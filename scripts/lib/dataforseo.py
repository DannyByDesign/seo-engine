"""DataForSEO API client. Optional — degrades to "not configured" if unset.

Auth: HTTP Basic (dedicated API login/password, not your dashboard password).
Base https://api.dataforseo.com/v3/. Mode (live/synchronous vs task-based/
queued) varies by namespace — do not assume uniformity across endpoints.

Two DataForSEO wire quirks this client absorbs:
* The API returns HTTP 200 even for failures — real status lives in the
  top-level `status_code` and per-task `tasks[i].status_code` (20000-series
  = ok). `_check` raises DataForSeoError on anything else, so an auth
  failure can never masquerade as an empty-but-successful result.
* On-Page task completion is signalled by `result[0].crawl_progress ==
  "finished"` — `status_message` is "Ok." from the moment the task is
  accepted, long before the crawl finishes.

Retry note: task_post and live calls are POSTs on a pay-per-call API —
http_util's "auto" policy retries them only on 429 (rejected, not billed),
never after an ambiguous 5xx/timeout that may already have been charged.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from . import http_util
from .config import Config

BASE_URL = "https://api.dataforseo.com/v3"
_HINT = "Create API credentials in the DataForSEO dashboard (distinct from your login password)."

_OK_CODES = {20000, 20100}


class DataForSeoError(RuntimeError):
    """DataForSEO reported an application-level error inside an HTTP 200."""


def _auth(cfg: Config) -> tuple[str, str]:
    login = cfg.require("DATAFORSEO_LOGIN", _HINT)
    password = cfg.require("DATAFORSEO_PASSWORD", _HINT)
    return login, password


def _check(payload: dict[str, Any], path: str) -> dict[str, Any]:
    top = payload.get("status_code")
    if top not in _OK_CODES:
        raise DataForSeoError(
            f"{path}: status_code={top} {payload.get('status_message', '')!r}"
        )
    for task in payload.get("tasks") or []:
        code = task.get("status_code")
        if code not in _OK_CODES:
            raise DataForSeoError(
                f"{path}: task {task.get('id', '?')} failed: "
                f"status_code={code} {task.get('status_message', '')!r}"
            )
    return payload


def _post(cfg: Config, path: str, payload: list[dict[str, Any]],
          timeout: float = 60.0) -> dict[str, Any]:
    resp = http_util.post(
        f"{BASE_URL}{path}", auth=_auth(cfg), json_body=payload,
        min_interval=0.2, timeout=timeout, check=True,
    )
    return _check(resp.json(), path)


def _get(cfg: Config, path: str) -> dict[str, Any]:
    resp = http_util.get(
        f"{BASE_URL}{path}", auth=_auth(cfg), min_interval=0.2, check=True,
    )
    return _check(resp.json(), path)


def serp_live(cfg: Config, keyword: str, location_code: int = 2840, language_code: str = "en") -> dict[str, Any]:
    """Live Google organic SERP. location_code 2840 = United States."""
    return _post(cfg, "/serp/google/organic/live/advanced", [{
        "keyword": keyword, "location_code": location_code, "language_code": language_code,
    }], timeout=120.0)


def search_volume(cfg: Config, keywords: list[str], location_code: int = 2840) -> dict[str, Any]:
    """Max 1,000 keywords per request; this endpoint is limited to 12 req/min."""
    return _post(cfg, "/keywords_data/google_ads/search_volume/live", [{
        "keywords": keywords[:1000], "location_code": location_code,
    }], timeout=120.0)


def keyword_difficulty(cfg: Config, keywords: list[str], location_code: int = 2840,
                       language_code: str = "en") -> dict[str, Any]:
    """DataForSEO Labs bulk keyword difficulty (0-100) — max 1,000 keywords."""
    return _post(cfg, "/dataforseo_labs/google/bulk_keyword_difficulty/live", [{
        "keywords": keywords[:1000], "location_code": location_code, "language_code": language_code,
    }], timeout=120.0)


def volume_and_difficulty(cfg: Config, keywords: list[str]) -> dict[str, dict[str, Any]]:
    """{keyword: {msv, kd}} from search_volume + keyword_difficulty; a failure of
    one call leaves that field None rather than failing the whole lookup."""
    out: dict[str, dict[str, Any]] = {k: {"msv": None, "kd": None} for k in keywords}
    if not keywords:
        return out
    try:
        for item in (search_volume(cfg, keywords)["tasks"][0].get("result") or []):
            if item.get("keyword") in out:
                out[item["keyword"]]["msv"] = item.get("search_volume")
    except Exception:
        pass
    try:
        for item in (keyword_difficulty(cfg, keywords)["tasks"][0].get("result") or []):
            if item.get("keyword") in out:
                out[item["keyword"]]["kd"] = item.get("keyword_difficulty")
    except Exception:
        pass
    return out


def backlinks_summary(cfg: Config, target: str) -> dict[str, Any]:
    return _post(cfg, "/backlinks/summary/live", [{"target": target}])


def backlinks_list(
    cfg: Config, target: str, limit: int = 100, offset: int = 0,
    order_by: Optional[str] = "first_seen,asc",
) -> dict[str, Any]:
    """`order_by=first_seen,asc` makes the first-N window stable across runs —
    required for honest new/lost diffing."""
    task: dict[str, Any] = {"target": target, "limit": limit, "offset": offset}
    if order_by:
        task["order_by"] = [order_by]
    return _post(cfg, "/backlinks/backlinks/live", [task])


def onpage_start_crawl(cfg: Config, target: str, max_crawl_pages: int = 100,
                       pingback_url: Optional[str] = None) -> str:
    """Submits a crawl job, returns the task id to poll with onpage_summary()."""
    task = {"target": target, "max_crawl_pages": max_crawl_pages}
    if pingback_url:
        task["pingback_url"] = pingback_url
    result = _post(cfg, "/on_page/task_post", [task])
    return result["tasks"][0]["id"]


def _crawl_progress(summary: dict[str, Any]) -> str:
    tasks = summary.get("tasks") or [{}]
    results = tasks[0].get("result") or [{}]
    return str(results[0].get("crawl_progress") or "")


def onpage_summary(cfg: Config, task_id: str) -> dict[str, Any]:
    return _get(cfg, f"/on_page/summary/{task_id}")


def onpage_wait_and_get_summary(cfg: Config, task_id: str, timeout: int = 600,
                                poll_interval: int = 15) -> dict[str, Any]:
    """Poll until `crawl_progress == "finished"` or timeout. (status_message
    is "Ok." the whole time the crawl runs — it signals acceptance, not
    completion.)"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        summary = onpage_summary(cfg, task_id)
        if _crawl_progress(summary) == "finished":
            return summary
        time.sleep(poll_interval)
    raise TimeoutError(f"on_page task {task_id} did not finish within {timeout}s")


