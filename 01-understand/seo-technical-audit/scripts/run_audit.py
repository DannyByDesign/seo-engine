"""seo-technical-audit: crawl-based technical SEO health audit.

Checks (all from one snapshot-store crawl + optional integrations):
* accidental noindex — evidence-laddered: a noindex page is only a finding
  when corroborated (listed in sitemap.xml, or has GSC impressions), and
  known-intentional path patterns (/login, /cart, ...) are suppressed. A
  bare "noindex + has inbound links" test is vacuous — every crawled page
  has inbound links by construction (that's how the crawler found it).
* cross-domain canonicals — genuinely different host only (www/apex/scheme
  variants are the same site); security-shaped, never auto-fixed.
* broken internal links — targets serving >= 400 (fetch errors are listed
  separately as possibly-transient, never as broken links).
* redirect taxonomy via lib/redirect_analysis (shared with seo-redirects):
  loops are TooManyRedirects-based; slash/www-normalizing redirects are
  info-level hygiene, not defects.
* crawl-vs-sitemap diff with identity folding on both sides.
* optional: Firecrawl raw-vs-rendered JS gap sample; GSC declared-vs-
  selected canonical cross-check (a finding ONLY when Google disagrees).

Output: JSON to stdout + .seo-engine/reports/technical-audit-<date>.json.
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
import re
import time
from typing import Any, Optional

from scripts.lib import (
    crawler, pagerules, redirect_analysis, robots, sitemaps, snapshots, urlnorm,
)

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

INTENTIONAL_NOINDEX_RE = re.compile(
    r"/(login|signin|signup|logout|cart|checkout|account|admin|search|preview)([/?]|$)"
    r"|/tag/|[?&]s=",
    re.IGNORECASE,
)


def _gsc_page_keys(cfg) -> Optional[set]:
    """Folded keys of pages with any GSC impressions in the last 90 days —
    the 'this page had search presence' evidence tier. None = unavailable."""
    if not cfg.integration_available("google_search_console"):
        return None
    try:
        from datetime import timedelta
        from scripts.lib import gsc

        end = gsc.gsc_today() - timedelta(days=3)
        start = end - timedelta(days=90)
        rows, _ = gsc.search_analytics_query_all(
            cfg, start.isoformat(), end.isoformat(),
            dimensions=["page"], max_rows=100_000,
        )
        return {urlnorm.canonical_key(r["keys"][0]) for r in rows if r.get("keys")}
    except Exception:
        return None


def find_noindex_findings(
    pages: list[dict], sitemap_keys: set, gsc_keys: Optional[set],
) -> tuple[list[dict], int]:
    """Evidence ladder for noindex pages. Returns (findings, observed_count).

    - in sitemap + GSC impressions -> accidental_noindex, high
    - GSC impressions only         -> accidental_noindex, high (human review)
    - in sitemap only              -> noindex_sitemap_conflict, medium
    - intentional path pattern     -> suppressed (info counter only)
    - no corroboration             -> counted, not a finding
    """
    findings = []
    observed = 0
    for p in pages:
        if not pagerules.is_noindex(p):
            continue
        observed += 1
        url = p.get("url", "")
        if INTENTIONAL_NOINDEX_RE.search(url):
            continue
        key = urlnorm.canonical_key(p.get("final_url") or url)
        in_sitemap = key in sitemap_keys
        had_traffic = bool(gsc_keys) and key in gsc_keys

        if not in_sitemap and not had_traffic:
            continue

        if had_traffic:
            finding_type, severity = "accidental_noindex", "high"
            evidence = ("page had Google Search impressions in the last 90 days"
                        + (" AND is listed in sitemap.xml" if in_sitemap else ""))
        else:
            finding_type, severity = "noindex_sitemap_conflict", "medium"
            evidence = "page is listed in sitemap.xml (sitemaps declare indexable URLs)"

        findings.append({
            "type": finding_type,
            "severity": severity,
            "url": url,
            "meta_robots": p.get("meta_robots", ""),
            "x_robots_tag": p.get("x_robots_tag", ""),
            "evidence": evidence,
            "detail": (
                f"{url} is marked noindex, but {evidence} — this looks accidental "
                "(staging leftover, CMS default, or a conditional meant for a "
                "different subset of pages)."
            ),
            "red_flags_ref": "red-flags.md §4 (Accidental noindex)",
            "auto_fixable": False,
            "human_review_reason": (
                "Removing noindex could itself be wrong if it was intentional — flag, "
                "don't guess. A human/agent must confirm intent before changing."
            ),
        })
    return findings, observed


def find_cross_domain_canonicals(pages: list[dict], site_url: str) -> list[dict]:
    """Canonical tag pointing to a genuinely different host — potential
    canonical hijacking. www/apex/scheme variants do NOT trigger this."""
    findings = []
    for p in pages:
        canonical = p.get("canonical", "")
        if not canonical:
            continue
        page_url = p.get("final_url") or p.get("url", "")
        if urlnorm.is_cross_host_canonical(canonical, page_url) \
                and urlnorm.is_cross_host_canonical(canonical, site_url):
            findings.append({
                "type": "cross_domain_canonical",
                "severity": "critical",
                "url": p.get("url", ""),
                "declared_canonical": canonical,
                "canonical_host": urlnorm.host_key(canonical),
                "site_host": urlnorm.host_key(site_url),
                "detail": (
                    f"{p.get('url', '')} declares a canonical pointing to a different "
                    f"host ({urlnorm.host_key(canonical)}) than the site itself "
                    f"({urlnorm.host_key(site_url)}). This matches the canonical-"
                    "hijacking pattern used against compromised sites."
                ),
                "red_flags_ref": "red-flags.md §4 (Canonical loops and cross-domain canonical hijacking); seo-playbook.md §5",
                "auto_fixable": False,
                "human_review_reason": (
                    "Treat as a potential security incident, not a routine SEO fix. "
                    "Escalate to a human before touching this page's canonical tag."
                ),
            })
    return findings


def find_broken_internal_links(pages: list[dict]) -> tuple[list[dict], list[dict]]:
    """(broken_link_findings, fetch_error_notes). Broken = target serves
    >= 400. Fetch errors (status -1) are possibly-transient and listed
    separately — a network blip is not a broken link."""
    status_by_key: dict[str, dict] = {}
    for p in pages:
        for candidate in (p.get("url", ""), p.get("final_url", "")):
            if candidate:
                status_by_key.setdefault(urlnorm.canonical_key(candidate), p)

    linkers_by_target: dict[str, set] = {}
    for p in pages:
        if p.get("status") != 200 or p.get("error"):
            continue
        for link in p.get("internal_links", []):
            linkers_by_target.setdefault(urlnorm.canonical_key(link), set()).add(p.get("url", ""))

    findings, error_notes = [], []
    for target_key, linkers in linkers_by_target.items():
        target_page = status_by_key.get(target_key)
        if target_page is None:
            continue
        status = target_page.get("status")
        target_url = target_page.get("url", "")
        if target_page.get("error"):
            error_notes.append({
                "type": "linked_page_fetch_error",
                "severity": "low",
                "target_url": target_url,
                "error_type": target_page.get("error_type", ""),
                "linked_from_count": len(linkers),
                "detail": (
                    f"{target_url} (linked from {len(linkers)} page(s)) failed to fetch "
                    f"({target_page.get('error_type') or 'unknown'}) — possibly transient; "
                    "re-check before treating as broken."
                ),
            })
        elif (status or 0) >= 400:
            findings.append({
                "type": "broken_internal_link",
                "severity": "high" if status >= 500 else "medium",
                "target_url": target_url,
                "target_status": status,
                "linked_from": sorted(linkers)[:20],
                "linked_from_count": len(linkers),
                "detail": (
                    f"{len(linkers)} page(s) link internally to {target_url}, which "
                    f"returned HTTP {status} instead of 200."
                ),
                "seo_playbook_ref": "seo-playbook.md §2 (Crawlable internal link graph)",
                "auto_fixable": False,
                "human_review_reason": (
                    "Fixing requires knowing whether the correct remedy is updating the "
                    "link, restoring the target page, or adding a redirect — a code-aware "
                    "agent should choose, not this script."
                ),
            })
    return findings, error_notes


def find_sitemap_mismatches(pages: list[dict], sitemap_result: dict) -> dict:
    """Diff crawled indexable URLs against declared sitemap URLs, with
    identity folding on BOTH sides (scheme/www/slash variants are the same
    page — without folding, a www-declaring sitemap against an apex crawl
    reports every page missing)."""
    if not sitemap_result.get("found"):
        return {
            "checked": False,
            "reason": "no sitemap found ("
                      + "; ".join(sitemap_result.get("errors", [])[:3] or ["tried default locations"])
                      + ")",
            "missing_from_sitemap": [],
            "should_not_be_in_sitemap": [],
        }

    sitemap_keys = {urlnorm.canonical_key(u) for u in sitemap_result["page_urls"]}
    by_key = {urlnorm.canonical_key(p.get("final_url") or p.get("url", "")): p for p in pages}

    missing = []
    should_not = []

    for key, p in by_key.items():
        canonical = p.get("canonical") or ""
        page_url = p.get("final_url") or p.get("url", "")
        is_self_canonical = not canonical or urlnorm.same_page(canonical, page_url)
        if pagerules.is_indexable_html(p) and is_self_canonical and key not in sitemap_keys:
            missing.append({
                "url": p.get("url", ""),
                "detail": "Indexable (200, no noindex, self-canonical) but not listed in the sitemap.",
            })

    for key in sitemap_keys:
        p = by_key.get(key)
        if p is None:
            continue
        reasons = []
        if p.get("error"):
            continue
        if p.get("status") != 200:
            reasons.append(f"HTTP {p.get('status')}")
        if pagerules.is_noindex(p):
            reasons.append("noindex")
        canonical = p.get("canonical") or ""
        page_url = p.get("final_url") or p.get("url", "")
        if canonical and not urlnorm.same_page(canonical, page_url):
            reasons.append(f"canonicalizes to {canonical}")
        if reasons:
            should_not.append({
                "url": p.get("url", ""),
                "reason": ", ".join(reasons),
                "detail": f"Listed in the sitemap but not indexable: {', '.join(reasons)}.",
            })

    return {
        "checked": True,
        "sitemap_url_count": len(sitemap_keys),
        "sitemaps_read": sitemap_result.get("sitemaps_read", []),
        "truncated": sitemap_result.get("truncated", False),
        "missing_from_sitemap": missing,
        "should_not_be_in_sitemap": should_not,
    }


def sample_js_rendering_gaps(cfg, pages: list[dict], sample_size: int) -> dict:
    """If FIRECRAWL_API_KEY is configured, sample HTML pages and diff raw vs.
    rendered content via Firecrawl. The free heuristic version of this check
    lives in geo-optimize's check_js_visibility.py (geo-playbook.md §11)."""
    if not cfg.integration_available("firecrawl"):
        return {
            "checked": False,
            "reason": (
                "FIRECRAWL_API_KEY not set — skipping rendered-diff JS check. "
                "geo-optimize's check_js_visibility.py covers the free heuristic "
                "version; set FIRECRAWL_API_KEY for the rendered diff."
            ),
            "findings": [],
        }

    from scripts.lib import firecrawl, http_util

    html_pages = [p for p in pages if pagerules.is_indexable_html(p)]
    html_pages.sort(key=lambda p: p.get("url", ""))
    stride = max(len(html_pages) // sample_size, 1) if html_pages else 1
    sample = html_pages[::stride][:sample_size]

    findings = []
    errors = []
    for p in sample:
        try:
            diff = firecrawl.diff_raw_vs_rendered(cfg, p["url"])
        except Exception as exc:
            errors.append({"url": p["url"], "error": http_util.sanitize_text(str(exc))})
            continue
        if diff.get("likely_js_dependent"):
            findings.append({
                "type": "js_rendering_gap",
                "severity": "medium",
                "url": diff["url"],
                "raw_word_count": diff["raw_word_count"],
                "rendered_word_count": diff["rendered_word_count"],
                "gap_ratio": diff["gap_ratio"],
                "detail": (
                    f"{diff['url']}: raw HTTP fetch sees {diff['raw_word_count']} words, "
                    f"rendered content has {diff['rendered_word_count']} words "
                    f"(gap ratio {diff['gap_ratio']:.2f}). This content is invisible to "
                    "every major AI crawler (none execute JavaScript — geo-playbook.md "
                    "§11) and possibly under-seen by Google."
                ),
                "red_flags_ref": "red-flags.md §4 (JS-rendering traps); geo-playbook.md §11",
                "auto_fixable": False,
                "human_review_reason": (
                    "Fixing requires a framework-level decision (SSR/SSG/prerendering) that "
                    "a code-aware agent must make in context of the actual stack."
                ),
            })

    return {
        "checked": True,
        "sample_size_requested": sample_size,
        "sample_size_actual": len(sample),
        "sampled_urls": [p["url"] for p in sample],
        "errors": errors,
        "findings": findings,
    }


def sample_canonical_gsc_crosscheck(cfg, pages: list[dict],
                                    cross_domain_findings: list[dict],
                                    sample_size: int) -> dict:
    """GSC declared-vs-Google-selected canonical cross-check.

    Sample: cross-domain findings first, then pages whose declared canonical
    differs substantively from their own URL. A finding is emitted ONLY when
    Google's selected canonical is present AND disagrees with the declared
    one — agreement is recorded in `confirmed`, not inflated into findings.
    """
    if not cfg.integration_available("google_search_console"):
        return {
            "checked": False,
            "reason": (
                "Google Search Console not configured — skipping declared-vs-selected "
                "canonical cross-check. Set GOOGLE_APPLICATION_CREDENTIALS (service "
                "account JSON path) to unlock this (see api-reference.md)."
            ),
            "findings": [],
        }

    from scripts.lib import gsc, http_util

    candidates: list[dict] = [
        {"url": f["url"], "declared_canonical": f.get("declared_canonical", "")}
        for f in cross_domain_findings
    ]
    seen = {c["url"] for c in candidates}
    for p in pages:
        canonical = p.get("canonical") or ""
        page_url = p.get("final_url") or p.get("url", "")
        if canonical and not urlnorm.same_page(canonical, page_url) and p.get("url") not in seen:
            candidates.append({"url": p["url"], "declared_canonical": canonical})
            seen.add(p["url"])

    sample = candidates[:sample_size]
    findings, confirmed, errors = [], [], []
    for c in sample:
        url = c["url"]
        try:
            result = gsc.inspect_url(cfg, url)
        except Exception as exc:
            errors.append({"url": url, "error": http_util.sanitize_text(str(exc))})
            continue
        index_result = result.get("inspectionResult", {}).get("indexStatusResult", {})
        google_canonical = index_result.get("googleCanonical", "")
        user_canonical = index_result.get("userCanonical", "")
        if not google_canonical:
            confirmed.append({"url": url, "note": "Google has not selected a canonical (not indexed yet?)"})
            continue
        if urlnorm.same_page(google_canonical, c["declared_canonical"]):
            confirmed.append({
                "url": url,
                "declared_canonical": c["declared_canonical"],
                "google_selected_canonical": google_canonical,
                "note": "Google's selected canonical agrees with the declared one.",
            })
            continue
        findings.append({
            "type": "canonical_gsc_disagreement",
            "severity": "high",
            "url": url,
            "declared_canonical": c["declared_canonical"],
            "gsc_user_canonical": user_canonical,
            "gsc_google_selected_canonical": google_canonical,
            "detail": (
                f"Google selected '{google_canonical}' as the canonical for {url}, "
                f"disagreeing with the declared '{c['declared_canonical']}' — the "
                "declared canonical is being ignored; investigate why (conflicting "
                "signals, redirects, or content duplication)."
            ),
            "seo_playbook_ref": "seo-playbook.md §5 (Canonicalization and indexing hygiene)",
            "auto_fixable": False,
        })

    return {
        "checked": True,
        "sample_size_requested": sample_size,
        "sample_size_actual": len(sample),
        "confirmed": confirmed,
        "errors": errors,
        "findings": findings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="seo-technical-audit: crawl-based technical SEO audit")
    parser.add_argument("--max-pages", type=int, default=crawler.DEFAULT_MAX_PAGES)
    parser.add_argument("--delay", type=float, default=crawler.CRAWL_DELAY_SECONDS)
    parser.add_argument("--sample-js", type=int, default=5,
                        help="how many pages to sample for the Firecrawl JS-rendering-gap check")
    parser.add_argument("--sample-canonical", type=int, default=5,
                        help="how many canonical-conflict pages to cross-check via GSC")
    parser.add_argument("--ignore-robots", action="store_true",
                        help="only for your own localhost/staging builds")
    parser.add_argument("--skip-crawl", action="store_true",
                        help="reuse the most recent shared snapshot (< 24h old) instead of recrawling")
    args = parser.parse_args()

    cfg = config_module.load()
    site_url = cfg.site_url

    snap = snapshots.latest(cfg, max_age_hours=24) if args.skip_crawl else None
    if snap is None:
        snap = snapshots.new_crawl(
            cfg, "seo-technical-audit",
            max_pages=args.max_pages, delay=args.delay, ignore_robots=args.ignore_robots,
        )
        crawl_summary = snap.meta.get("crawl_summary", {})
    else:
        crawl_summary = {"reused_existing_snapshot": True,
                         "snapshot": str(snap.path),
                         "produced_by": snap.meta.get("producer_skill", "unknown")}

    pages = list(snap.pages())

    if snap.meta.get("crawl_summary", {}).get("all_blocked"):
        report = {
            "site_url": site_url,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "error": (
                "Crawl produced zero pages: robots.txt "
                f"({snap.meta['crawl_summary'].get('robots_status')}) blocked everything. "
                "Nothing was audited. For your own staging build use --ignore-robots; "
                "for production, the site may be WAF-blocking this crawler's User-Agent."
            ),
            "findings": [],
        }
        json.dump(report, sys.stdout, indent=2)
        print()
        sys.exit(1)

    robots_policy = robots.fetch(site_url)
    sitemap_result = sitemaps.fetch_url_set(site_url, robots_policy)
    sitemap_keys = {urlnorm.canonical_key(u) for u in sitemap_result.get("page_urls", [])}
    gsc_keys = _gsc_page_keys(cfg)

    noindex_findings, noindex_observed = find_noindex_findings(pages, sitemap_keys, gsc_keys)
    cross_domain_canonicals = find_cross_domain_canonicals(pages, site_url)
    broken_links, fetch_error_notes = find_broken_internal_links(pages)

    redirect_result = redirect_analysis.classify_snapshot(pages)
    redirect_findings = (
        redirect_result["findings"]["redirect_loop"]
        + redirect_result["findings"]["redirect_chain"]
        + redirect_result["findings"]["canonicalization_chain"]
        + redirect_result["findings"]["link_to_redirect"]
    )

    sitemap_analysis = find_sitemap_mismatches(pages, sitemap_result)
    js_rendering = sample_js_rendering_gaps(cfg, pages, args.sample_js)
    canonical_gsc = sample_canonical_gsc_crosscheck(
        cfg, pages, cross_domain_canonicals, args.sample_canonical)

    all_findings = (
        noindex_findings
        + cross_domain_canonicals
        + broken_links
        + fetch_error_notes
        + redirect_findings
        + js_rendering.get("findings", [])
        + canonical_gsc.get("findings", [])
    )
    all_findings.sort(key=lambda f: SEVERITY_ORDER.get(f.get("severity", "low"), 9))

    severity_counts: dict[str, int] = {}
    for f in all_findings:
        severity_counts[f.get("severity", "unknown")] = severity_counts.get(f.get("severity", "unknown"), 0) + 1

    report = {
        "site_url": site_url,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "crawl_summary": crawl_summary,
        "pages_analyzed": len(pages),
        "snapshot": str(snap.path),
        "integrations_used": {
            "firecrawl": js_rendering.get("checked", False),
            "google_search_console": canonical_gsc.get("checked", False),
        },
        "integrations_available": cfg.available_integrations(),
        "severity_counts": severity_counts,
        "noindex_pages_observed": noindex_observed,
        "noindex_findings_note": (
            f"{noindex_observed} noindex page(s) observed; only corroborated cases "
            "(sitemap-listed or with GSC impressions) become findings — the rest are "
            "assumed intentional."
        ),
        "normalizing_redirects_observed": redirect_result["counts"]["normalizing_redirect"],
        "sitemap": {
            "checked": sitemap_analysis["checked"],
            "reason": sitemap_analysis.get("reason"),
            "sitemap_url_count": sitemap_analysis.get("sitemap_url_count"),
            "sitemaps_read": sitemap_analysis.get("sitemaps_read", []),
            "missing_from_sitemap_count": len(sitemap_analysis.get("missing_from_sitemap", [])),
            "should_not_be_in_sitemap_count": len(sitemap_analysis.get("should_not_be_in_sitemap", [])),
            "missing_from_sitemap": sitemap_analysis.get("missing_from_sitemap", []),
            "should_not_be_in_sitemap": sitemap_analysis.get("should_not_be_in_sitemap", []),
        },
        "js_rendering_check": {
            "checked": js_rendering.get("checked", False),
            "reason": js_rendering.get("reason"),
            "sample_size_requested": js_rendering.get("sample_size_requested"),
            "sample_size_actual": js_rendering.get("sample_size_actual"),
            "errors": js_rendering.get("errors", []),
        },
        "canonical_gsc_crosscheck": {
            "checked": canonical_gsc.get("checked", False),
            "reason": canonical_gsc.get("reason"),
            "sample_size_requested": canonical_gsc.get("sample_size_requested"),
            "sample_size_actual": canonical_gsc.get("sample_size_actual"),
            "confirmed": canonical_gsc.get("confirmed", []),
            "errors": canonical_gsc.get("errors", []),
        },
        "findings": all_findings,
    }

    dated_report_path = cfg.reports_dir / f"technical-audit-{time.strftime('%Y-%m-%d')}.json"
    dated_report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["_report_path"] = str(dated_report_path)

    snapshots.prune(cfg)

    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
