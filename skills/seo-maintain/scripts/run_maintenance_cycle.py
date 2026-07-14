"""Continuous-maintenance orchestrator: regression-first SEO+GEO checkup.

Runs a fresh crawl into the shared snapshot store (lib/snapshots.py), diffs
it against the most recent COMPARABLE baseline (same site, same max_pages,
neither truncated — diffing incomparable crawls reports coverage changes as
regressions, so the store refuses instead), pulls adjacent-window Google
Search Console deltas when GSC is configured, and ranks improvement
opportunities from the fresh crawl.

This script NEVER modifies site content or config. It only reads, diffs, and
writes a JSON report + snapshot state. Every finding is tagged with the name
of the other seo-engine skill that owns fixing it — the calling agent
decides whether/how to invoke that skill next.

Identity note: pages are keyed by urlnorm.canonical_key, so /about vs
/about/ vs www-variants are one page, and a www<->apex canonical is NOT a
"cross-domain hijack" (only a genuinely different host is).

Orphan detection is deliberately NOT here: a link-following crawl cannot
discover unlinked pages by construction — seo-internal-linking owns that
check (it builds a sitemap/GSC URL universe). This report only points at it.

Usage:
    python3 run_maintenance_cycle.py [--max-pages 500] [--gsc-days 28]

Output: a JSON report written to .seo-engine/reports/maintenance-<date>.json
and also printed to stdout.
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
import json  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from typing import Any  # noqa: E402

from scripts.lib import pagerules, redirect_analysis, snapshots, urlnorm  # noqa: E402
from scripts.lib.config import Config  # noqa: E402

try:
    from scripts.lib import gsc as gsc_module
except ImportError:
    gsc_module = None

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
GSC_LAG_DAYS = 3


def _index_by_key(snap: "snapshots.Snapshot") -> dict[str, dict[str, Any]]:
    """canonical_key(requested url) -> record. Request identity (not final
    destination) so a page that starts redirecting is still 'present'."""
    pages: dict[str, dict[str, Any]] = {}
    for record in snap.pages():
        key = urlnorm.canonical_key(record.get("url", ""))
        if key:
            pages[key] = record
    return pages


# ---------------------------------------------------------------------------
# Crawl-diff regressions
# ---------------------------------------------------------------------------

def detect_regressions(
    previous: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
    *,
    suppress_disappeared: bool = False,
) -> list[dict[str, Any]]:
    """Compare two comparable crawl snapshots and surface what got WORSE.

    Only regressions — a page that improved is a return to baseline, not
    news. Each finding names the owning skill, per red-flags.md's guidance
    to flag rather than auto-guess on anything ambiguous.
    """
    regressions: list[dict[str, Any]] = []

    for key, prev_rec in previous.items():
        cur_rec = current.get(key)
        if cur_rec is None:
            continue
        url = cur_rec.get("url", prev_rec.get("url", ""))

        # 1. New noindex on a previously indexable page (meta OR header).
        if not pagerules.is_noindex(prev_rec) and pagerules.is_noindex(cur_rec):
            regressions.append({
                "type": "new_noindex",
                "severity": "critical",
                "url": url,
                "detail": (
                    f"Page previously indexable is now emitting noindex "
                    f"(meta_robots='{cur_rec.get('meta_robots', '')}', "
                    f"x_robots_tag='{cur_rec.get('x_robots_tag', '')}'). "
                    "Could be intentional (do not auto-remove) or an accidental "
                    "CMS/template regression — verify against red-flags.md §4."
                ),
                "dispatch_skill": "seo-technical-audit",
                "human_review_required": True,
            })

        # 2. Fetch/status regressions on previously-healthy pages.
        prev_ok = prev_rec.get("status") == 200 and not prev_rec.get("error")
        if prev_ok:
            cur_status = cur_rec.get("status")
            if cur_rec.get("error"):
                # A single failed fetch can be a transient blip — never critical.
                regressions.append({
                    "type": "fetch_error",
                    "severity": "medium",
                    "url": url,
                    "detail": (
                        f"Page fetched fine last cycle but errored this cycle "
                        f"({cur_rec.get('error_type') or 'unknown'}): "
                        f"{(cur_rec.get('error') or '')[:200]}. Could be transient — "
                        "re-check before treating as an outage."
                        + (" NOTE error_type=too_many_redirects is a genuine "
                           "redirect loop — dispatch seo-redirects."
                           if cur_rec.get("error_type") == "too_many_redirects" else "")
                    ),
                    "dispatch_skill": ("seo-redirects"
                                       if cur_rec.get("error_type") == "too_many_redirects"
                                       else "seo-technical-audit"),
                    "human_review_required": True,
                })
            elif cur_status != 200:
                regressions.append({
                    "type": "status_code_regression",
                    "severity": "critical" if (cur_status or 0) >= 500 else "high",
                    "url": url,
                    "detail": f"Status changed from 200 to {cur_status} since the baseline crawl.",
                    "dispatch_skill": "seo-technical-audit",
                    "human_review_required": False,
                })

        # 3. Canonical changes.
        prev_canonical = prev_rec.get("canonical") or ""
        cur_canonical = cur_rec.get("canonical") or ""
        if prev_canonical != cur_canonical:
            if cur_canonical and urlnorm.is_cross_host_canonical(cur_canonical, url):
                regressions.append({
                    "type": "cross_domain_canonical",
                    "severity": "critical",
                    "url": url,
                    "detail": (
                        f"Canonical tag now points to a DIFFERENT HOST: '{cur_canonical}' "
                        f"(was '{prev_canonical or '(none)'}'). This matches the documented "
                        "cross-domain canonical hijack attack pattern — treat as a security "
                        "incident, do not auto-correct. (www/apex/scheme variants of this "
                        "site would NOT trigger this finding.)"
                    ),
                    "dispatch_skill": "seo-redirects",
                    "human_review_required": True,
                })
            elif prev_canonical and not cur_canonical:
                regressions.append({
                    "type": "canonical_removed",
                    "severity": "medium",
                    "url": url,
                    "detail": (
                        f"Canonical tag removed (was '{prev_canonical}'). Removal can "
                        "reopen duplicate-content ambiguity — confirm it was intentional."
                    ),
                    "dispatch_skill": "seo-technical-audit",
                    "human_review_required": True,
                })
            elif prev_canonical and cur_canonical and not urlnorm.same_page(prev_canonical, cur_canonical):
                regressions.append({
                    "type": "canonical_changed",
                    "severity": "medium",
                    "url": url,
                    "detail": f"Canonical changed from '{prev_canonical}' to '{cur_canonical}'.",
                    "dispatch_skill": "seo-technical-audit",
                    "human_review_required": False,
                })

    # 4. New redirects on previously-direct pages (requests follows redirects,
    #    so these pages still report status 200 — the hop chain is the signal).
    regressions.extend(redirect_analysis.new_redirect_regressions(previous, current))
    for finding in regressions:
        finding.setdefault("dispatch_skill", "seo-redirects")

    # 5. Pages that disappeared entirely (suppressed when the crawl was
    #    truncated — disappearance is then indistinguishable from the cap).
    if not suppress_disappeared:
        for key, prev_rec in previous.items():
            if key in current:
                continue
            if prev_rec.get("status") != 200 or prev_rec.get("error") or pagerules.is_noindex(prev_rec):
                continue
            regressions.append({
                "type": "page_disappeared",
                "severity": "high",
                "url": prev_rec.get("url", ""),
                "detail": (
                    "Page was indexable in the baseline crawl and is no longer "
                    "reachable via internal links in this crawl (may be a broken "
                    "link graph, a removed page without a redirect, or an "
                    "orphaning regression)."
                ),
                "dispatch_skill": "seo-internal-linking",
                "human_review_required": True,
            })

    # 6. New broken internal links: links added since the baseline whose
    #    target now serves >= 400. Fetch errors (status -1) are excluded —
    #    a network blip is not a broken link.
    broken_targets = {
        key for key, rec in current.items()
        if not rec.get("error") and (rec.get("status") or 0) >= 400
    }
    for key, cur_rec in current.items():
        prev_rec = previous.get(key)
        prev_links = {urlnorm.canonical_key(u) for u in (prev_rec or {}).get("internal_links", [])}
        cur_links = {urlnorm.canonical_key(u) for u in cur_rec.get("internal_links", [])}
        newly_broken = sorted((cur_links - prev_links) & broken_targets)
        if newly_broken:
            regressions.append({
                "type": "new_broken_internal_links",
                "severity": "medium",
                "url": cur_rec.get("url", ""),
                "detail": (
                    f"{len(newly_broken)} newly-introduced internal link(s) on this "
                    f"page point to URLs now serving 4xx/5xx: {newly_broken[:5]}"
                    + (" (truncated)" if len(newly_broken) > 5 else "")
                ),
                "dispatch_skill": "seo-technical-audit",
                "human_review_required": False,
            })

    regressions.sort(key=lambda r: SEVERITY_ORDER.get(r["severity"], 9))
    return regressions


# ---------------------------------------------------------------------------
# Opportunity ranking (from the fresh crawl only — no baseline needed)
# ---------------------------------------------------------------------------

def detect_opportunities(current: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank improvement opportunities from the current crawl snapshot.

    These are NOT regressions — they may have existed for a long time. Each
    is tagged with impact/effort and the skill that owns implementing it.
    """
    opportunities: list[dict[str, Any]] = []

    def ok_pages():
        return ((rec.get("url", ""), rec) for rec in current.values()
                if rec.get("status") == 200 and not rec.get("error"))

    def html_ok(rec):
        return pagerules.is_html(rec)

    missing_title = [u for u, r in ok_pages() if html_ok(r) and not (r.get("title") or "").strip()]
    if missing_title:
        opportunities.append({
            "type": "missing_title_tag", "impact": "high", "effort": "low",
            "count": len(missing_title), "sample_urls": missing_title[:10],
            "detail": "Pages with no <title> tag — a foundational ranking and click-through element.",
            "dispatch_skill": "seo-metadata",
        })

    missing_desc = [u for u, r in ok_pages() if html_ok(r) and not (r.get("meta_description") or "").strip()]
    if missing_desc:
        opportunities.append({
            "type": "missing_meta_description", "impact": "medium", "effort": "low",
            "count": len(missing_desc), "sample_urls": missing_desc[:10],
            "detail": "Pages with no meta description — Google may auto-generate a snippet instead.",
            "dispatch_skill": "seo-metadata",
        })

    no_h1 = [u for u, r in ok_pages() if html_ok(r) and not r.get("h1")]
    if no_h1:
        opportunities.append({
            "type": "missing_h1", "impact": "medium", "effort": "low",
            "count": len(no_h1), "sample_urls": no_h1[:10],
            "detail": "Pages with no <h1> — weakens on-page structure for both crawlers and readers.",
            "dispatch_skill": "seo-metadata",
        })

    multi_h1 = [u for u, r in ok_pages() if len(r.get("h1", [])) > 1]
    if multi_h1:
        opportunities.append({
            "type": "multiple_h1", "impact": "low", "effort": "low",
            "count": len(multi_h1), "sample_urls": multi_h1[:10],
            "detail": "Pages with more than one <h1> — ambiguous primary-topic signal.",
            "dispatch_skill": "seo-metadata",
        })

    no_json_ld = [u for u, r in ok_pages() if html_ok(r) and not r.get("json_ld_types")]
    if no_json_ld:
        opportunities.append({
            "type": "no_structured_data", "impact": "medium", "effort": "medium",
            "count": len(no_json_ld), "sample_urls": no_json_ld[:10],
            "detail": (
                "Pages with no JSON-LD structured data. Justify this via rich-result "
                "eligibility and crawler comprehension (seo-playbook.md §8) — NOT as a "
                "GEO/AI-citation lever (geo-playbook.md §3 found no such causal benefit)."
            ),
            "dispatch_skill": "seo-structured-data",
        })

    json_ld_errors = [u for u, r in ok_pages() if r.get("json_ld_errors")]
    if json_ld_errors:
        opportunities.append({
            "type": "invalid_json_ld", "impact": "medium", "effort": "low",
            "count": len(json_ld_errors), "sample_urls": json_ld_errors[:10],
            "detail": "Pages with malformed JSON-LD (fails to parse) — invalidates any rich-result eligibility.",
            "dispatch_skill": "seo-structured-data",
        })

    deep_pages = [u for u, r in ok_pages() if r.get("depth", 0) > 4]
    if deep_pages:
        opportunities.append({
            "type": "excessive_link_depth", "impact": "low", "effort": "medium",
            "count": len(deep_pages), "sample_urls": deep_pages[:10],
            "detail": "Pages more than 4 clicks from the homepage — crawled/refreshed less often (seo-playbook.md §6).",
            "dispatch_skill": "seo-internal-linking",
        })

    images_missing_alt_count = sum(len(r.get("images_missing_alt", [])) for r in current.values())
    pages_with_missing_alt = [u for u, r in ok_pages() if r.get("images_missing_alt")]
    if pages_with_missing_alt:
        opportunities.append({
            "type": "images_missing_alt_text", "impact": "low", "effort": "medium",
            "count": images_missing_alt_count, "sample_urls": pages_with_missing_alt[:10],
            "detail": f"{images_missing_alt_count} images across {len(pages_with_missing_alt)} pages with no alt text.",
            "dispatch_skill": "seo-technical-audit",
        })

    thin_content = [
        u for u, r in ok_pages()
        if html_ok(r) and 0 < r.get("word_count", 0) < 150
    ]
    if thin_content:
        opportunities.append({
            "type": "thin_content", "impact": "medium", "effort": "high",
            "count": len(thin_content), "sample_urls": thin_content[:10],
            "detail": (
                "Pages under ~150 words of visible text. Flag for human review of genuine "
                "user value per seo-playbook.md §1 — do not pad word count as a fix; only "
                "expand if there is real, substantive content to add."
            ),
            "dispatch_skill": "seo-content-optimize",
            "human_review_required": True,
        })

    missing_lang = [u for u, r in ok_pages() if html_ok(r) and not (r.get("lang") or "").strip()]
    if missing_lang:
        opportunities.append({
            "type": "missing_html_lang", "impact": "low", "effort": "low",
            "count": len(missing_lang), "sample_urls": missing_lang[:10],
            "detail": "Pages with no <html lang> attribute set.",
            "dispatch_skill": "seo-technical-audit",
        })

    # hreflang reciprocity — per red-flags.md §4 (alias-folded lookups).
    by_key = {urlnorm.canonical_key(r.get("url", "")): r for r in current.values()}
    broken_reciprocal = []
    for url, rec in ok_pages():
        for tag in rec.get("hreflang", []):
            target_key = urlnorm.canonical_key(tag.get("href", ""))
            target_rec = by_key.get(target_key)
            if target_rec is None:
                continue  # target outside crawl scope — can't verify, skip rather than guess
            if not any(urlnorm.same_page(t.get("href", ""), url) for t in target_rec.get("hreflang", [])):
                broken_reciprocal.append(url)
                break
    if broken_reciprocal:
        opportunities.append({
            "type": "hreflang_missing_reciprocal", "impact": "medium", "effort": "medium",
            "count": len(broken_reciprocal), "sample_urls": broken_reciprocal[:10],
            "detail": "hreflang tags without a reciprocal return tag on the target page (red-flags.md §4).",
            "dispatch_skill": "seo-technical-audit",
        })

    impact_order = {"high": 0, "medium": 1, "low": 2}
    opportunities.sort(key=lambda o: (impact_order.get(o["impact"], 9), -o.get("count", 0)))
    return opportunities


