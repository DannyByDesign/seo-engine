"""Ahrefs API v3 client. Optional — degrades to "not configured" if unset.

Auth: Bearer token. Base https://api.ahrefs.com/v3/. Each endpoint takes a
`select` param (comma-separated fields). Min charge 50 units/request; default
60 req/min. See the api-reference in skills/seo-references/ for plan gating
and the cost model.

Ahrefs v3 point-in-time endpoints REQUIRE a `date` (and organic endpoints a
`country`) — omitting them is a guaranteed 400. Snapshot-style endpoints
(all-backlinks, broken-backlinks) query the live index and take no date.
"""

from __future__ import annotations

from datetime import date as _date
from typing import Any, Optional

from . import http_util
from .config import Config

BASE_URL = "https://api.ahrefs.com/v3"
_HINT = "Create a key in Ahrefs > Account Settings > API Keys (owner/admin only)."


def _today() -> str:
    return _date.today().isoformat()


def _get(cfg: Config, path: str, params: dict[str, Any]) -> dict[str, Any]:
    key = cfg.require("AHREFS_API_KEY", _HINT)
    resp = http_util.get(
        f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        params=params,
        min_interval=1.0,  # 60 req/min default limit
        cache_dir=cfg.state_dir / "http-cache", cache_ttl=3600,
        check=True,
    )
    return resp.json()


def domain_rating(cfg: Config, target: str, date: Optional[str] = None) -> dict[str, Any]:
    return _get(cfg, "/site-explorer/domain-rating", {
        "target": target, "date": date or _today(),
        "select": "domain_rating,ahrefs_rank",
    })


def all_backlinks(
    cfg: Config, target: str, limit: int = 100,
    select: str = "url_from,url_to,domain_rating_source,first_seen,link_type",
    order_by: Optional[str] = "first_seen:asc",
    offset: int = 0,
) -> dict[str, Any]:
    """Live-index backlink rows. `order_by=first_seen:asc` makes the first-N
    window stable across runs — required for honest new/lost diffing."""
    params: dict[str, Any] = {
        "target": target, "limit": limit, "select": select, "offset": offset,
    }
    if order_by:
        params["order_by"] = order_by
    return _get(cfg, "/site-explorer/all-backlinks", params)


def broken_backlinks(cfg: Config, target: str, limit: int = 100) -> dict[str, Any]:
    return _get(cfg, "/site-explorer/broken-backlinks", {
        "target": target, "limit": limit,
        "select": "url_from,url_to,domain_rating_source,http_code",
    })


def backlinks_stats(cfg: Config, target: str, date: Optional[str] = None) -> dict[str, Any]:
    """Profile totals (live backlinks / referring domains) — used as the
    refuse-to-diff guard before window-limited backlink fetches."""
    return _get(cfg, "/site-explorer/backlinks-stats", {
        "target": target, "date": date or _today(),
    })


def organic_keywords(
    cfg: Config, target: str, country: str = "us", limit: int = 100,
    date: Optional[str] = None,
) -> dict[str, Any]:
    return _get(cfg, "/site-explorer/organic-keywords", {
        "target": target, "country": country, "limit": limit,
        "date": date or _today(),
        "select": "keyword,best_position,volume,sum_traffic,best_position_url",
    })


def organic_competitors(
    cfg: Config, target: str, limit: int = 20,
    country: str = "us", date: Optional[str] = None,
) -> dict[str, Any]:
    return _get(cfg, "/site-explorer/organic-competitors", {
        "target": target, "limit": limit, "country": country,
        "date": date or _today(),
        "select": "competitor_domain,common_keywords,share",
    })


def keywords_overview(
    cfg: Config, keywords: list[str], country: str = "us",
    date: Optional[str] = None,
) -> dict[str, Any]:
    return _get(cfg, "/keywords-explorer/overview", {
        "keywords": ",".join(keywords), "country": country,
        "date": date or _today(),
        "select": "keyword,volume,keyword_difficulty,cpc",
    })
