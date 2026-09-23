"""Core Web Vitals audit: field data (CrUX, authoritative) + lab diagnostics (Lighthouse).

Wraps scripts.lib.psi.run_pagespeed / core_web_vitals across a set of "key pages"
(homepage + top pages discovered from the shared crawl-snapshot store via
scripts.lib.snapshots -- reusing snapshots.latest() when fresh, else running a
small new_crawl -- and/or GSC top-clicked pages) and reports each page's
LCP/INP/CLS against Google's published "good" thresholds (see
references/seo-playbook.md section 3):

    LCP < 2.5s   INP < 200ms   CLS < 0.1

Field data (loadingExperience in the PSI response, sourced from CrUX real-user
data) is the number that matters for ranking-relevant reporting. Lab data
(Lighthouse's synthetic run, under lighthouseResult) has no ranking weight of
its own -- it exists purely to explain *why* field data is bad, via the
"opportunities" and "diagnostics" audit groups. This script always reports
field data status first and treats lab detail as supporting diagnosis.

Per references/api-reference.md: a claim that Google plans to remove field
data from the PSI response could not be confirmed and should be treated as
unverified -- this script does not assume that will happen and always requests
field data as a matter of course.

Usage:
    python3 audit_cwv.py                        # auto-discovers key pages
    python3 audit_cwv.py --url https://x.com/a --url https://x.com/b
    python3 audit_cwv.py --strategy desktop --max-pages 15
    python3 audit_cwv.py --no-gsc --no-crawl-snapshot   # homepage only, unless --url given

Output: structured JSON to stdout; also written to
.seo-engine/reports/cwv-audit-<timestamp>.json and merged into
.seo-engine/state/cwv-history.json (one time series per URL+strategy) so
successive runs can show trend, not just a snapshot.
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

import argparse
import json
import time
from datetime import timedelta, datetime, timezone
from typing import Any, Optional

from scripts.lib import http_util, pagerules, psi, snapshots, urlnorm
from scripts.lib.config import Config, MissingConfigError

THRESHOLDS = {
    "lcp_ms": {"good": 2500, "needs_improvement": 4000},
    "inp_ms": {"good": 200, "needs_improvement": 500},
    "cls": {"good": 0.1, "needs_improvement": 0.25},
}

OPPORTUNITY_AUDIT_IDS = [
    "render-blocking-resources",
    "unused-css-rules",
    "unused-javascript",
    "modern-image-formats",
    "uses-optimized-images",
    "uses-responsive-images",
    "efficient-animated-content",
    "offscreen-images",
    "unminified-css",
    "unminified-javascript",
    "prioritize-lcp-image",
    "duplicated-javascript",
    "legacy-javascript",
    "total-byte-weight",
    "font-display",
]
DIAGNOSTIC_AUDIT_IDS = [
    "layout-shift-elements",
    "largest-contentful-paint-element",
    "long-tasks",
    "non-composited-animations",
    "dom-size",
    "third-party-summary",
    "third-party-facades",
    "bootup-time",
    "mainthread-work-breakdown",
    "network-dependency-tree-insight",
    "render-blocking-insight",
    "cls-culprits-insight",
    "lcp-discovery-insight",
]

FIX_GUIDANCE = {
    "render-blocking-resources": "Defer or async non-critical <script>/<link rel=stylesheet> tags; inline critical CSS for above-the-fold content. Primarily helps LCP.",
    "unused-css-rules": "Split/purge unused CSS (e.g. per-route bundles, PurgeCSS/Tailwind JIT) to shrink render-blocking payload. Helps LCP.",
    "unused-javascript": "Code-split by route/component and lazy-load non-critical JS bundles. Helps LCP and INP (less main-thread parse/compile work).",
    "modern-image-formats": "Serve AVIF/WebP with fallback instead of JPEG/PNG. Helps LCP.",
    "uses-optimized-images": "Compress images and use a modern encoder/CDN image pipeline. Helps LCP.",
    "uses-responsive-images": "Serve `srcset`/`sizes` so mobile doesn't download desktop-resolution images. Helps LCP.",
    "efficient-animated-content": "Replace animated GIFs with video (webm/mp4) formats. Helps LCP and overall byte weight.",
    "offscreen-images": "Lazy-load (`loading=\"lazy\"`) below-the-fold images; never lazy-load the actual LCP element itself. Helps LCP.",
    "unminified-css": "Minify CSS at build time. Helps LCP.",
    "unminified-javascript": "Minify JS at build time. Helps LCP and INP.",
    "prioritize-lcp-image": "Add `fetchpriority=\"high\"` and avoid `loading=\"lazy\"` on the actual LCP image; consider `<link rel=preload>` for it. Directly targets LCP.",
    "duplicated-javascript": "De-duplicate bundled modules/libraries across chunks (check bundler config for repeated vendor code). Helps LCP and INP.",
    "legacy-javascript": "Drop unnecessary transpilation/polyfills for evergreen browsers (adjust browserslist/target). Helps LCP and INP.",
    "total-byte-weight": "Audit largest transferred resources (images, JS bundles, fonts) for outsized payloads. Helps LCP.",
    "font-display": "Set `font-display: swap` (or `optional`) in @font-face and/or preload critical font files. Helps LCP and reduces layout shift from font swap.",
    "layout-shift-elements": "Reserve explicit width/height (or aspect-ratio) on images, embeds, and ad slots that shift layout after load. Directly targets CLS.",
    "largest-contentful-paint-element": "Identifies which DOM element IS the LCP element -- use this to target the specific fix (preload it, don't lazy-load it, serve it pre-optimized).",
    "long-tasks": "Break up long JS main-thread tasks (>50ms) via chunking/yielding (e.g. `scheduler.yield()`, setTimeout breakup). Directly targets INP.",
    "non-composited-animations": "Switch animations to compositor-only properties (transform/opacity) instead of properties that trigger layout/paint. Helps CLS and INP.",
    "dom-size": "Reduce excessive DOM node count/depth (virtualize long lists, simplify markup). Helps INP (style/layout recalculation cost).",
    "third-party-summary": "Audit and defer/trim third-party scripts (analytics, ads, chat widgets, tag managers) -- each adds parse/exec cost outside your control. Helps LCP and INP.",
    "third-party-facades": "Use a facade/placeholder (click-to-load) for heavy embeds (YouTube, social widgets) instead of loading the full third-party script upfront. Helps LCP and INP.",
    "bootup-time": "Reduce JS execution time on load (code-split, remove unused polyfills/libraries). Helps INP.",
    "mainthread-work-breakdown": "Profile which task category (script eval, style/layout, rendering) dominates main-thread time and target that category specifically. Helps INP.",
    "network-dependency-tree-insight": "Flatten critical-request chains (e.g. CSS importing CSS importing fonts) so the browser can fetch critical resources in parallel. Helps LCP.",
    "render-blocking-insight": "Same remediation as render-blocking-resources (defer/inline/async). Helps LCP.",
    "cls-culprits-insight": "Lighthouse's newer consolidated view of what's causing layout shift -- cross-reference with layout-shift-elements. Directly targets CLS.",
    "lcp-discovery-insight": "Ensure the LCP resource is discoverable from the initial HTML (not injected only after JS runs) and is preloaded. Directly targets LCP.",
}


def _rating(metric: str, value: Optional[float]) -> str:
    if value is None:
        return "unknown"
    t = THRESHOLDS[metric]
    if value <= t["good"]:
        return "good"
    if value <= t["needs_improvement"]:
        return "needs_improvement"
    return "poor"


def _extract_lighthouse_audits(psi_report: dict[str, Any]) -> dict[str, Any]:
    """Pull opportunities/diagnostics defensively -- Lighthouse audit-ID keys
    have shifted between versions before, so every access here degrades to
    "not present" rather than raising."""
    lighthouse = psi_report.get("lighthouseResult") or {}
    audits = lighthouse.get("audits") or {}
    lh_version = lighthouse.get("lighthouseVersion", "unknown")

    def _collect(audit_ids: list[str]) -> list[dict[str, Any]]:
        found = []
        for audit_id in audit_ids:
            audit = audits.get(audit_id)
            if not audit:
                continue
            score = audit.get("score")
            if score is not None and score >= 0.9:
                continue
            entry = {
                "id": audit_id,
                "title": audit.get("title"),
                "score": score,
                "display_value": audit.get("displayValue"),
                "fix_guidance": FIX_GUIDANCE.get(audit_id),
            }
            details = audit.get("details") or {}
            if details.get("overallSavingsMs"):
                entry["estimated_savings_ms"] = details["overallSavingsMs"]
            if details.get("overallSavingsBytes"):
                entry["estimated_savings_bytes"] = details["overallSavingsBytes"]
            found.append(entry)
        found.sort(key=lambda e: e.get("estimated_savings_ms", 0), reverse=True)
        return found

    perf_category = (lighthouse.get("categories") or {}).get("performance") or {}

    return {
        "lighthouse_version": lh_version,
        "lab_performance_score": perf_category.get("score"),
        "opportunities": _collect(OPPORTUNITY_AUDIT_IDS),
        "diagnostics": _collect(DIAGNOSTIC_AUDIT_IDS),
    }


def _discover_key_pages(
    cfg: Config,
    max_pages: int,
    use_crawl_snapshot: bool,
    use_gsc: bool,
) -> tuple[list[str], list[str]]:
    """Homepage + top pages from the crawl-snapshot store and/or GSC
    top-clicked pages. Returns (urls, notes) where notes explain what
    was/wasn't used. URLs are deduplicated by urlnorm.canonical_key but
    reported/audited in their raw observed form."""
    notes: list[str] = []
    site_url = cfg.site_url
    urls: list[str] = [site_url]
    seen = {urlnorm.canonical_key(site_url)}

    if use_crawl_snapshot:
        snap = None
        try:
            snap = snapshots.latest(cfg)
            if snap is not None:
                notes.append(
                    f"Reusing crawl snapshot {snap.path.name} "
                    f"(producer: {snap.meta.get('producer_skill', 'unknown')}, "
                    f"{snap.pages_crawled} pages, finished {snap.meta.get('finished_at', '?')})."
                )
            else:
                snap = snapshots.new_crawl(cfg, "seo-performance", max_pages=max_pages)
                summary = snap.meta.get("crawl_summary") or {}
                if summary.get("all_blocked"):
                    notes.append(
                        "Fresh crawl produced no usable pages -- robots_status="
                        f"{summary.get('robots_status', 'unknown')} (the crawl was blocked "
                        "by/because of robots.txt). Page discovery falls back to the "
                        "homepage and GSC only."
                    )
                else:
                    notes.append(
                        f"No reusable snapshot (<24h) found -- ran a fresh crawl "
                        f"({snap.pages_crawled} pages, snapshot {snap.path.name})."
                    )
        except Exception as exc:
            snap = None
            notes.append(
                "Crawl-snapshot discovery failed, continuing without it: "
                f"{http_util.sanitize_text(str(exc))}"
            )
        if snap is not None:
            count = 0
            for record in snap.pages():
                if count >= max_pages:
                    break
                url = record.get("final_url") or record.get("url")
                if not url or not pagerules.is_indexable_html(record):
                    continue
                key = urlnorm.canonical_key(url)
                if key in seen:
                    continue
                urls.append(url)
                seen.add(key)
                count += 1
            notes.append(f"Added {count} page(s) from crawl snapshot {snap.path.name}.")

    if use_gsc:
        integrations = cfg.available_integrations()
        if integrations.get("google_search_console"):
            try:
                from scripts.lib import gsc

                end = gsc.gsc_today() - timedelta(days=3)
                start = end - timedelta(days=28)
                result = gsc.search_analytics_query(
                    cfg, start.isoformat(), end.isoformat(),
                    dimensions=["page"], row_limit=max_pages,
                )
                added = 0
                for row in result.get("rows", []):
                    url = row.get("keys", [None])[0]
                    if not url or added >= max_pages:
                        continue
                    key = urlnorm.canonical_key(url)
                    if key in seen:
                        continue
                    urls.append(url)
                    seen.add(key)
                    added += 1
                notes.append(f"Added {added} top-clicked page(s) from GSC (last 28 days).")
            except MissingConfigError as exc:
                notes.append(f"GSC configured but credentials incomplete: {exc}")
            except Exception as exc:
                notes.append(
                    "GSC query failed, continuing without it: "
                    f"{http_util.sanitize_text(str(exc))}"
                )
        else:
            notes.append(
                "GOOGLE_APPLICATION_CREDENTIALS / GSC_SERVICE_ACCOUNT_JSON not set -- "
                "skipping GSC top-page discovery. Set one of these to include real "
                "top-clicked pages instead of only the homepage/crawl sample. See "
                "references/api-reference.md (Google Search Console API section)."
            )

    return urls[:max_pages], notes


def _load_history(cfg: Config) -> dict[str, Any]:
    path = cfg.state_dir / "cwv-history.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_history(cfg: Config, history: dict[str, Any]) -> Path:
    path = cfg.state_dir / "cwv-history.json"
    path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    return path


def audit_page(cfg: Config, url: str, strategy: str) -> dict[str, Any]:
    try:
        report = psi.run_pagespeed(cfg, url, strategy=strategy)
    except Exception as exc:
        return {"url": url, "strategy": strategy, "error": http_util.sanitize_text(str(exc))}

    field = psi.core_web_vitals(report)
    field_status = {
        "lcp_ms": {"value": field["lcp_ms"], "rating": _rating("lcp_ms", field["lcp_ms"])},
        "inp_ms": {"value": field["inp_ms"], "rating": _rating("inp_ms", field["inp_ms"])},
        "cls": {"value": field["cls"], "rating": _rating("cls", field["cls"])},
        "overall_category": field.get("overall_category"),
        "has_field_data": any(
            field[k] is not None for k in ("lcp_ms", "inp_ms", "cls")
        ),
    }
    lab = _extract_lighthouse_audits(report)

    failing_metrics = [
        m for m in ("lcp_ms", "inp_ms", "cls")
        if field_status[m]["rating"] == "poor"
    ]
    needs_improvement_metrics = [
        m for m in ("lcp_ms", "inp_ms", "cls")
        if field_status[m]["rating"] == "needs_improvement"
    ]

    return {
        "url": url,
        "strategy": strategy,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "field_data": field_status,
        "lab_diagnostics": lab,
        "failing_metrics": failing_metrics,
        "needs_improvement_metrics": needs_improvement_metrics,
        "passes_core_web_vitals_assessment": (
            field_status["overall_category"] == "FAST"
            if field_status["overall_category"] else (not failing_metrics and field_status["has_field_data"])
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit Core Web Vitals (field data authoritative, lab data diagnostic) "
                    "across key pages via PageSpeed Insights."
    )
    parser.add_argument("--url", action="append", default=[],
                        help="Specific URL to audit; repeatable. If given, disables auto-discovery "
                             "unless --include-discovered is also passed.")
    parser.add_argument("--include-discovered", action="store_true",
                        help="Combine --url pages with auto-discovered pages instead of replacing them.")
    parser.add_argument("--strategy", default="mobile", choices=["mobile", "desktop"],
                        help="PSI strategy. Google's CWV assessment for ranking is mobile-first; "
                             "default is mobile.")
    parser.add_argument("--both-strategies", action="store_true",
                        help="Also audit desktop in the same run (doubles PSI calls).")
    parser.add_argument("--max-pages", type=int, default=10,
                        help="Max key pages to audit (homepage always included).")
    parser.add_argument("--no-crawl-snapshot", action="store_true",
                        help="Don't pull extra pages from the crawl-snapshot store (and don't "
                             "run a fresh discovery crawl when no reusable snapshot exists).")
    parser.add_argument("--no-gsc", action="store_true",
                        help="Don't pull top-clicked pages from Search Console.")
    args = parser.parse_args()

    cfg = config_module.load()
    snapshots.prune(cfg)

    integrations = cfg.available_integrations()
    setup_notes: list[str] = []
    if not integrations.get("pagespeed_insights"):
        setup_notes.append(
            "GOOGLE_PSI_API_KEY not set -- PSI requests will use the shared unkeyed quota "
            "(low, shared across all unauthenticated callers, prone to throttling). "
            "Get a key at https://developers.google.com/speed/docs/insights/v5/get-started "
            "(same key also unlocks the dedicated CrUX API) and set GOOGLE_PSI_API_KEY."
        )

    explicit_urls = list(dict.fromkeys(args.url))
    discovery_notes: list[str] = []
    if explicit_urls and not args.include_discovered:
        urls = explicit_urls
    else:
        discovered, discovery_notes = _discover_key_pages(
            cfg,
            max_pages=args.max_pages,
            use_crawl_snapshot=not args.no_crawl_snapshot,
            use_gsc=not args.no_gsc,
        )
        urls = list(dict.fromkeys(explicit_urls + discovered)) if explicit_urls else discovered

    strategies = ["mobile", "desktop"] if args.both_strategies else [args.strategy]

    history = _load_history(cfg)
    pages_result: list[dict[str, Any]] = []
    for url in urls:
        for strategy in strategies:
            result = audit_page(cfg, url, strategy)
            pages_result.append(result)

            if "error" not in result:
                key = f"{url}::{strategy}"
                history.setdefault(key, [])
                history[key].append({
                    "fetched_at": result["fetched_at"],
                    "lcp_ms": result["field_data"]["lcp_ms"]["value"],
                    "inp_ms": result["field_data"]["inp_ms"]["value"],
                    "cls": result["field_data"]["cls"]["value"],
                    "overall_category": result["field_data"]["overall_category"],
                    "lab_performance_score": result["lab_diagnostics"]["lab_performance_score"],
                })
                history[key] = history[key][-52:]

    history_path = _save_history(cfg, history)

    valid_pages = [p for p in pages_result if "error" not in p]
    summary = {
        "pages_audited": len(valid_pages),
        "pages_failed_to_fetch": len(pages_result) - len(valid_pages),
        "pages_with_field_data": sum(1 for p in valid_pages if p["field_data"]["has_field_data"]),
        "pages_passing_cwv_assessment": sum(1 for p in valid_pages if p["passes_core_web_vitals_assessment"]),
        "pages_failing_lcp": sum(1 for p in valid_pages if "lcp_ms" in p["failing_metrics"]),
        "pages_failing_inp": sum(1 for p in valid_pages if "inp_ms" in p["failing_metrics"]),
        "pages_failing_cls": sum(1 for p in valid_pages if "cls" in p["failing_metrics"]),
    }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "site_url": cfg.site_url,
        "thresholds_ms_and_unitless": THRESHOLDS,
        "methodology_note": (
            "field_data comes from CrUX real-user metrics (loadingExperience in the PSI "
            "response) and is the authoritative, ranking-relevant signal. lab_diagnostics "
            "comes from a synthetic Lighthouse run and has no ranking weight of its own -- "
            "use it only to explain *why* field data is failing and to guide the fix. "
            "See references/seo-playbook.md section 3."
        ),
        "setup_notes": setup_notes,
        "discovery_notes": discovery_notes,
        "summary": summary,
        "pages": pages_result,
        "history_file": str(history_path),
    }

    reports_dir = cfg.reports_dir
    ts = time.strftime("%Y%m%d-%H%M%S")
    report_path = reports_dir / f"cwv-audit-{ts}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report_file"] = str(report_path)

    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