def domain_intersection(cfg: Config, target1: str, target2: str,
                        location_code: int = 2840, language_code: str = "en") -> dict[str, Any]:
    """Keywords both domains rank for — useful for competitor gap analysis.
    Labs endpoints require a language."""
    return _post(cfg, "/dataforseo_labs/google/domain_intersection/live", [{
        "target1": target1, "target2": target2,
        "location_code": location_code, "language_code": language_code,
    }])


def competitors_domain(cfg: Config, target: str, location_code: int = 2840,
                       limit: int = 20, language_code: str = "en") -> dict[str, Any]:
    return _post(cfg, "/dataforseo_labs/google/competitors_domain/live", [{
        "target": target, "location_code": location_code, "limit": limit,
        "language_code": language_code,
    }])


def keyword_ideas(cfg: Config, keywords: list[str], location_code: int = 2840,
                  language_code: str = 'en', limit: int = 20) -> dict[str, Any]:
    return _post(cfg, '/dataforseo_labs/google/keyword_ideas/live', [{
        'keywords': keywords, 'location_code': location_code, 'language_code': language_code,
        'limit': limit, 'include_serp_info': True}])


def ranked_keywords(cfg: Config, target: str, location_code: int = 2840,
                    language_code: str = 'en', limit: int = 20) -> dict[str, Any]:
    return _post(cfg, '/dataforseo_labs/google/ranked_keywords/live', [{
        'target': target, 'location_code': location_code, 'language_code': language_code,
        'limit': limit, 'item_types': ['organic']}])
