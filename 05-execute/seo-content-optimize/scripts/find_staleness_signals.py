"""Find pages that are genuinely stale, not just old.

Per references/seo-playbook.md §7: "only flag a page as 'needs refresh' when
there is a real, identifiable staleness signal (outdated facts, superseded
data, broken references), never on a pure time-since-last-edit basis." This
script operationalizes that rule instead of leaving it as a slogan:

  1. It ALWAYS takes a fresh crawl through the shared snapshot store
     (scripts.lib.snapshots.new_crawl) and compares each page's
     `content_hash` against an honest baseline chosen by
     `snapshots.find_baseline`: a prior snapshot of the same site, same
     max_pages, neither side truncated, and at least --min-days-old days
     older. Pages are matched between the two crawls by
     urlnorm.canonical_key of the final destination URL, so a slash/www
     alias never breaks the diff. If no honest baseline exists, the report
     says `checked: false` with the exact refusal reason — this script
     never diffs a crawl against itself or against an incomparable snapshot.
  2. For pages whose content hash is unchanged across that window, it
     fetches the page's current live text (a fresh, cheap HTTP GET -- no
     rendering, no paid API) and regex-scans it for concrete time-bound
     language: a hardcoded year, "last year"/"this year"/"next year", an
     explicit version reference, or a copyright year -- i.e. content that
     *asserts* a point in time and may now be wrong, not just content that
     happens to be old.

A page only becomes a "staleness candidate" if BOTH conditions hold: the
content hash is unchanged since the baseline (nothing was touched) AND the
live text contains at least one time-bound expression. Age alone, or
time-bound language alone (e.g. a page correctly discussing "the 2019 launch
of X" as settled history), is deliberately NOT enough to flag a page -- see
references/red-flags.md §3 ("do not freshness-fake") and geo-playbook.md §7
(freshness effect is real but modest and platform-dependent, not a "13-week
rule").

Template boilerplate is filtered site-level: a match string appearing on
more than half of the scanned pages (and at least 5 of them) is a template
artifact (e.g. "© 2024" in the footer), reported ONCE as a
`template_boilerplate` finding ("fix the template once") and EXCLUDED from
every per-page candidate.

This script never edits content and never touches timestamps, and its
output never recommends a timestamp-only update. It only surfaces
candidates + the specific matched staleness language for a human/agent to
read and judge. See SKILL.md for how to act on the output.

Usage:
    python3 find_staleness_signals.py
    python3 find_staleness_signals.py --max-pages 300 --min-days-old 90
    python3 find_staleness_signals.py --fetch-limit 40
"""

import sys
from pathlib import Path

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

import json
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup

from scripts.lib import http_util, linkgraph, pagerules, snapshots, urlnorm

SECONDS_PER_DAY = 86400
BOILERPLATE_MIN_PAGES = 5
BOILERPLATE_MIN_FRACTION = 0.5

YEAR_RE = re.compile(r"\b(20[0-9]{2})\b")

RELATIVE_TIME_RE = re.compile(
    r"\b(last year|this year|next year|earlier this year|as of \d{4}|"
    r"currently in \d{4}|in \d{4} so far)\b",
    re.IGNORECASE,
)

VERSION_RE = re.compile(
    r"(?i:\b(?:version|ver\.?|v)\s?\d+(?:\.\d+){1,3}\b)"
    r"|\b[A-Z][A-Za-z0-9+#.]{1,20}\s+\d+\.\d+(?:\.\d+)?\b"
)

COPYRIGHT_RE = re.compile(r"(?:©|\(c\)|copyright)\s*(20[0-9]{2})", re.IGNORECASE)

PRICE_RATING_MARKERS = (
    "$", "€", "£", "rated", "stars", "out of", "price", "per month",
)
PRICE_RATING_WINDOW = 20

_CURRENT_YEAR = datetime.now(timezone.utc).year


