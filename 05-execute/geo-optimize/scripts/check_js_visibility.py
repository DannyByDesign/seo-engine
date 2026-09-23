"""geo-optimize: JS-visibility check -- what AI crawlers actually see.

No major AI crawler executes JavaScript (references/geo-playbook.md §11):
GPTBot, ClaudeBot, PerplexityBot, OAI-SearchBot and their citation-relevant
siblings read the RAW HTML response and nothing else. A site that renders its
substantive content client-side (Next.js/Nuxt/SvelteKit/Angular/React SPA
shells) is effectively invisible to AI search even where Googlebot -- which
does render -- sees it fine. This is the single most common structural GEO
blocker, and checking for it is free.

Core check (no API key required):
  Fetch the raw, unrendered HTML per URL and flag pages where the extracted
  body text is thin (< --min-words, default 100) AND the raw HTML carries a
  JS-framework hydration marker (`__NEXT_DATA__`, `__NUXT__`, an
  `id="root"`/`id="app"` shell with trivial inner text, `data-reactroot`,
  `ng-version`, `data-sveltekit`, `astro-island`). Both conditions together
  say "there is an app here, and its content is not in the HTML". Severity:
  high under 30 words (an empty shell), else medium.

Optional upgrade (FIRECRAWL_API_KEY):
  Flagged URLs are re-checked with a true raw-vs-rendered diff via
  scripts.lib.firecrawl.diff_raw_vs_rendered, reporting the rendered word
  count and gap_ratio. A confirmed gap upgrades confidence; a rendered page
  that is ALSO thin means the page is thin for everyone (not a JS-rendering
  problem) and the finding is downgraded rather than left overstated.

The fix is to server-side render or prerender the content -- the SAME
content for everyone. Never "fix" this by serving special HTML only to
crawler user-agents: crawler-specific serving is cloaking (red-flags.md §1).

Usage:
    python3 check_js_visibility.py --urls https://example.com/ https://example.com/docs
    python3 check_js_visibility.py --sample-from-crawl --sample-size 8
    python3 check_js_visibility.py --from-snapshot --min-words 100
"""

from __future__ import annotations

import json
import re
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
from scripts.lib import firecrawl, http_util, pagerules, snapshots
from scripts.lib.config import MissingConfigError

from bs4 import BeautifulSoup

DEFAULT_MIN_WORDS = 100
HIGH_SEVERITY_WORDS = 30

STRING_MARKERS = (
    "__NEXT_DATA__",
    "__NUXT__",
    "data-reactroot",
    "ng-version",
    "data-sveltekit",
    "astro-island",
)

REMEDIATION = (
    "Server-side render or prerender the content so the substantive text is "
    "present in the raw HTML -- and serve that same content to everyone. Do "
    "NOT special-case responses for crawler user-agents: crawler-specific "
    "serving is cloaking (red-flags.md §1)."
)

GEO_PLAYBOOK_REF = "geo-playbook.md §11 (AI crawlers don't render JavaScript)"


def _extract_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def detect_markers(html: str) -> list[str]:
    """JS-framework hydration markers present in raw HTML. String markers are
    substring checks; the root/app shell check requires the mount node's own
    inner text to be trivial (a populated SSR'd `id=\"root\"` is fine)."""
    found = [m for m in STRING_MARKERS if m in html]

    soup = BeautifulSoup(html, "lxml")
    for el_id in ("root", "app"):
        el = soup.find(id=el_id)
        if el is not None and len(el.get_text(" ", strip=True).split()) < 10:
            found.append(f'id="{el_id}" mount node with trivial inner text')
    return found


def analyze_html(url: str, html: str) -> dict:
    markers = detect_markers(html)
    word_count = len(_extract_text(BeautifulSoup(html, "lxml")).split())
    return {"url": url, "word_count_raw": word_count, "markers_found": markers}


def check_url_live(url: str) -> dict:
    """Fetch the raw (unrendered) HTML for one URL and analyze it."""
    try:
        resp = http_util.get(url, min_interval=0.5)
    except http_util.HttpError as exc:
        return {"url": url, "error": str(exc), "flagged": False}
    if resp.status_code != 200:
        return {"url": url, "status": resp.status_code, "flagged": False,
                "note": f"HTTP {resp.status_code} -- not analyzed"}
    if "text/html" not in resp.headers.get("Content-Type", "").lower():
        return {"url": url, "status": 200, "flagged": False,
                "note": "not an HTML response -- not analyzed"}
    return analyze_html(url, resp.text or "")


