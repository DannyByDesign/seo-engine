"""Polite, dependency-light site crawler used by the audit skills.

No API key required. Crawls same-site pages breadth-first from a start URL,
respects robots.txt (fetched with the engine's own User-Agent and RFC 9309
semantics — see lib/robots.py), and extracts the on-page signals the
SEO/GEO skills care about. Emits one JSON object per page (JSONL) so
snapshots diff cleanly between runs; skills store snapshots through
lib/snapshots.py, which adds the provenance sidecar diffing depends on.

Record schema v2 essentials:
* `error` / `error_type` carry fetch failures (`final_url` never holds
  exception text). `error_type == "too_many_redirects"` is THE redirect-loop
  signal — a genuine loop never yields a followable chain, it raises.
* `redirect_chain` records per-hop {url, status, location} dicts so new-3xx
  regressions and hop analysis are possible from snapshots alone.
* Links are harvested only from same-site, robots-allowed, status-200 HTML;
  rel=nofollow links are recorded in `nofollow_links` but never enqueued;
  noindex pages are still crawled and followed (noindex is not nofollow).

For JavaScript-rendered sites where raw HTML is missing content, skills fall
back to Firecrawl (see lib/firecrawl.py) when FIRECRAWL_API_KEY is set.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin, urldefrag, urlparse

from bs4 import BeautifulSoup

from . import http_util, robots, urlnorm

CRAWL_DELAY_SECONDS = 1.0
DEFAULT_MAX_PAGES = 500
MAX_BODY_BYTES = 2 * 1024 * 1024
SCHEMA_VERSION = 2

_HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")
_TRACKING_PREFIXES = ("utm_", "fbclid=", "gclid=", "msclkid=", "mc_eid=", "igshid=")


@dataclass
class PageRecord:
    url: str
    fetched_at: float
    status: int
    error: str = ""
    error_type: str = ""
    redirect_chain: list[dict] = field(default_factory=list)
    final_url: str = ""
    content_type: str = ""
    title: str = ""
    meta_description: str = ""
    meta_robots: str = ""
    x_robots_tag: str = ""
    canonical: str = ""
    h1: list[str] = field(default_factory=list)
    h2: list[str] = field(default_factory=list)
    lang: str = ""
    hreflang: list[dict[str, str]] = field(default_factory=list)
    internal_links: list[str] = field(default_factory=list)
    external_links: list[str] = field(default_factory=list)
    nofollow_links: list[str] = field(default_factory=list)
    images_missing_alt: list[str] = field(default_factory=list)
    json_ld_types: list[str] = field(default_factory=list)
    json_ld_errors: list[str] = field(default_factory=list)
    og: dict[str, str] = field(default_factory=dict)
    twitter: dict[str, str] = field(default_factory=dict)
    word_count: int = 0
    content_hash: str = ""
    depth: int = 0
    discovered_from: str = ""


def normalize_url(base: str, href: str) -> Optional[str]:
    """Resolve, strip fragments, drop non-http(s) and common tracking params.
    Never raises — a malformed href in someone's markup must not kill a
    500-page crawl."""
    if not href:
        return None
    href = href.strip()
    if href.startswith(("mailto:", "tel:", "javascript:", "data:")):
        return None
    try:
        absolute, _ = urldefrag(urljoin(base, href))
        parsed = urlparse(absolute)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    query = "&".join(
        p for p in parsed.query.split("&")
        if p and not any(p.lower().startswith(prefix) for prefix in _TRACKING_PREFIXES)
    )
    rebuilt = parsed._replace(query=query).geturl()
    return rebuilt.rstrip("/") if parsed.path in ("", "/") and not query else rebuilt


def _read_capped_body(resp) -> bytes:
    """Read at most MAX_BODY_BYTES from a streamed response."""
    chunks: list[bytes] = []
    read = 0
    for chunk in resp.iter_content(chunk_size=65536):
        chunks.append(chunk)
        read += len(chunk)
        if read >= MAX_BODY_BYTES:
            break
    return b"".join(chunks)


def _fetch(url: str, delay: float) -> PageRecord:
    """Fetch one URL into a PageRecord (no extraction yet). Reads a body only
    for status-200 HTML under the size cap; classifies transport errors."""
    record = PageRecord(url=url, fetched_at=time.time(), status=0)
    try:
        resp = http_util.get(url, min_interval=delay, stream=True)
    except http_util.HttpError as exc:
        record.status = -1
        record.error = str(exc)
        record.error_type = exc.error_type or "other"
        if exc.response is not None:
            record.redirect_chain = [
                {"url": r.url, "status": r.status_code,
                 "location": r.headers.get("Location", "")}
                for r in (exc.response.history or [])
            ]
        return record

    try:
        record.status = resp.status_code
        record.final_url = resp.url
        record.content_type = resp.headers.get("Content-Type", "")
        record.x_robots_tag = resp.headers.get("X-Robots-Tag", "")
        record.redirect_chain = [
            {"url": r.url, "status": r.status_code,
             "location": r.headers.get("Location", "")}
            for r in resp.history
        ]

        is_html = any(t in record.content_type.lower() for t in _HTML_CONTENT_TYPES)
        declared_len = resp.headers.get("Content-Length", "")
        too_big = declared_len.isdigit() and int(declared_len) > MAX_BODY_BYTES
        if record.status == 200 and is_html and not too_big:
            body = _read_capped_body(resp)
            resp._content = body
            record._body_text = resp.text
    finally:
        resp.close()
    return record


def _extract(record: PageRecord, root_host: str, include_subdomains: bool) -> PageRecord:
    """Parse the fetched HTML body (if any) into the record's fields."""
    body_text = getattr(record, "_body_text", None)
    if body_text is None:
        return record
    del record._body_text
    if not body_text:
        return record

    base_url = record.final_url or record.url
    soup = BeautifulSoup(body_text, "lxml")

    if soup.title and soup.title.string:
        record.title = soup.title.string.strip()
    for meta in soup.find_all("meta"):
        name = (meta.get("name") or "").lower()
        prop = (meta.get("property") or "").lower()
        content = (meta.get("content") or "").strip()
        if name == "description":
            record.meta_description = content
        elif name == "robots":
            record.meta_robots = content
        elif prop.startswith("og:"):
            record.og[prop] = content
        elif name.startswith("twitter:") or prop.startswith("twitter:"):
            record.twitter[name or prop] = content

    canonical_tag = soup.find("link", rel=lambda v: v and "canonical" in v)
    if canonical_tag:
        record.canonical = normalize_url(base_url, canonical_tag.get("href", "")) or ""

    html_tag = soup.find("html")
    if html_tag:
        record.lang = (html_tag.get("lang") or "").strip()

    for alt_link in soup.find_all("link", rel="alternate"):
        if alt_link.get("hreflang"):
            record.hreflang.append({
                "hreflang": alt_link["hreflang"],
                "href": alt_link.get("href", ""),
            })

    record.h1 = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
    record.h2 = [h.get_text(" ", strip=True) for h in soup.find_all("h2")]

    internal, external, nofollow = set(), set(), set()
    for anchor in soup.find_all("a", href=True):
        normalized = normalize_url(base_url, anchor["href"])
        if not normalized:
            continue
        rels = [r.lower() for r in (anchor.get("rel") or [])]
        if "nofollow" in rels:
            nofollow.add(normalized)
            continue
        if urlnorm.same_site(normalized, root_host, include_subdomains=include_subdomains):
            internal.add(normalized)
        else:
            external.add(normalized)
    record.internal_links = sorted(internal)
    record.external_links = sorted(external)
    record.nofollow_links = sorted(nofollow)

    for img in soup.find_all("img"):
        if not (img.get("alt") or "").strip():
            src = img.get("src") or img.get("data-src") or ""
            if src:
                record.images_missing_alt.append(normalize_url(base_url, src) or src)

    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text() or ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            record.json_ld_errors.append(f"invalid JSON-LD: {exc}")
            continue
        nodes = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for node in nodes:
            if isinstance(node, dict) and node.get("@type"):
                node_type = node["@type"]
                record.json_ld_types.extend(node_type if isinstance(node_type, list) else [node_type])

    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    record.word_count = len(text.split())
    record.content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return record


