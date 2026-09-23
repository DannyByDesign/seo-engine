"""Firecrawl client (v2 API) — JS-rendering scrape/crawl. Optional; used by
seo-technical-audit to diff raw-HTML content against rendered content,
catching JS-hydration SEO/GEO blind spots (see skills/seo-references/
red-flags.md §4 and geo-playbook.md §11 for platform-specific rendering limits).

Search and scrape support limited anonymous use in current vendor documentation.
Other endpoints retain the configured-key contract; availability and quota are
determined by the server rather than assumed from credential presence.
"""

from __future__ import annotations

from typing import Any, Optional

from . import http_util
from .config import Config

BASE_URL = "https://api.firecrawl.dev/v2"
_HINT = "Get a key at firecrawl.dev (free tier: 1,000 credits/month). The cloud API requires auth on all endpoints."


def _headers(cfg: Config, anonymous_allowed: bool = False) -> dict[str, str]:
    if anonymous_allowed and not cfg.has('FIRECRAWL_API_KEY'):
        return {'Content-Type': 'application/json'}
    key = cfg.require("FIRECRAWL_API_KEY", _HINT)
    return {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}


def scrape(cfg: Config, url: str, formats: Optional[list[str]] = None) -> dict[str, Any]:
    """Single-URL rendered scrape. formats: any of markdown, html, rawHtml,
    screenshot, links (default: markdown + rawHtml, so callers can diff
    rendered vs. raw content directly)."""
    resp = http_util.post(
        f"{BASE_URL}/scrape", headers=_headers(cfg, anonymous_allowed=True),
        json_body={"url": url, "formats": formats or ["markdown", "rawHtml"]},
        min_interval=0.5, timeout=120.0, check=True,
    )
    return resp.json()


def map_urls(cfg: Config, url: str, limit: int = 5000) -> list[str]:
    """Near-instant full URL discovery for a domain (no content fetch).
    v2 returns links as objects ({"url", "title", ...}); v1 returned bare
    strings — both shapes are handled."""
    resp = http_util.post(
        f"{BASE_URL}/map", headers=_headers(cfg),
        json_body={"url": url, "limit": limit},
        min_interval=0.5, timeout=120.0, check=True,
    )
    links = resp.json().get("links", [])
    urls: list[str] = []
    for link in links:
        if isinstance(link, str):
            urls.append(link)
        elif isinstance(link, dict) and link.get("url"):
            urls.append(link["url"])
    return urls


def search_raw(cfg: Config, query: str, limit: int = 10, tbs: Optional[str] = None,
               country: Optional[str] = None, location: Optional[str] = None) -> dict[str, Any]:
    """Retain the full provider envelope for provenance and failure handling."""
    body: dict[str, Any] = {"query": query, "limit": limit}
    if country: body['country'] = country
    if location: body['location'] = location
    if tbs:
        body["tbs"] = tbs
    resp = http_util.post(
        f"{BASE_URL}/search", headers=_headers(cfg, anonymous_allowed=True), json_body=body,
        min_interval=0.5, timeout=120.0, check=True,
    )
    raw = resp.json()
    if not isinstance(raw, dict) or raw.get('success') is False or 'data' not in raw:
        raise ValueError('Firecrawl search returned an error or unrecognized response')
    return raw


def search(cfg: Config, query: str, limit: int = 10, tbs: Optional[str] = None) -> list[dict[str, Any]]:
    """Normalized web results; use search_raw for complete collection receipts."""
    data = search_raw(cfg, query, limit, tbs)['data']
    if isinstance(data, dict):
        data = data.get("web", []) or []
    return [{"url": d.get("url"), "title": d.get("title"), "description": d.get("description")}
            for d in data if isinstance(d, dict) and d.get("url")]


def start_crawl(cfg: Config, url: str, limit: int = 100) -> str:
    """Kicks off an async recursive crawl; returns a job id for get_crawl_status()."""
    resp = http_util.post(
        f"{BASE_URL}/crawl", headers=_headers(cfg),
        json_body={"url": url, "limit": limit},
        min_interval=0.5, timeout=120.0, check=True,
    )
    return resp.json()["id"]


def get_crawl_status(cfg: Config, job_id: str) -> dict[str, Any]:
    resp = http_util.get(
        f"{BASE_URL}/crawl/{job_id}", headers=_headers(cfg), check=True,
    )
    return resp.json()


def diff_raw_vs_rendered(cfg: Config, url: str) -> dict[str, Any]:
    """Fetches raw HTML directly and rendered content via Firecrawl, and
    reports the word-count gap — a large gap indicates JS-dependent content
    that AI crawlers (which do not execute JavaScript — geo-playbook.md §11)
    never see, even where Googlebot renders it."""
    import re
    from bs4 import BeautifulSoup

    raw_resp = http_util.get(url)
    raw_soup = BeautifulSoup(raw_resp.text, "lxml")
    for tag in raw_soup(["script", "style", "noscript"]):
        tag.decompose()
    raw_text = re.sub(r"\s+", " ", raw_soup.get_text(" ", strip=True))

    rendered = scrape(cfg, url, formats=["markdown"])
    rendered_text = rendered.get("data", rendered).get("markdown", "")

    raw_words = len(raw_text.split())
    rendered_words = len(rendered_text.split())
    return {
        "url": url,
        "raw_word_count": raw_words,
        "rendered_word_count": rendered_words,
        "gap_ratio": (rendered_words - raw_words) / max(rendered_words, 1),
        "likely_js_dependent": rendered_words > raw_words * 1.5 and rendered_words > 100,
    }