def flag(result: dict, min_words: int) -> dict:
    """Apply the flagging heuristic to an analyzed result (in place)."""
    if "word_count_raw" not in result:
        return result
    flagged = (result["word_count_raw"] < min_words
               and bool(result["markers_found"]))
    result["flagged"] = flagged
    if flagged:
        result["severity"] = ("high" if result["word_count_raw"] < HIGH_SEVERITY_WORDS
                              else "medium")
    return result


def build_finding(result: dict) -> dict:
    words = result["word_count_raw"]
    markers = result["markers_found"]
    return {
        "type": "js_dependent_content",
        "severity": result["severity"],
        "url": result["url"],
        "word_count_raw": words,
        "markers_found": markers,
        "confidence": "heuristic",
        "detail": (
            f"The raw (unrendered) HTML of {result['url']} extracts only {words} "
            f"words of body text while carrying JS-framework hydration markers "
            f"({', '.join(markers)}). No major AI crawler executes JavaScript "
            f"({GEO_PLAYBOOK_REF}), so content that only appears after client-side "
            "rendering is invisible to ChatGPT/Claude/Perplexity citation crawlers "
            "-- even where Googlebot, which does render, sees the full page."
        ),
        "geo_playbook_ref": GEO_PLAYBOOK_REF,
        "red_flags_ref": "red-flags.md §1 (Cloaking -- constrains the fix, see remediation)",
        "remediation": REMEDIATION,
        "auto_fixable": False,
        "human_review_reason": (
            "Rendering architecture changes (SSR/prerendering) are a build-"
            "pipeline decision -- this script identifies the gap, a human "
            "picks the rendering strategy."
        ),
    }


def upgrade_with_firecrawl(cfg, findings: list[dict], results_by_url: dict) -> None:
    """True raw-vs-rendered diff for flagged URLs. Confirms or honestly
    downgrades each heuristic finding; never crashes the core check."""
    for finding in findings:
        url = finding["url"]
        try:
            diff = firecrawl.diff_raw_vs_rendered(cfg, url)
        except Exception as exc:
            err = http_util.sanitize_text(str(exc))
            finding["rendered_diff_error"] = err
            results_by_url[url]["rendered_diff_error"] = err
            continue
        rendered = {
            "raw_word_count": diff["raw_word_count"],
            "rendered_word_count": diff["rendered_word_count"],
            "gap_ratio": round(diff["gap_ratio"], 3),
            "likely_js_dependent": diff["likely_js_dependent"],
        }
        finding["rendered_diff"] = rendered
        finding["gap_ratio"] = rendered["gap_ratio"]
        results_by_url[url]["rendered_diff"] = rendered
        if diff["likely_js_dependent"]:
            finding["confidence"] = "confirmed"
            finding["detail"] += (
                f" CONFIRMED by rendered diff: rendering grows the page from "
                f"{diff['raw_word_count']} to {diff['rendered_word_count']} words "
                f"(gap_ratio {rendered['gap_ratio']})."
            )
        else:
            finding["confidence"] = "unlikely"
            finding["severity"] = "low"
            results_by_url[url]["severity"] = "low"
            finding["detail"] += (
                f" DOWNGRADED by rendered diff: the rendered page has only "
                f"{diff['rendered_word_count']} words (gap_ratio "
                f"{rendered['gap_ratio']}) -- the page is thin for everyone, "
                "which is a content problem, not a JS-rendering visibility gap."
            )