def _drop_pending_body(record: PageRecord) -> None:
    if getattr(record, "_body_text", None) is not None:
        del record._body_text


def _robots_status(policy: robots.RobotsPolicy) -> str:
    if policy.source_status == 200:
        return "ok"
    if policy.source_status in (401, 403):
        return "unauthorized_allow_all"
    if 400 <= policy.source_status < 500:
        return "not_found"
    if policy.source_status >= 500:
        return "server_error_blocked"
    return "network_error_blocked"


def crawl(
    start_url: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    delay: float = CRAWL_DELAY_SECONDS,
    ignore_robots: bool = False,
    include_subdomains: bool = False,
    stats: Optional[dict] = None,
) -> Iterable[PageRecord]:
    """BFS crawl constrained to the start URL's site. Yields PageRecords.

    `ignore_robots` exists ONLY for crawling your own localhost/staging builds
    that block all bots — never use it against sites you don't own.

    Pass a dict as `stats` to receive crawl telemetry the records alone can't
    carry: robots_status, all_blocked, blocked_by_robots, truncated.
    """
    root_host = urlparse(start_url).netloc
    stats = stats if stats is not None else {}
    stats.update({
        "robots_status": "ignored" if ignore_robots else "",
        "blocked_by_robots": 0,
        "all_blocked": False,
        "truncated": False,
    })

    policy: Optional[robots.RobotsPolicy] = None
    if not ignore_robots:
        policy = robots.fetch(start_url)
        stats["robots_status"] = _robots_status(policy)
        if policy.fetch_error:
            stats["robots_error"] = policy.fetch_error
        crawl_delay = policy.crawl_delay(http_util.USER_AGENT)
        if crawl_delay:
            delay = max(delay, float(crawl_delay))
        if policy.disallow_all:
            stats["all_blocked"] = True
            return

    start = normalize_url(start_url, start_url) or start_url
    queue: deque[tuple[str, int, str]] = deque([(start, 0, "")])
    seen: set[str] = {urlnorm.canonical_key(start)}
    fetched = 0

    while queue and fetched < max_pages:
        url, depth, referrer = queue.popleft()
        if policy is not None and not policy.allowed(http_util.USER_AGENT, url):
            stats["blocked_by_robots"] += 1
            continue

        record = _fetch(url, delay)
        record.depth = depth
        record.discovered_from = referrer
        fetched += 1

        follow_links = record.status == 200
        if follow_links and policy is not None and record.final_url:
            if not policy.allowed(http_util.USER_AGENT, record.final_url):
                stats["blocked_by_robots"] += 1
                follow_links = False
        if follow_links and record.final_url and not urlnorm.same_site(
                record.final_url, root_host, include_subdomains=include_subdomains):
            follow_links = False

        if follow_links:
            record = _extract(record, root_host, include_subdomains)
        else:
            _drop_pending_body(record)

        yield record

        if not follow_links:
            continue
        for link in record.internal_links:
            key = urlnorm.canonical_key(link)
            if key not in seen and len(seen) < max_pages * 5:
                seen.add(key)
                queue.append((link, depth + 1, url))

    if queue and fetched >= max_pages:
        stats["truncated"] = True
    if fetched == 0 and stats.get("blocked_by_robots", 0) > 0:
        stats["all_blocked"] = True


def crawl_to_file(start_url: str, out_path: Path, **kwargs) -> dict:
    """Run a crawl and write JSONL + a summary dict (see snapshots.new_crawl,
    which stores this summary in the snapshot's provenance sidecar)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stats: dict = {}
    counts = {"pages": 0, "errors": 0, "non_200": 0}
    with out_path.open("w", encoding="utf-8") as fh:
        for record in crawl(start_url, stats=stats, **kwargs):
            fh.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
            counts["pages"] += 1
            if record.status == -1:
                counts["errors"] += 1
            elif record.status != 200:
                counts["non_200"] += 1
    counts.update(stats)
    counts["schema_version"] = SCHEMA_VERSION
    return counts
