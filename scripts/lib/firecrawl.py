"""Firecrawl client (v2 API) — JS-rendering scrape/crawl. Optional; used by
seo-technical-audit to diff raw-HTML content against rendered content,
catching JS-hydration SEO/GEO blind spots (see skills/seo-references/
red-flags.md §4 and geo-playbook.md §11 — no major AI crawler executes JS).

The cloud API requires authentication on every endpoint — there is no
keyless tier. Calls without FIRECRAWL_API_KEY raise MissingConfigError with
remediation text instead of an opaque 401.
"""

from __future__ import annotations

from typing import Any, Optional

from . import http_util
from .config import Config

BASE_URL = "https://api.firecrawl.dev/v2"
_HINT = "Get a key at firecrawl.dev (free tier: 1,000 credits/month). The cloud API requires auth on all endpoints."


def _headers(cfg: Config) -> dict[str, str]:
    key = cfg.require("FIRECRAWL_API_KEY", _HINT)
    return {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}


def scrape(cfg: Config, url: str, formats: Optional[list[str]] = None) -> dict[str, Any]:
    """Single-URL rendered scrape. formats: any of markdown, html, rawHtml,
    screenshot, links (default: markdown + rawHtml, so callers can diff
    rendered vs. raw content directly)."""
    resp = http_util.post(
        f"{BASE_URL}/scrape", headers=_headers(cfg),
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