# ---------------------------------------------------------------------------
# GSC-based regression checks (optional integration)
# ---------------------------------------------------------------------------

def check_gsc_regressions(cfg: Config, days: int) -> dict[str, Any]:
    """Adjacent-window GSC click comparison over FULLY PAGINATED page rows.

    Honesty rules: when either window hits the row cap, only pages present
    in BOTH windows are compared (absence from a truncated window is not
    zero clicks); drops need both a relative (>=50%) and an absolute (>=5
    clicks) floor; severity never exceeds high — click data cannot
    distinguish seasonality from breakage on its own.
    """
    result: dict[str, Any] = {"checked": False, "regressions": []}
    if gsc_module is None:
        result["reason"] = "google-api-python-client/google-auth not installed"
        return result

    end_recent = gsc_module.gsc_today() - timedelta(days=GSC_LAG_DAYS)
    start_recent = end_recent - timedelta(days=days)
    end_prior = start_recent - timedelta(days=1)
    start_prior = end_prior - timedelta(days=days)

    try:
        recent_rows, recent_capped = gsc_module.search_analytics_query_all(
            cfg, start_recent.isoformat(), end_recent.isoformat(),
            dimensions=["page"], max_rows=100_000,
        )
        prior_rows, prior_capped = gsc_module.search_analytics_query_all(
            cfg, start_prior.isoformat(), end_prior.isoformat(),
            dimensions=["page"], max_rows=100_000,
        )
    except Exception as exc:  # noqa: BLE001 — surface any GSC failure informatively, don't crash the cycle
        result["reason"] = f"GSC query failed: {exc}"
        return result

    recent = {r["keys"][0]: r for r in recent_rows if r.get("keys")}
    prior = {r["keys"][0]: r for r in prior_rows if r.get("keys")}

    capped = recent_capped or prior_capped
    compared_pages = set(prior) & set(recent) if capped else set(prior)
    if capped:
        result["note"] = (
            "A GSC window hit the row cap — only pages present in both windows "
            f"were compared ({len(compared_pages)} pages); "
            f"{len(set(prior) - compared_pages)} prior-window pages excluded."
        )

    regressions = []
    for page in compared_pages:
        prior_clicks = prior[page].get("clicks", 0)
        if prior_clicks < 10:
            continue  # too little volume for a percentage to mean anything
        recent_clicks = recent.get(page, {"clicks": 0}).get("clicks", 0)
        drop_abs = prior_clicks - recent_clicks
        drop_pct = drop_abs / prior_clicks if prior_clicks else 0
        if drop_pct >= 0.5 and drop_abs >= 5:
            regressions.append({
                "type": "gsc_clicks_drop",
                "severity": "high" if (drop_pct >= 0.75 and prior_clicks >= 30) else "medium",
                "url": page,
                "detail": (
                    f"Clicks dropped {drop_pct:.0%} ({prior_clicks} -> {recent_clicks}) "
                    f"over the last {days} days vs. the prior {days}-day window. "
                    "Could be seasonality, a SERP-feature change, or a real regression — "
                    "diagnose before acting."
                ),
                "dispatch_skill": "seo-rank-tracking",
                "human_review_required": True,
            })

    result["checked"] = True
    result["window_days"] = days
    result["recent_range"] = [start_recent.isoformat(), end_recent.isoformat()]
    result["prior_range"] = [start_prior.isoformat(), end_prior.isoformat()]
    result["row_cap_hit"] = capped
    result["regressions"] = regressions
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Run one seo-maintain continuous-maintenance cycle")
    parser.add_argument("--max-pages", type=int, default=500, help="max pages to crawl this cycle")
    parser.add_argument("--gsc-days", type=int, default=28, help="window size (days) for GSC click/impression comparison")
    parser.add_argument("--ignore-robots", action="store_true", help="only for your own localhost/staging builds")
    args = parser.parse_args()

    cfg = config_module.load()
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    checked: dict[str, Any] = {}
    not_checked: dict[str, str] = {}

    site_url = cfg.site_url  # raises MissingConfigError with a clear message if unset

    # 1. Fresh crawl into the shared snapshot store.
    current_snap = snapshots.new_crawl(
        cfg, "seo-maintain", max_pages=args.max_pages, ignore_robots=args.ignore_robots,
    )
    summary = current_snap.meta.get("crawl_summary", {})
    checked["crawl"] = {
        "snapshot": str(current_snap.path),
        "pages_crawled": current_snap.pages_crawled,
        "non_200_pages": summary.get("non_200", 0),
        "fetch_errors": summary.get("errors", 0),
        "robots_status": summary.get("robots_status", ""),
        "truncated": current_snap.truncated,
    }

    if summary.get("all_blocked"):
        # No pages could be crawled at all — say why, loudly, and stop.
        report = {
            "generated_at": now.isoformat(),
            "site_url": site_url,
            "cycle_date": today,
            "error": (
                "Crawl produced zero pages: robots.txt "
                f"({summary.get('robots_status')}) blocked everything"
                + (f" — {summary.get('robots_error')}" if summary.get("robots_error") else "")
                + ". Nothing was checked this cycle. If this is your own staging "
                "build that blocks all bots, re-run with --ignore-robots; if it is "
                "production, the site may be WAF-blocking this crawler's User-Agent."
            ),
            "regressions": [],
            "opportunities": [],
            "summary": {"checked": checked, "not_checked": {"everything": "crawl blocked"}},
        }
        report_path = cfg.reports_dir / f"maintenance-{today}.json"
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        report["_report_path"] = str(report_path)
        json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
        print()
        sys.exit(1)

    current = _index_by_key(current_snap)

    # 2. Regressions first — against a COMPARABLE baseline only.
    regressions: list[dict[str, Any]] = []
    baseline = snapshots.find_baseline(cfg, current_snap, require_comparable=True)
    if baseline.snapshot is not None:
        previous = _index_by_key(baseline.snapshot)
        regressions.extend(detect_regressions(
            previous, current,
            suppress_disappeared=current_snap.truncated or baseline.snapshot.truncated,
        ))
        checked["crawl"]["compared_against_previous"] = True
        checked["crawl"]["previous_snapshot"] = str(baseline.snapshot.path)
        if current_snap.truncated:
            not_checked["page_disappeared"] = (
                "Crawl hit the --max-pages cap — disappearance is indistinguishable "
                "from truncation; raise --max-pages to re-enable this check."
            )
    else:
        checked["crawl"]["compared_against_previous"] = False
        not_checked["crawl_diff_regressions"] = baseline.refusal_reason or "no baseline"

    # 3. GSC-based regression check (optional integration).
    integrations = cfg.available_integrations()
    if integrations.get("google_search_console"):
        gsc_result = check_gsc_regressions(cfg, args.gsc_days)
        checked["google_search_console"] = gsc_result
        if gsc_result.get("checked"):
            regressions.extend(gsc_result["regressions"])
        else:
            not_checked["google_search_console"] = gsc_result.get(
                "reason", "GSC configured but query failed for an unknown reason."
            )
    else:
        not_checked["google_search_console"] = (
            "Not configured — set GOOGLE_APPLICATION_CREDENTIALS or GSC_SERVICE_ACCOUNT_JSON "
            "to unlock click/impression regression detection on top pages (see api-reference.md)."
        )

    # Everything is merged now — sort ONCE so the report's ordering contract
    # (critical -> high -> medium -> low) holds across crawl + GSC findings.
    regressions.sort(key=lambda r: SEVERITY_ORDER.get(r["severity"], 9))

    # 4. Opportunities (ranked, from the fresh crawl).
    opportunities = detect_opportunities(current)

    # 5. Explicit coverage notes for everything this cycle did NOT check.
    not_checked["orphan_pages"] = (
        "Orphan detection requires a URL source independent of the link graph "
        "(sitemap/GSC) — dispatch seo-internal-linking, which owns that check."
    )
    if not integrations.get("pagespeed_insights"):
        not_checked["core_web_vitals"] = (
            "GOOGLE_PSI_API_KEY not set — seo-performance cannot be dispatched with fresh "
            "CWV field data this cycle. This cycle's crawl-based checks still ran."
        )
    if not integrations.get("firecrawl"):
        not_checked["js_rendering_diff"] = (
            "FIRECRAWL_API_KEY not set — cannot diff raw-HTML crawl against a rendered "
            "snapshot (red-flags.md §4). geo-optimize's check_js_visibility.py covers the "
            "free heuristic version of this check."
        )
    if not integrations.get("ahrefs") and not integrations.get("dataforseo"):
        not_checked["backlink_and_serp_data"] = (
            "Neither AHREFS_API_KEY nor DATAFORSEO_LOGIN/PASSWORD set — seo-backlinks and "
            "seo-rank-tracking have no independent-of-GSC data source this cycle."
        )

    report: dict[str, Any] = {
        "generated_at": now.isoformat(),
        "site_url": site_url,
        "cycle_date": today,
        "regressions": regressions,
        "opportunities": opportunities,
        "summary": {
            "regressions_found": len(regressions),
            "regressions_critical": sum(1 for r in regressions if r.get("severity") == "critical"),
            "opportunities_found": len(opportunities),
            "checked": checked,
            "not_checked": not_checked,
        },
    }

    report_path = cfg.reports_dir / f"maintenance-{today}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    report["_report_path"] = str(report_path)

    snapshots.prune(cfg)

    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
