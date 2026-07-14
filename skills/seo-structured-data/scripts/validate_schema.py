"""Validate JSON-LD structured data across a site: live check or local HTML files.

Wraps scripts.lib.schema_validate.validate_html (offline, no external API calls
— see references/api-reference.md "Structured data validation" for why no
public Rich Results Test API exists and this is the CI-safe floor instead).

Severity model (mirrors scripts.lib.schema_validate):
  error    Broken/ineligible markup: malformed JSON-LD, a node with no @type,
           or a Google-REQUIRED property missing/empty. Exit-blocking (exit 2).
  warning  A Google-RECOMMENDED property missing/empty — valid markup with
           reduced rich-result eligibility. Exit-blocking only with --strict.
  info     Advisory only: types whose rich-result visual treatment Google
           retired (FAQPage/HowTo) — valid markup, no visual yield expected.

Two additional things reported per page:
  1. Per-page issue lists carry severity; the summary carries total
     error/warning/info counts.
  2. NO-SCHEMA-BUT-LIKELY-FIT: pages with ZERO JSON-LD nodes where the URL
     pattern or H1/title suggests an obvious content-type match. This is a
     suggestion, never an issue of any severity, and it only fires when
     node_count == 0. The homepage→Organization hint fires only for the site
     root URL (live mode) or the index.html at the scan root (--files-dir
     mode) — never for pretty-URL index.html files at depth.

Live mode discovers URLs from the shared crawl-snapshot store
(scripts.lib.snapshots.latest(), else a fresh new_crawl) — snapshots don't
store page HTML, so each page is re-fetched politely (min 1s/request,
matching the crawler's politeness floor; robots.txt crawl-delay can raise it)
and robots.txt is honored via scripts.lib.robots.

Usage:
    # Live check (uses cfg.site_url from .seo-engine/config.yml, or pass --url)
    python3 validate_schema.py --live --max-pages 100

    # Live check of one specific URL
    python3 validate_schema.py --live --url https://example.com/blog/my-post

    # Local HTML files (e.g. a pre-deploy CI check against a build output dir)
    python3 validate_schema.py --files dist/index.html dist/blog/post.html
    python3 validate_schema.py --files-dir ./dist --pattern "*.html"

    # Promote warnings (missing recommended properties) to exit-blocking
    python3 validate_schema.py --files-dir ./dist --strict

Exit codes: 0 = no errors (warnings/info are OK unless --strict), 2 = errors
present (or warnings present with --strict), 1 = setup/usage problem.

Output: structured JSON on stdout, plus a dated report written to
.seo-engine/reports/ and a running baseline written to
.seo-engine/state/schema-validation.json so successive runs can diff against
the last one (used by seo-maintain's regression pass).
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
from scripts.lib import config as config_module  # noqa: E402

import argparse  # noqa: E402
import fnmatch  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Any, Optional  # noqa: E402
from urllib.parse import urlparse  # noqa: E402

from scripts.lib import http_util  # noqa: E402
from scripts.lib import pagerules  # noqa: E402
from scripts.lib import robots  # noqa: E402
from scripts.lib import schema_validate  # noqa: E402
from scripts.lib import snapshots  # noqa: E402
from scripts.lib import urlnorm  # noqa: E402

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None


_EXTRUCT_REMEDIATION = (
    "The 'extruct' package is required for JSON-LD extraction but is not "
    "installed. Run: python3 -m pip install -r requirements.txt (from the "
    "seo-engine root), then re-run this script."
)

# URL-pattern / heading heuristics for "this page probably wants schema but has
# none." Deliberately conservative: only flags the clearest, lowest-false-
# -positive cases. Order matters — first match wins.
CONTENT_TYPE_HINTS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"/blog/|/posts?/|/news/|/articles?/", re.I), "BlogPosting",
     "URL path suggests a blog/news/article page (BlogPosting, or Article/NewsArticle "
     "if it's editorial news rather than a blog)"),
    (re.compile(r"/product/|/products/|/shop/|/p/\d", re.I), "Product",
     "URL path suggests a product detail page"),
    (re.compile(r"/faq/?$|/faqs/?$|frequently-asked-questions", re.I), "FAQPage",
     "URL path suggests a dedicated FAQ page"),
    (re.compile(r"/recipes?/", re.I), "Recipe",
     "URL path suggests a recipe page"),
    (re.compile(r"/how-to-|/guide/|/tutorial/", re.I), "HowTo",
     "URL path suggests a how-to/tutorial page"),
    (re.compile(r"/locations?/|/stores?/|/branches?/", re.I), "LocalBusiness",
     "URL path suggests a physical-location/store page"),
    (re.compile(r"/team/|/authors?/|/people/|/staff/", re.I), "Person",
     "URL path suggests an individual bio/author page"),
]

H1_TITLE_HINTS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"\bhow to\b", re.I), "HowTo", "H1/title reads as a how-to"),
    (re.compile(r"\brecipe\b", re.I), "Recipe", "H1/title reads as a recipe"),
    (re.compile(r"\bfaqs?\b|frequently asked questions", re.I), "FAQPage",
     "H1/title reads as an FAQ page"),
]

HOMEPAGE_ORG_HINT = (
    "Organization",
    "homepage with no Organization/WebSite markup — nearly every site benefits "
    "from identifying itself as an entity on its own homepage",
)


def _infer_expected_type(
    url: str, title: str, h1_list: list[str], is_homepage: bool,
) -> Optional[tuple[str, str]]:
    """Returns (suggested_type, reason) or None if no confident inference.

    The homepage→Organization hint is caller-gated (is_homepage): live mode
    passes True only for the site root URL; --files-dir mode only for the
    index.html at the scan root. A pretty-URL /about/index.html at depth is
    NOT a homepage and must not trigger it."""
    path = urlparse(url).path
    for pattern, suggested_type, reason in CONTENT_TYPE_HINTS:
        if pattern.search(path):
            return suggested_type, reason

    heading_text = " ".join([title or "", *h1_list])
    for pattern, suggested_type, reason in H1_TITLE_HINTS:
        if pattern.search(heading_text):
            return suggested_type, reason

    if is_homepage:
        return HOMEPAGE_ORG_HINT

    return None


def _validation_to_dict(outcome: schema_validate.ValidationResult) -> dict[str, Any]:
    return {
        "url": outcome.url,
        "ok": outcome.ok,  # errors only — warnings/info never flip this
        "node_count": outcome.node_count,
        "types_found": outcome.types_found,
        "issue_counts": outcome.counts(),
        "issues": [
            {"type": i.node_type, "severity": i.severity, "message": i.message}
            for i in outcome.issues
        ],
    }


def _error_page_entry(url: str, message: str) -> dict[str, Any]:
    return {
        "url": url, "ok": False, "node_count": 0, "types_found": [],
        "issue_counts": {"error": 1, "warning": 0, "info": 0},
        "issues": [{"type": "unknown", "severity": "error", "message": message}],
    }


def _robots_skip_entry(url: str, policy: robots.RobotsPolicy) -> dict[str, Any]:
    if policy.disallow_all:
        reason = (
            "robots.txt could not be read ("
            + (policy.fetch_error or f"HTTP {policy.source_status}")
            + ") — treating as disallow-all (conservative), page not fetched"
        )
    else:
        reason = "disallowed by robots.txt for this tool's user agent — page not fetched"
    return {
        "url": url, "checked": False, "skipped_reason": reason,
        "node_count": 0, "types_found": [],
        "issue_counts": {"error": 0, "warning": 0, "info": 0}, "issues": [],
    }


def _check_page(
    url: str,
    html: str,
    title: str = "",
    h1_list: Optional[list[str]] = None,
    is_homepage: bool = False,
) -> dict[str, Any]:
    outcome = schema_validate.validate_html(html, url)
    page_result = _validation_to_dict(outcome)

    # missing_schema_suggestion fires ONLY on pages with zero JSON-LD nodes —
    # a page that already ships markup gets validation issues, never this.
    if outcome.node_count == 0:
        if not title or h1_list is None:
            if BeautifulSoup is not None:
                soup = BeautifulSoup(html, "lxml")
                if not title and soup.title and soup.title.string:
                    title = soup.title.string.strip()
                if h1_list is None:
                    h1_list = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
        inferred = _infer_expected_type(url, title, h1_list or [], is_homepage)
        if inferred:
            suggested_type, reason = inferred
            spec = schema_validate.GOOGLE_RICH_RESULTS.get(suggested_type, {})
            page_result["missing_schema_suggestion"] = {
                "suggested_type": suggested_type,
                "reason": reason,
                "required_properties": spec.get("required", []),
                "recommended_properties": spec.get("recommended", []),
            }
    return page_result


def _is_root_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.path in ("", "/") and not parsed.query


def validate_live(
    cfg, max_pages: int, single_url: Optional[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Returns (page_results, notes). URL discovery comes from the crawl-
    snapshot store; snapshots don't store HTML, so pages are re-fetched here —
    politely (>=1s between requests, the crawler's own floor) and honoring
    robots.txt."""
    results: list[dict[str, Any]] = []
    notes: list[str] = []

    if single_url:
        policy = robots.fetch(single_url)
        if not policy.allowed(http_util.USER_AGENT, single_url):
            results.append(_robots_skip_entry(single_url, policy))
            return results, notes
        try:
            resp = http_util.get(single_url, min_interval=1.0, check=True)
        except Exception as exc:  # noqa: BLE001 -- surfaced as a page-level error
            results.append(_error_page_entry(
                single_url,
                f"Fetch failed during validation pass: {http_util.sanitize_text(str(exc))}",
            ))
            return results, notes
        results.append(_check_page(single_url, resp.text,
                                   is_homepage=_is_root_url(single_url)))
        return results, notes

    site_url = cfg.site_url
    snap = snapshots.latest(cfg)
    if snap is None:
        snap = snapshots.new_crawl(cfg, "seo-structured-data", max_pages=max_pages)
        summary = snap.meta.get("crawl_summary") or {}
        if summary.get("all_blocked"):
            notes.append(
                "Fresh crawl produced no usable pages -- robots_status="
                f"{summary.get('robots_status', 'unknown')} (crawl blocked by/"
                "because of robots.txt). Nothing was validated; this is a "
                "coverage gap, not a clean bill of health."
            )
        else:
            notes.append(
                f"No reusable snapshot (<24h) found -- ran a fresh crawl "
                f"({snap.pages_crawled} pages, snapshot {snap.path.name})."
            )
    else:
        notes.append(
            f"URL discovery from crawl snapshot {snap.path.name} "
            f"(producer: {snap.meta.get('producer_skill', 'unknown')}, "
            f"{snap.pages_crawled} pages)."
        )

    policy = robots.fetch(site_url)
    fetch_interval = max(1.0, policy.crawl_delay(http_util.USER_AGENT) or 0.0)
    if policy.disallow_all:
        notes.append(
            "robots.txt could not be read ("
            + (policy.fetch_error or f"HTTP {policy.source_status}")
            + ") — conservatively skipping all live re-fetches."
        )

    count = 0
    for record in snap.pages():
        if count >= max_pages:
            break
        if record.get("status") != 200 or not pagerules.is_html(record):
            continue
        display_url = record.get("url") or record.get("final_url") or ""
        fetch_url = record.get("final_url") or display_url
        if not fetch_url:
            continue
        if not policy.allowed(http_util.USER_AGENT, fetch_url):
            results.append(_robots_skip_entry(display_url, policy))
            count += 1
            continue
        try:
            resp = http_util.get(fetch_url, min_interval=fetch_interval, check=True)
        except Exception as exc:  # noqa: BLE001 -- one bad page must not kill the run
            results.append(_error_page_entry(
                display_url,
                f"Fetch failed during validation pass: {http_util.sanitize_text(str(exc))}",
            ))
            count += 1
            continue
        results.append(_check_page(
            display_url, resp.text,
            record.get("title") or "", record.get("h1") or [],
            is_homepage=urlnorm.same_page(fetch_url, site_url),
        ))
        count += 1
    return results, notes


