"""Bing Webmaster Tools API client. Optional — degrades to "not configured".

This API is de facto frozen (docs last substantively updated ~2022); use it
only for crawl-stats/query-stats reads plus sitemap (feed) submission. For
URL submission, use indexnow.py instead — Bing itself steers URL-submission
use cases there.

Wire format quirks this client absorbs so callers don't have to:
* Every JSON response wraps its payload as {"d": ...} — unwrapped here.
* Reads are GETs with an `apikey` query param; mutations (SubmitFeed) are
  POSTs with the JSON body {"siteUrl", "feedUrl"}. There is no
  "SubmitSitemap" method — sitemap submission is SubmitFeed.
"""

from __future__ import annotations

from typing import Any

from . import http_util
from .config import Config

BASE_URL = "https://ssl.bing.com/webmaster/api.svc/json"
_HINT = "Get a key from the Bing Webmaster Tools dashboard (bing.com/webmasters)."


def _unwrap(payload: Any) -> Any:
    if isinstance(payload, dict) and "d" in payload:
        return payload["d"]
    return payload


def _get(cfg: Config, method: str, params: dict[str, Any]) -> Any:
    key = cfg.require("BING_WEBMASTER_API_KEY", _HINT)
    resp = http_util.get(
        f"{BASE_URL}/{method}", params={"apikey": key, **params}, check=True,
    )
    return _unwrap(resp.json())


def _post(cfg: Config, method: str, body: dict[str, Any]) -> Any:
    key = cfg.require("BING_WEBMASTER_API_KEY", _HINT)
    resp = http_util.post(
        f"{BASE_URL}/{method}", params={"apikey": key}, json_body=body, check=True,
    )
    return _unwrap(resp.json()) if resp.content else None


def submit_sitemap(cfg: Config, site_url: str, sitemap_url: str) -> Any:
    """Submit a sitemap ("feed"). POST SubmitFeed — the GET SubmitSitemap
    method this used to call does not exist in the API."""
    return _post(cfg, "SubmitFeed", {"siteUrl": site_url, "feedUrl": sitemap_url})


def get_crawl_stats(cfg: Config, site_url: str) -> Any:
    return _get(cfg, "GetCrawlStats", {"siteUrl": site_url})


def get_query_stats(cfg: Config, site_url: str) -> Any:
    return _get(cfg, "GetQueryStats", {"siteUrl": site_url})