def _extract_visible_text(html: str) -> str:
    """Same cleaning approach as crawler.py's own text extraction, so the
    text this script scans matches what content_hash was computed from."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def _reject_price_rating_context(text: str, match: "re.Match") -> bool:
    """True when a version-shaped match sits in price/rating context
    ("rated 4.8 stars", "$49.99 per month") and must not be treated as a
    version reference."""
    start = max(0, match.start() - PRICE_RATING_WINDOW)
    end = min(len(text), match.end() + PRICE_RATING_WINDOW)
    window = text[start:end].lower()
    return any(marker in window for marker in PRICE_RATING_MARKERS)


def _find_staleness_language(text: str) -> list[dict[str, Any]]:
    """Regex-scan visible text for concrete time-bound expressions. Returns a
    list of {"kind", "match", "context"} -- never a verdict on its own; a
    human/agent still has to read `context` to decide if the reference is
    actually outdated (e.g. "founded in 2016" is a fact that doesn't go stale;
    "the latest version, 2.3, was released this year" does)."""
    findings: list[dict[str, Any]] = []

    def _context(match: "re.Match") -> str:
        start = max(0, match.start() - 60)
        end = min(len(text), match.end() + 60)
        return text[start:end].strip()

    for match in YEAR_RE.finditer(text):
        year = int(match.group(1))
        if year < _CURRENT_YEAR:
            findings.append({
                "kind": "hardcoded_year",
                "match": match.group(0),
                "context": _context(match),
            })

    for match in RELATIVE_TIME_RE.finditer(text):
        findings.append({
            "kind": "relative_time_phrase",
            "match": match.group(0),
            "context": _context(match),
        })

    for match in COPYRIGHT_RE.finditer(text):
        year = int(match.group(1))
        if year < _CURRENT_YEAR:
            findings.append({
                "kind": "copyright_year",
                "match": match.group(0),
                "context": _context(match),
            })

    for match in VERSION_RE.finditer(text):
        if _reject_price_rating_context(text, match):
            continue
        findings.append({
            "kind": "version_reference",
            "match": match.group(0),
            "context": _context(match),
        })

    return findings


def _normalized_match(finding: dict[str, Any]) -> str:
    """Site-level identity of a matched string, for the boilerplate
    frequency filter: kind + whitespace-collapsed, lowercased match text."""
    text = re.sub(r"\s+", " ", str(finding.get("match", ""))).strip().lower()
    return f"{finding.get('kind', '')}:{text}"


def _page_identity(rec: dict[str, Any]) -> str:
    return urlnorm.canonical_key(rec.get("final_url") or rec.get("url", ""))


def _emit(output: dict[str, Any], cfg: config_module.Config) -> None:
    """Write the dated report file, prune stored state, print to stdout."""
    report_path = cfg.reports_dir / f"content-staleness-{time.strftime('%Y-%m-%d')}.json"
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False),
                           encoding="utf-8")
    output["report_file"] = str(report_path)

    snapshots.prune(cfg)

    json.dump(output, sys.stdout, indent=2, ensure_ascii=False)
    print()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Find pages whose content is unchanged since an honest "
                    "baseline snapshot AND contains real time-bound language -- "
                    "a genuine staleness signal, never a time-since-edit proxy."
    )
    parser.add_argument("--max-pages", type=int, default=500,
                        help="page cap for the fresh crawl this script always takes "
                            "(default 500); the baseline must have used the same cap "
                            "to be comparable")
    parser.add_argument("--min-days-old", type=int, default=30,
                        help="minimum age (days) of the baseline snapshot before a page "
                            "is even eligible to be checked (default 30) -- avoids flagging "
                            "'unchanged' on a page that simply hasn't had time to change yet")
    parser.add_argument("--fetch-limit", type=int, default=60,
                        help="max number of unchanged-content pages to live-fetch and "
                            "regex-scan for staleness language in one run (default 60) -- "
                            "keeps this script polite and bounded on large sites")
    args = parser.parse_args()

    cfg = config_module.load()
    site_url = cfg.site_url

    current = snapshots.new_crawl(cfg, "seo-content-optimize", max_pages=args.max_pages)
    crawl_summary = current.meta.get("crawl_summary") or {}

    output_base: dict[str, Any] = {
        "site_url": site_url,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_path": str(current.path),
        "crawl_summary": crawl_summary,
    }

    if bool(crawl_summary.get("all_blocked")) or current.pages_crawled == 0:
        output = dict(output_base)
        output.update({
            "pages_analyzed": 0,
            "checked": False,
            "reason": (
                "The fresh crawl produced no pages"
                + (f" — robots.txt blocked it (robots_status="
                   f"{crawl_summary.get('robots_status')!r})"
                   if crawl_summary.get("all_blocked") else "")
                + ". Nothing was checked; this is a crawl-access problem, "
                "not an absence of stale content."
            ),
            "not_checked": {"content_hash_diff": "crawl produced no pages"},
            "candidates": [],
            "template_boilerplate": [],
        })
        _emit(output, cfg)
        return

    baseline_result = snapshots.find_baseline(cfg, current, min_age_days=args.min_days_old)
    if baseline_result.snapshot is None:
        output = dict(output_base)
        output.update({
            "pages_analyzed": current.pages_crawled,
            "checked": False,
            "reason": (
                f"{baseline_result.refusal_reason} — per seo-playbook.md §7, "
                "this script refuses to guess staleness without an honest "
                "baseline. This run's crawl is stored in the snapshot store "
                "and will serve as a future baseline; re-run after "
                f"--min-days-old ({args.min_days_old}) days."
            ),
            "not_checked": {"content_hash_diff": baseline_result.refusal_reason},
            "candidates": [],
            "template_boilerplate": [],
        })
        _emit(output, cfg)
        return

    baseline = baseline_result.snapshot
    previous_age_days = (
        (datetime.now(timezone.utc) - baseline.finished_at).total_seconds()
        / SECONDS_PER_DAY
    )

    pages = list(current.pages())

    current_by_key: dict[str, dict[str, Any]] = {}
    for rec in pages:
        if not pagerules.is_indexable_html(rec):
            continue
        key = _page_identity(rec)
        if key and key not in current_by_key:
            current_by_key[key] = rec

    baseline_hash_by_key: dict[str, str] = {}
    for rec in baseline.pages():
        key = _page_identity(rec)
        content_hash = rec.get("content_hash")
        if key and content_hash and key not in baseline_hash_by_key:
            baseline_hash_by_key[key] = content_hash

    unchanged_keys: list[str] = []
    for key, rec in current_by_key.items():
        cur_hash = rec.get("content_hash")
        if cur_hash and baseline_hash_by_key.get(key) == cur_hash:
            unchanged_keys.append(key)

    graph = linkgraph.build_graph(pages)
    unchanged_keys.sort(key=lambda k: -graph.inbound.get(k, 0))
    to_fetch = unchanged_keys[: args.fetch_limit]
    skipped_due_to_limit = unchanged_keys[args.fetch_limit:]

    page_matches: dict[str, list[dict[str, Any]]] = {}
    pages_scanned: list[str] = []
    fetch_errors: list[dict[str, str]] = []

    for key in to_fetch:
        rec = current_by_key[key]
        url = rec.get("final_url") or rec.get("url", "")
        try:
            resp = http_util.get(url, min_interval=1.0)
        except http_util.HttpError as exc:
            fetch_errors.append({"url": url, "error": str(exc)})
            continue
        if resp.status_code != 200 or "text/html" not in resp.headers.get("Content-Type", ""):
            continue
        text = _extract_visible_text(resp.text)
        pages_scanned.append(key)
        matches = _find_staleness_language(text)
        if matches:
            page_matches[key] = matches

    match_pages: dict[str, set] = defaultdict(set)
    match_example: dict[str, dict[str, Any]] = {}
    for key, matches in page_matches.items():
        for finding in matches:
            norm = _normalized_match(finding)
            match_pages[norm].add(key)
            match_example.setdefault(norm, finding)

    scanned_count = len(pages_scanned)
    boilerplate_norms = {
        norm for norm, keys in match_pages.items()
        if len(keys) >= BOILERPLATE_MIN_PAGES
        and len(keys) > BOILERPLATE_MIN_FRACTION * scanned_count
    }

    template_boilerplate: list[dict[str, Any]] = []
    for norm in sorted(boilerplate_norms, key=lambda n: -len(match_pages[n])):
        example = match_example[norm]
        n_pages = len(match_pages[norm])
        percent = round(100.0 * n_pages / scanned_count) if scanned_count else 0
        template_boilerplate.append({
            "type": "template_boilerplate",
            "severity": "low",
            "kind": example["kind"],
            "match": example["match"],
            "example_context": example.get("context", ""),
            "pages_matched": n_pages,
            "pages_scanned": scanned_count,
            "percent_of_scanned": percent,
            "detail": (
                f"{example['match']!r} appears on {percent}% of the scanned "
                f"pages ({n_pages}/{scanned_count}) — this is template "
                "boilerplate (typically a footer/header), not per-page stale "
                "content. Fix the template once; it is excluded from every "
                "per-page staleness candidate below."
            ),
            "auto_fixable": example["kind"] == "copyright_year",
        })

    candidates: list[dict[str, Any]] = []
    for key, matches in page_matches.items():
        kept = [m for m in matches if _normalized_match(m) not in boilerplate_norms]
        if not kept:
            continue
        rec = current_by_key[key]
        url = rec.get("final_url") or rec.get("url", "")
        candidates.append({
            "url": url,
            "inbound_internal_link_count": graph.inbound.get(key, 0),
            "unchanged_since": baseline.path.name,
            "unchanged_for_days": round(previous_age_days, 1),
            "staleness_signals_found": len(kept),
            "staleness_signals": kept[:15],
            "detail": (
                f"Content hash unchanged for at least {round(previous_age_days, 1)} "
                f"day(s) AND live text contains {len(kept)} time-bound "
                "expression(s) that may now be outdated. This is a candidate for "
                "human/agent review, not a confirmed problem -- some matches "
                "(e.g. a founding year cited as settled history) are not actually "
                "stale. Read `staleness_signals[].context` before concluding "
                "anything needs to change."
            ),
        })

    candidates.sort(key=lambda c: -c["staleness_signals_found"])

    output = dict(output_base)
    output.update({
        "pages_analyzed": len(current_by_key),
        "checked": True,
        "previous_snapshot": str(baseline.path),
        "previous_snapshot_age_days": round(previous_age_days, 1),
        "pages_with_unchanged_content_hash": len(unchanged_keys),
        "pages_live_fetched_for_language_scan": len(to_fetch),
        "pages_scanned": scanned_count,
        "pages_skipped_due_to_fetch_limit": len(skipped_due_to_limit),
        "fetch_errors": fetch_errors,
        "template_boilerplate": template_boilerplate,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "methodology_note": (
            "A page only appears here if BOTH: (1) its content_hash is "
            "identical to the same page's content_hash in the baseline "
            "snapshot (matched by canonical URL identity — truly untouched, "
            "not just old), AND (2) its current live text contains at least "
            "one hardcoded year older than the current year, a relative time "
            "phrase ('last year', 'this year', etc.), a copyright year, or an "
            "explicit version reference (a bare decimal or a price/rating is "
            "rejected). Match strings shared by most scanned pages are "
            "reported once as template_boilerplate and excluded per-page. Age "
            "alone and time-bound language alone are each independently "
            "insufficient -- see references/seo-playbook.md §7 and "
            "references/red-flags.md §3 ('do not freshness-fake'). This "
            "script never reads or trusts a CMS updated_at/published_at field."
        ),
        "note": (
            "This script only detects and reports candidates. It never edits "
            "content, never touches a timestamp, and none of its findings "
            "should ever be 'fixed' by a timestamp-only update. See SKILL.md "
            "for how to turn a candidate into an actual, substantive content "
            "improvement -- which is agent judgment work, not something this "
            "script automates."
        ),
    })

    _emit(output, cfg)


if __name__ == "__main__":
    main()