def main() -> None:
    import argparse
    import time

    parser = argparse.ArgumentParser(
        description=(
            "Free check for JS-rendered content invisible to AI crawlers "
            f"({GEO_PLAYBOOK_REF}). No API key required; FIRECRAWL_API_KEY "
            "optionally upgrades flags to a true raw-vs-rendered diff."
        )
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--urls", nargs="+", help="explicit list of URLs to check")
    group.add_argument("--sample-from-crawl", action="store_true",
                       help="sample pages from the latest crawl snapshot "
                            "(crawls fresh if none is recent) and fetch each raw")
    group.add_argument("--from-snapshot", action="store_true",
                       help="screen ALL pages of the latest snapshot by their stored "
                            "raw word_count; fetch only the thin ones for marker analysis")
    parser.add_argument("--max-pages", type=int, default=20,
                        help="crawl cap when a fresh crawl is needed (default 20)")
    parser.add_argument("--sample-size", type=int, default=8,
                        help="pages to check with --sample-from-crawl (default 8)")
    parser.add_argument("--min-words", type=int, default=DEFAULT_MIN_WORDS,
                        help=f"raw-HTML word count below which a page with hydration "
                             f"markers is flagged (default {DEFAULT_MIN_WORDS})")
    args = parser.parse_args()

    cfg = config_module.load()
    snapshots.prune(cfg)

    snapshot_info = None
    results: list[dict] = []

    if args.urls:
        results = [flag(check_url_live(url), args.min_words) for url in args.urls]
    else:
        try:
            site_url = cfg.site_url
        except MissingConfigError as exc:
            report = {
                "urls_checked": [],
                "error": (
                    f"No site URL configured: {exc}. Pass --urls <url> [<url> ...] "
                    "explicitly, or run the seo-setup skill to write "
                    ".seo-engine/config.yml, or export SEO_SITE_URL."
                ),
            }
            json.dump(report, sys.stdout, indent=2)
            print()
            sys.exit(1)

        snap = snapshots.latest(cfg, max_age_hours=24)
        reused = snap is not None
        if snap is None:
            snap = snapshots.new_crawl(cfg, "geo-optimize", max_pages=args.max_pages)
        snapshot_info = {
            "path": snap.path.name,
            "producer_skill": snap.meta.get("producer_skill", ""),
            "reused": reused,
            "pages_crawled": snap.pages_crawled,
        }

        if args.from_snapshot:
            for record in snap.pages():
                if not pagerules.is_indexable_html(record):
                    continue
                url = record.get("final_url") or record.get("url") or ""
                stored = int(record.get("word_count") or 0)
                if stored >= args.min_words:
                    results.append({"url": url, "word_count_raw": stored,
                                    "markers_found": [], "flagged": False,
                                    "source": "snapshot"})
                else:
                    result = flag(check_url_live(url), args.min_words)
                    result["source"] = "snapshot+live_fetch"
                    results.append(result)
        else:
            urls = []
            for record in snap.pages():
                if pagerules.is_indexable_html(record):
                    urls.append(record.get("final_url") or record.get("url"))
                if len(urls) >= args.sample_size:
                    break
            if not urls:
                summary = snap.meta.get("crawl_summary", {})
                snapshot_info["empty_crawl_reason"] = {
                    "robots_status": summary.get("robots_status", ""),
                    "all_blocked": summary.get("all_blocked", False),
                }
                urls = [site_url]
            results = [flag(check_url_live(url), args.min_words) for url in urls]

    findings = [build_finding(r) for r in results if r.get("flagged")]
    results_by_url = {r["url"]: r for r in results}

    firecrawl_configured = cfg.integration_available("firecrawl")
    if findings:
        if firecrawl_configured:
            upgrade_with_firecrawl(cfg, findings, results_by_url)
        else:
            for finding in findings:
                finding["rendered_diff"] = {
                    "checked": False,
                    "reason": (
                        "FIRECRAWL_API_KEY not set -- raw-vs-rendered confirmation "
                        "unavailable; this flag stands on raw-HTML evidence alone "
                        "(thin extracted text + hydration markers)."
                    ),
                }

    findings.sort(key=lambda f: {"high": 0, "medium": 1, "low": 2}.get(f["severity"], 3))

    report = {
        "urls_checked": [r["url"] for r in results],
        "min_words": args.min_words,
        "results": results,
        "findings": findings,
        "severity_counts": {
            "high": sum(1 for f in findings if f["severity"] == "high"),
            "medium": sum(1 for f in findings if f["severity"] == "medium"),
            "low": sum(1 for f in findings if f["severity"] == "low"),
        },
        "firecrawl_configured": firecrawl_configured,
        "geo_playbook_ref": GEO_PLAYBOOK_REF,
        "remediation": REMEDIATION,
        "auto_fixable": False,
    }
    if snapshot_info:
        report["snapshot"] = snapshot_info

    stamp = time.strftime("%Y%m%d-%H%M%S")
    report_path = cfg.reports_dir / f"geo-js-visibility-{stamp}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    state_path = cfg.state_dir / "geo-js-visibility-last-run.json"
    state_path.write_text(json.dumps({
        "urls_checked_count": len(results),
        "severity_counts": report["severity_counts"],
        "report_path": str(report_path),
    }, indent=2), encoding="utf-8")

    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
