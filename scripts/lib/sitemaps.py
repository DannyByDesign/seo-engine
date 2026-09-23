"""Sitemap discovery and URL extraction.

Discovery order (each is a real-world default the previous one misses):
  1. `Sitemap:` lines in robots.txt (the authoritative declaration)
  2. /sitemap.xml
  3. /sitemap_index.xml   (Yoast and other WordPress SEO plugins)
  4. /wp-sitemap.xml      (WordPress core)

Sitemap indexes are followed one level deep. Used by orphan detection
(the known-URL universe a link-following crawl cannot see) and by the
technical audit's crawl-vs-sitemap diff.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import urljoin

from . import http_util
from .robots import RobotsPolicy

DEFAULT_SITEMAP_PATHS = ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml")
MAX_CHILD_SITEMAPS = 50


def discover(site_url: str, policy: Optional[RobotsPolicy] = None) -> list[str]:
    """Candidate sitemap URLs, robots.txt declarations first, deduped."""
    candidates: list[str] = []
    if policy is not None:
        candidates.extend(urljoin(site_url, s) for s in policy.sitemaps)
    candidates.extend(urljoin(site_url, p) for p in DEFAULT_SITEMAP_PATHS)
    seen: set[str] = set()
    ordered = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _parse_sitemap_xml(body: bytes) -> tuple[str, list[str]]:
    """Returns ("urlset"|"sitemapindex"|"unknown", [loc values])."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return "unknown", []
    kind = _localname(root.tag)
    locs = []
    for child in root:
        for sub in child:
            if _localname(sub.tag) == "loc" and (sub.text or "").strip():
                locs.append(sub.text.strip())
    if kind not in ("urlset", "sitemapindex"):
        kind = "unknown"
    return kind, locs


def fetch_url_set(
    site_url: str,
    policy: Optional[RobotsPolicy] = None,
    *,
    max_urls: int = 100_000,
) -> dict:
    """Fetch the site's sitemap URL inventory.

    Returns {"found": bool, "sitemaps_read": [...], "page_urls": [...],
             "truncated": bool, "errors": [...]}. `page_urls` are raw, as
    declared — callers fold with urlnorm.canonical_key for identity work.
    """
    result: dict = {"found": False, "sitemaps_read": [], "page_urls": [],
                    "truncated": False, "errors": []}
    page_urls: list[str] = []

    def read_one(url: str) -> Optional[tuple[str, list[str]]]:
        try:
            resp = http_util.get(url)
        except http_util.HttpError as exc:
            result["errors"].append(str(exc))
            return None
        if resp.status_code != 200:
            return None
        if url.endswith(".gz"):
            result["errors"].append(f"unsupported gzip sitemap skipped: {url}")
            return None
        return _parse_sitemap_xml(resp.content)

    for candidate in discover(site_url, policy):
        parsed = read_one(candidate)
        if parsed is None:
            continue
        kind, locs = parsed
        if kind == "unknown":
            continue
        result["found"] = True
        result["sitemaps_read"].append(candidate)
        if kind == "urlset":
            page_urls.extend(locs)
        else:
            for child_url in locs[:MAX_CHILD_SITEMAPS]:
                child = read_one(child_url)
                if child is None:
                    continue
                child_kind, child_locs = child
                if child_kind == "urlset":
                    result["sitemaps_read"].append(child_url)
                    page_urls.extend(child_locs)
            if len(locs) > MAX_CHILD_SITEMAPS:
                result["truncated"] = True
                result["errors"].append(
                    f"sitemap index {candidate} lists {len(locs)} child sitemaps; "
                    f"only the first {MAX_CHILD_SITEMAPS} were read"
                )
        break

    if len(page_urls) > max_urls:
        page_urls = page_urls[:max_urls]
        result["truncated"] = True
    result["page_urls"] = page_urls
    return result