def validate_local_files(
    paths: list[Path], scan_root: Optional[Path] = None,
) -> list[dict[str, Any]]:
    # The homepage→Organization hint applies only to the index.html sitting at
    # the SCAN ROOT (--files-dir mode). Explicit --files lists have no known
    # root, so the hint never fires for them; nor for index.html at depth
    # (pretty-URL builds emit one per page).
    root_index: Optional[Path] = None
    if scan_root is not None:
        for name in ("index.html", "index.htm"):
            candidate = scan_root / name
            if candidate.is_file():
                root_index = candidate.resolve()
                break

    results: list[dict[str, Any]] = []
    for path in paths:
        try:
            html = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            results.append(_error_page_entry(str(path), f"Could not read file: {exc}"))
            continue
        # Use the file path as a pseudo-URL for reporting + heuristics.
        pseudo_url = "/" + str(path.as_posix()).lstrip("/")
        is_homepage = root_index is not None and path.resolve() == root_index
        results.append(_check_page(pseudo_url, html, is_homepage=is_homepage))
    return results


def _resolve_file_list(files: Optional[list[str]], files_dir: Optional[str], pattern: str) -> list[Path]:
    resolved: list[Path] = []
    if files:
        for f in files:
            p = Path(f)
            if p.is_file():
                resolved.append(p)
    if files_dir:
        base = Path(files_dir)
        resolved.extend(sorted(p for p in base.rglob("*") if p.is_file() and fnmatch.fnmatch(str(p), f"*{pattern.lstrip('*')}")))
    return resolved


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    checked = [r for r in results if r.get("checked", True)]
    issue_counts = {"error": 0, "warning": 0, "info": 0}
    for r in results:
        for sev, n in (r.get("issue_counts") or {}).items():
            issue_counts[sev] = issue_counts.get(sev, 0) + n
    pages_with_schema = sum(1 for r in checked if r.get("node_count", 0) > 0)
    pages_with_errors = sum(1 for r in checked if not r.get("ok", True))
    pages_with_warnings = sum(
        1 for r in checked if (r.get("issue_counts") or {}).get("warning", 0) > 0
    )
    pages_missing_suggested = sum(1 for r in checked if r.get("missing_schema_suggestion"))
    type_counts: dict[str, int] = {}
    for r in checked:
        for t in r.get("types_found", []):
            type_counts[t] = type_counts.get(t, 0) + 1
    return {
        "pages_checked": len(checked),
        "pages_skipped_robots": len(results) - len(checked),
        "pages_with_structured_data": pages_with_schema,
        "pages_with_validation_errors": pages_with_errors,
        "pages_with_warnings": pages_with_warnings,
        "issue_counts": issue_counts,
        "pages_missing_natural_fit_schema": pages_missing_suggested,
        "types_found_counts": type_counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate JSON-LD structured data (live check or local HTML files). "
                    "Exit 0 = no errors (warnings/info OK), 2 = errors present "
                    "(--strict also blocks on warnings)."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true", help="Check the live site (cfg.site_url or --url)")
    mode.add_argument("--files", nargs="+", help="Explicit local HTML file paths")
    mode.add_argument("--files-dir", help="Directory to scan for local HTML files")

    parser.add_argument("--url", help="With --live: validate exactly this one URL instead of the whole site")
    parser.add_argument("--max-pages", type=int, default=200, help="With --live site mode: page cap")
    parser.add_argument("--pattern", default="*.html", help="With --files-dir: glob suffix to match (default *.html)")
    parser.add_argument("--strict", action="store_true",
                        help="Promote warnings (missing Google-RECOMMENDED properties) to "
                             "exit-blocking: exit 2 on any error OR warning.")
    parser.add_argument("--no-report", action="store_true", help="Skip writing files under .seo-engine/")
    args = parser.parse_args()

    if schema_validate.extruct is None:
        print(json.dumps({
            "error": "Missing dependency: extruct.",
            "remediation": _EXTRUCT_REMEDIATION,
        }, indent=2))
        return 1

    cfg = config_module.load()

    notes: list[str] = []
    try:
        if args.live:
            if not args.url:
                try:
                    _ = cfg.site_url  # fail fast with a clean hint before any crawl
                except config_module.MissingConfigError as exc:
                    print(json.dumps({
                        "error": str(exc),
                        "hint": "Either pass --url https://example.com/some-page for a single-URL "
                                "check, or set site_url in .seo-engine/config.yml (run the seo-setup "
                                "skill first) / export SEO_SITE_URL for a full-site check.",
                    }, indent=2))
                    return 1
            results, notes = validate_live(cfg, args.max_pages, args.url)
            mode_label = "live"
        else:
            file_list = _resolve_file_list(args.files, args.files_dir, args.pattern)
            if not file_list:
                print(json.dumps({
                    "error": "No HTML files matched.",
                    "hint": "Check --files paths or --files-dir/--pattern.",
                }, indent=2))
                return 1
            scan_root = Path(args.files_dir) if args.files_dir else None
            results = validate_local_files(file_list, scan_root=scan_root)
            mode_label = "files"
    except RuntimeError as exc:
        # schema_validate raises RuntimeError when extruct is missing — the
        # upfront check should have caught it, but never leak a raw traceback.
        if "extruct" in str(exc):
            print(json.dumps({
                "error": "Missing dependency: extruct.",
                "remediation": _EXTRUCT_REMEDIATION,
            }, indent=2))
            return 1
        raise

    summary = summarize(results)
    output = {
        "mode": mode_label,
        "strict": args.strict,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes,
        "severity_note": (
            "error = broken/ineligible markup (missing Google-REQUIRED property, "
            "malformed JSON-LD, node without @type) — exit-blocking. warning = "
            "missing Google-RECOMMENDED property — valid markup, reduced "
            "eligibility, exit-blocking only with --strict. info = advisory "
            "(e.g. FAQPage/HowTo rich results retired by Google) — never blocking."
        ),
        "summary": summary,
        "pages": results,
    }

    if not args.no_report:
        # Retention housekeeping — every main() prunes; skipped only when the
        # user asked us not to touch .seo-engine at all.
        snapshots.prune(cfg)
        timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        report_path = cfg.reports_dir / f"schema-validation-{timestamp}.json"
        report_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
        output["report_written_to"] = str(report_path)

        state_path = cfg.state_dir / "schema-validation.json"
        state_path.write_text(json.dumps({
            "last_run_at": output["checked_at"],
            "mode": mode_label,
            "strict": args.strict,
            "summary": summary,
        }, indent=2), encoding="utf-8")
        output["state_written_to"] = str(state_path)

    json.dump(output, sys.stdout, indent=2)
    print()

    blocking = summary["issue_counts"]["error"]
    if args.strict:
        blocking += summary["issue_counts"]["warning"]
    return 0 if blocking == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
