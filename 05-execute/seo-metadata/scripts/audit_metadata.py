"""Audit page titles, meta descriptions, and Open Graph/Twitter Card tags.

Crawl I/O goes through the shared snapshot store (scripts.lib.snapshots):
the newest snapshot for the configured site is reused when it is under 24
hours old; otherwise (or with --force-recrawl) a fresh crawl is taken and
stored with provenance for other skills to reuse.

Flags, per references/seo-playbook.md §1 (people-first) and §8 (structured
data / rich results depend on clean on-page signals):
  - missing title / missing meta description
  - duplicate titles / duplicate meta descriptions across >1 page identity
    (grouped by urlnorm.canonical_key of the FINAL destination URL, so
    /about vs /about/ or a www alias of the same page is ONE page, not a
    false duplicate; one finding is emitted per duplicated value, listing
    every affected URL)
  - title length outside ~30-60 chars (SERP truncation risk beyond ~60-70;
    Google renders by pixel width, not a hard char count, so this is a
    heuristic band, not a hard rule)
  - meta description length outside ~70-155 chars (too short wastes the
    summary/entice opportunity; too long gets truncated)
  - missing og:title / og:description / og:image (social-preview + some AI
    crawlers read OG tags as a structured summary fallback)
  - missing/empty twitter:card (Twitter Card markup; without it, X/Twitter
    and other consumers fall back to OG tags where present, or render a
    bare link)
  - H1/title wildly unrelated (potential mismatch/confusion signal) using a
    cheap token-overlap heuristic, not an LLM judgment call

Only indexable pages are audited (status 200, HTML, not noindex via the
meta robots tag OR the X-Robots-Tag header — see scripts.lib.pagerules).

This script only reads and reports. It never edits source files -- SKILL.md
instructs the calling agent to locate and edit the actual template/component
source per the flagged URL, never rendered HTML output.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


if sys.version_info < (3, 9):
    sys.exit("seo-engine requires Python 3.9+ (found %d.%d)" % sys.version_info[:2])


def _find_engine_root(start: Path) -> Path:
    import os

    env = os.environ.get("SEO_ENGINE_ROOT")
    if env and (Path(env) / "scripts" / "lib" / "config.py").is_file():
        return Path(env)
    for candidate in [start, *start.parents]:
        if (candidate / "scripts" / "lib" / "config.py").is_file():
            return candidate
    raise SystemExit(
        "Could not locate seo-engine root (scripts/lib/config.py). If skills were "
        "copied (not symlinked), set SEO_ENGINE_ROOT=/path/to/seo-engine."
    )


sys.path.insert(0, str(_find_engine_root(Path(__file__).resolve())))
from scripts.lib import config as config_module
from scripts.lib import pagerules, snapshots, urlnorm

TITLE_MIN = 30
TITLE_MAX = 60
DESCRIPTION_MIN = 70
DESCRIPTION_MAX = 155
SNAPSHOT_MAX_AGE_HOURS = 24

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "how", "in", "into", "is", "it", "of", "on", "or", "our", "than", "that",
    "the", "their", "this", "to", "up", "vs", "was", "were", "will", "with",
    "your", "you", "we", "i", "us", "&", "-", "|", ":",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


@dataclass
class PageIssue:
    url: str
    severity: str
    problem: str
    detail: str
    current_value: Optional[str] = None
    affected_urls: Optional[list[str]] = None


@dataclass
class AuditResult:
    site_url: str
    snapshot_path: str
    pages_analyzed: int = 0
    issues: list[PageIssue] = field(default_factory=list)

    def add(self, url: str, severity: str, problem: str, detail: str,
            current_value: Optional[str] = None,
            affected_urls: Optional[list[str]] = None) -> None:
        self.issues.append(
            PageIssue(url, severity, problem, detail, current_value, affected_urls))


def _dedupe_by_identity(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """One record per folded FINAL-destination identity
    (urlnorm.canonical_key), restricted to indexable HTML pages
    (pagerules.is_indexable_html: 200, HTML, and not noindex via either the
    meta robots tag or the X-Robots-Tag header). /about and /about/, or a
    www alias fetched separately, fold to ONE page — auditing them twice
    would flag a page as a duplicate of itself."""
    by_key: dict[str, dict[str, Any]] = {}
    for rec in records:
        if not pagerules.is_indexable_html(rec):
            continue
        key = urlnorm.canonical_key(rec.get("final_url") or rec.get("url", ""))
        if key and key not in by_key:
            by_key[key] = rec
    return by_key


def audit(records: list[dict[str, Any]], site_url: str, snapshot_path: str) -> AuditResult:
    result = AuditResult(site_url=site_url, snapshot_path=snapshot_path)
    pages_by_key = _dedupe_by_identity(records)
    result.pages_analyzed = len(pages_by_key)

    titles_by_value: dict[str, list[str]] = defaultdict(list)
    descriptions_by_value: dict[str, list[str]] = defaultdict(list)

    for key in sorted(pages_by_key):
        page = pages_by_key[key]
        url = page.get("final_url") or page.get("url", "")
        title = (page.get("title") or "").strip()
        description = (page.get("meta_description") or "").strip()
        og = page.get("og") or {}
        twitter = page.get("twitter") or {}
        h1_list = page.get("h1") or []

        if title:
            titles_by_value[title].append(url)
        if description:
            descriptions_by_value[description].append(url)

        if not title:
            result.add(url, "high", "missing_title",
                       "No <title> element found. Google will synthesize one "
                       "(often from the H1 or link text) with no control over "
                       "the result.")
        if not description:
            result.add(url, "medium", "missing_meta_description",
                       "No meta description found. Google will auto-generate "
                       "a snippet from page content, which is frequently a "
                       "poor summary and loses a click-through opportunity.")

        if title:
            length = len(title)
            if length > TITLE_MAX:
                result.add(url, "medium", "title_too_long",
                           f"Title is {length} chars (recommended ~{TITLE_MIN}-{TITLE_MAX}). "
                           "Google truncates by pixel width, typically somewhere "
                           "past ~60 characters -- the end of this title is at "
                           "meaningful risk of being cut off in SERPs.",
                           current_value=title)
            elif length < TITLE_MIN:
                result.add(url, "low", "title_too_short",
                           f"Title is only {length} chars (recommended ~{TITLE_MIN}-{TITLE_MAX}). "
                           "Likely under-using available SERP space to describe "
                           "the page.",
                           current_value=title)

        if description:
            length = len(description)
            if length > DESCRIPTION_MAX:
                result.add(url, "low", "description_too_long",
                           f"Meta description is {length} chars (recommended "
                           f"~{DESCRIPTION_MIN}-{DESCRIPTION_MAX}). Likely truncated in SERPs.",
                           current_value=description)
            elif length < DESCRIPTION_MIN:
                result.add(url, "low", "description_too_short",
                           f"Meta description is only {length} chars (recommended "
                           f"~{DESCRIPTION_MIN}-{DESCRIPTION_MAX}). Wastes the "
                           "opportunity to summarize/entice in the SERP snippet.",
                           current_value=description)

        if not og.get("og:title"):
            result.add(url, "low", "missing_og_title",
                       "No og:title found -- social shares and link-preview "
                       "surfaces will fall back to an inconsistent default "
                       "(often the raw <title>, sometimes nothing).")
        if not og.get("og:description"):
            result.add(url, "low", "missing_og_description",
                       "No og:description found -- social share previews "
                       "will show no summary text or fall back unpredictably.")
        if not og.get("og:image"):
            result.add(url, "medium", "missing_og_image",
                       "No og:image found -- shares on social platforms and "
                       "messaging apps render as a bare text link with no "
                       "preview image, which measurably suppresses click-through.")

        if not (twitter.get("twitter:card") or "").strip():
            result.add(url, "low", "missing_twitter_card",
                       "No twitter:card meta tag found (or its content is "
                       "empty) -- X/Twitter and other Twitter-Card consumers "
                       "will fall back to Open Graph tags where present, or "
                       "render the share as a bare link. Add twitter:card "
                       "(usually 'summary' or 'summary_large_image') in the "
                       "same template that emits the OG tags.")

        if title and h1_list:
            h1_text = " ".join(h1_list)
            title_tokens = _tokens(title)
            h1_tokens = _tokens(h1_text)
            if title_tokens and h1_tokens:
                overlap = title_tokens & h1_tokens
                union = title_tokens | h1_tokens
                jaccard = len(overlap) / len(union) if union else 0.0
                if jaccard < 0.15:
                    result.add(url, "medium", "title_h1_mismatch",
                               f"Title and H1 share almost no words (overlap "
                               f"score {jaccard:.2f}). Title: {title!r} vs "
                               f"H1: {h1_text!r}. This can read as a "
                               "bait-and-switch to both users and ranking "
                               "systems if the page doesn't actually deliver "
                               "on the title's promise -- verify the mismatch "
                               "is not just cosmetic before rewriting.",
                               current_value=title)
        elif title and not h1_list:
            result.add(url, "low", "missing_h1",
                       "Page has a <title> but no <h1> at all -- not strictly "
                       "a metadata bug, but worth flagging since it blocks "
                       "the title/H1 relevance check and is itself a "
                       "content-structure signal.")

    for value, urls in titles_by_value.items():
        if len(urls) > 1:
            result.add(urls[0], "high", "duplicate_title",
                       f"Title {value!r} is shared by {len(urls)} distinct pages: "
                       f"{', '.join(urls)}. Each indexable page needs a distinct "
                       "title describing its own content.",
                       current_value=value,
                       affected_urls=list(urls))

    for value, urls in descriptions_by_value.items():
        if len(urls) > 1:
            result.add(urls[0], "medium", "duplicate_meta_description",
                       f"Meta description is shared by {len(urls)} distinct pages: "
                       f"{', '.join(urls)}. Each page should describe its own "
                       "specific content.",
                       current_value=value,
                       affected_urls=list(urls))

    return result


_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def to_json(result: AuditResult) -> dict[str, Any]:
    by_url: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for issue in result.issues:
        entry: dict[str, Any] = {
            "severity": issue.severity,
            "problem": issue.problem,
            "detail": issue.detail,
            "current_value": issue.current_value,
        }
        if issue.affected_urls is not None:
            entry["affected_urls"] = issue.affected_urls
        by_url[issue.url].append(entry)

    pages_out = []
    for url, issues in by_url.items():
        issues.sort(key=lambda i: _SEVERITY_ORDER.get(i["severity"], 9))
        best_severity = issues[0]["severity"]
        pages_out.append({
            "url": url,
            "severity": best_severity,
            "issue_count": len(issues),
            "issues": issues,
        })
    pages_out.sort(key=lambda p: (_SEVERITY_ORDER.get(p["severity"], 9), -p["issue_count"]))

    counts: dict[str, int] = defaultdict(int)
    for issue in result.issues:
        counts[issue.problem] += 1

    return {
        "site_url": result.site_url,
        "snapshot_path": result.snapshot_path,
        "pages_analyzed": result.pages_analyzed,
        "pages_with_issues": len(pages_out),
        "total_issues": len(result.issues),
        "issue_counts_by_type": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "pages": pages_out,
    }


def main() -> None:
    import argparse
    import time

    parser = argparse.ArgumentParser(
        description="Audit page titles, meta descriptions, and OG/Twitter Card "
                    "tags from the shared crawl-snapshot store; reuses a "
                    "snapshot under 24h old, else crawls fresh."
    )
    parser.add_argument("--max-pages", type=int, default=500,
                        help="cap for a fresh crawl (default 500)")
    parser.add_argument("--force-recrawl", action="store_true",
                        help="ignore any reusable snapshot and crawl fresh")
    args = parser.parse_args()

    cfg = config_module.load()

    snap = None
    if not args.force_recrawl:
        snap = snapshots.latest(cfg, max_age_hours=SNAPSHOT_MAX_AGE_HOURS)
    freshly_crawled = snap is None
    if snap is None:
        snap = snapshots.new_crawl(cfg, "seo-metadata", max_pages=args.max_pages)

    records = list(snap.pages())
    result = audit(records, cfg.site_url, str(snap.path))
    output = to_json(result)
    output["freshly_crawled"] = freshly_crawled

    crawl_summary = snap.meta.get("crawl_summary") or {}
    output["crawl"] = {
        "producer_skill": snap.meta.get("producer_skill"),
        "finished_at": snap.meta.get("finished_at"),
        "pages_crawled": snap.pages_crawled,
        "truncated": snap.truncated,
        "robots_status": crawl_summary.get("robots_status"),
        "all_blocked": bool(crawl_summary.get("all_blocked")),
    }
    if result.pages_analyzed == 0:
        if output["crawl"]["all_blocked"]:
            output["empty_reason"] = (
                "The crawl produced no usable pages because robots.txt blocked "
                f"it (robots_status={output['crawl']['robots_status']!r}). "
                "Nothing was audited — this is a crawl-access problem, not a "
                "clean metadata bill of health."
            )
        else:
            output["empty_reason"] = (
                "The snapshot contains no indexable HTML pages (status 200, "
                "text/html, not noindex). Check the crawl summary above — an "
                "empty audit is not the same as a clean audit."
            )

    output["note"] = (
        "This script only reports. Fixes must be made in the source template "
        "(Next.js metadata export / generateMetadata, Astro frontmatter, Hugo "
        "front matter, Nuxt useHead, or the HTML <head> partial) that generates "
        "each flagged URL -- never in built/rendered output. See SKILL.md."
    )

    report_path = cfg.reports_dir / f"metadata-audit-{time.strftime('%Y-%m-%d')}.json"
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False),
                           encoding="utf-8")
    output["report_file"] = str(report_path)

    snapshots.prune(cfg)

    json.dump(output, sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
