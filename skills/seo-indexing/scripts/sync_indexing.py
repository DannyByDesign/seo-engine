"""seo-indexing: sitemap registration + GSC coverage checks + IndexNow submission.

Three independent jobs, each degrading gracefully if its integration isn't
configured:

1. Sitemap sync (requires Google Search Console): lists sitemaps already
   registered on the property via scripts.lib.gsc.list_sitemaps, and submits
   the site's sitemap via scripts.lib.gsc.submit_sitemap if it isn't already
   registered (or if --force-resubmit is passed).
2. URL Inspection sample (requires GSC): runs scripts.lib.gsc.inspect_url
   against a sample of "important pages" (explicit --url args, or the
   homepage plus GSC's own top-clicked pages) and reports index status,
   Google's *selected* canonical (which can diverge from the declared one --
   see references/seo-playbook.md section 5), and rich-results verdict.
3. IndexNow submission (requires INDEXNOW_API_KEY; Bing/Yandex/etc. only --
   Google and Baidu do NOT participate, per references/api-reference.md and
   references/red-flags.md section 4): submits a caller-supplied list of
   changed URLs via scripts.lib.indexnow.submit. This script does NOT try to
   auto-detect "changed" URLs itself -- that's better done by diffing two
   crawl snapshots (seo-technical-audit / seo-maintain already produce
   .seo-engine/state/crawl-*.jsonl for exactly this purpose). Feed this
   script the resulting URL list via --changed-url / --changed-urls-file.

Neither job requires the other to be configured -- each reports its own
"not configured" status rather than failing the whole run.

Usage:
    # Sitemap check/submit + URL Inspection sample only (no IndexNow)
    python3 sync_indexing.py --sitemap-url https://example.com/sitemap.xml

    # Also submit specific changed URLs to IndexNow (Bing/Yandex/etc.)
    python3 sync_indexing.py --sitemap-url https://example.com/sitemap.xml \\
        --changed-url https://example.com/blog/new-post \\
        --changed-url https://example.com/pricing

    # Feed changed URLs from a file (one URL per line) -- e.g. produced by
    # diffing content_hash between two crawl-*.jsonl snapshots
    python3 sync_indexing.py --changed-urls-file changed-urls.txt

    # Inspect specific important pages instead of auto-selecting a sample
    python3 sync_indexing.py --inspect-url https://example.com/ \\
        --inspect-url https://example.com/pricing

Output: structured JSON to stdout, also written to
.seo-engine/reports/indexing-sync-<timestamp>.json.
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
import time  # noqa: E402
from datetime import timedelta, datetime, timezone  # noqa: E402
from typing import Any, Optional  # noqa: E402
from urllib.parse import urlparse  # noqa: E402

from scripts.lib import gsc, http_util, indexnow, robots, sitemaps, snapshots, urlnorm  # noqa: E402
from scripts.lib.config import Config, MissingConfigError  # noqa: E402

# IndexNow participants per references/api-reference.md -- one key works
# across all of these. Google and Baidu explicitly do NOT participate; this
# script must never imply IndexNow submission does anything for Google.
INDEXNOW_PARTICIPANTS = [
    "Bing", "Yandex", "Naver", "Seznam.cz", "Yep", "Amazon", "Yahoo (via Bing's materials)",
]

INDEXNOW_DISCLAIMER = (
    "IndexNow does not guarantee indexing -- it only signals that a URL changed and may earn "
    "a prioritized (not immediate) crawl visit; the receiving engine still applies its own "
    "quality/crawl-quota gating. Submitted URLs count toward the site's own crawl quota, so "
    "don't over-submit (this script never auto-detects 'changed' URLs itself -- it only submits "
    "what the caller explicitly supplies). Google and Baidu do NOT participate in IndexNow at "
    "all -- for Google, rely exclusively on sitemaps + GSC URL Inspection, never IndexNow. "
    "See references/api-reference.md (IndexNow) and references/red-flags.md section 4."
)


def _feedpath_from_sitemap_url(sitemap_url: str) -> str:
    """GSC's sitemaps API takes a feedpath relative to nothing -- in practice
    the full sitemap URL is accepted as the feedpath by the searchconsole v1
    API. Pass the URL through unchanged; this helper exists so the intent is
    documented at the call site."""
    return sitemap_url


def sync_sitemap(cfg: Config, site_url: str, sitemap_url: Optional[str], force_resubmit: bool) -> dict[str, Any]:
    integrations = cfg.available_integrations()
    if not integrations.get("google_search_console"):
        return {
            "checked": False,
            "reason": (
                "GOOGLE_APPLICATION_CREDENTIALS / GSC_SERVICE_ACCOUNT_JSON not set -- sitemap "
                "registration status can't be read or written without Search Console access. "
                "See references/api-reference.md's Google Search Console API section for the "
                "service-account setup (no interactive OAuth consent needed once configured)."
            ),
        }

    discovered_note = None
    if not sitemap_url:
        # Auto-discover: robots.txt Sitemap: declarations, then the standard
        # default paths (sitemap.xml / sitemap_index.xml / wp-sitemap.xml).
        policy = robots.fetch(site_url)
        found = sitemaps.fetch_url_set(site_url, policy)
        if found["found"] and found["sitemaps_read"]:
            sitemap_url = found["sitemaps_read"][0]
            discovered_note = (
                f"No --sitemap-url given; auto-discovered {sitemap_url} "
                f"({len(found['page_urls'])} URLs listed)."
            )
        else:
            return {
                "checked": False,
                "reason": (
                    "No --sitemap-url was given and none could be auto-discovered (checked "
                    "robots.txt Sitemap: declarations, /sitemap.xml, /sitemap_index.xml, "
                    "/wp-sitemap.xml). If the site has a sitemap at a custom path, pass "
                    "--sitemap-url explicitly; if it has none, generate one first."
                ),
            }

    try:
        existing = gsc.list_sitemaps(cfg)
    except MissingConfigError as exc:
        return {"checked": False, "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 -- report, don't crash the whole sync
        return {"checked": False, "reason": f"GSC sitemaps.list failed: {http_util.sanitize_text(str(exc))}"}

    registered_paths = [s.get("path", "") for s in existing.get("sitemap", [])]
    already_registered = sitemap_url in registered_paths

    result: dict[str, Any] = {
        "checked": True,
        "sitemap_url": sitemap_url,
        "already_registered": already_registered,
        "all_registered_sitemaps": registered_paths,
        "submitted_this_run": False,
    }
    if discovered_note:
        result["discovery_note"] = discovered_note

    if already_registered and not force_resubmit:
        result["notes"] = (
            "Sitemap already registered on this property -- no resubmission needed. "
            "Pass --force-resubmit to re-submit anyway (harmless, but rarely necessary; "
            "GSC recrawls a registered sitemap on its own schedule)."
        )
        return result

    try:
        gsc.submit_sitemap(cfg, sitemap_url)
        result["submitted_this_run"] = True
        result["notes"] = (
            "Sitemap submitted via sitemaps.submit. This registers/re-registers it with "
            "Search Console -- it does not itself guarantee or expedite indexing of the URLs "
            "inside it; use the URL Inspection sample below (or GSC's Coverage report) to check "
            "actual index status."
        )
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"sitemaps.submit failed: {http_util.sanitize_text(str(exc))}"

    return result


def _select_inspect_urls(
    cfg: Config, site_url: str, explicit_urls: list[str], max_urls: int
) -> tuple[list[str], list[str]]:
    """Homepage + explicit --inspect-url args + (if GSC configured) top-clicked
    pages from the last 28 days, capped at max_urls. Returns (urls, notes)."""
    notes: list[str] = []
    urls: list[str] = []
    seen: set[str] = set()

    for u in [site_url, *explicit_urls]:
        if u and u not in seen:
            urls.append(u)
            seen.add(u)

    if len(urls) < max_urls:
        integrations = cfg.available_integrations()
        if integrations.get("google_search_console"):
            try:
                end = gsc.gsc_today() - timedelta(days=3)
                start = end - timedelta(days=28)
                result = gsc.search_analytics_query(
                    cfg, start.isoformat(), end.isoformat(),
                    dimensions=["page"], row_limit=max_urls,
                )
                added = 0
                for row in result.get("rows", []):
                    page_url = row.get("keys", [None])[0]
                    if page_url and page_url not in seen and len(urls) < max_urls:
                        urls.append(page_url)
                        seen.add(page_url)
                        added += 1
                notes.append(f"Added {added} top-clicked page(s) from GSC (last 28 days) to the inspection sample.")
            except MissingConfigError as exc:
                notes.append(f"GSC configured but credentials incomplete: {exc}")
            except Exception as exc:  # noqa: BLE001
                notes.append("GSC top-page query failed, continuing with homepage/explicit "
                             f"URLs only: {http_util.sanitize_text(str(exc))}")
        else:
            notes.append(
                "GOOGLE_APPLICATION_CREDENTIALS / GSC_SERVICE_ACCOUNT_JSON not set -- inspection "
                "sample limited to the homepage and any explicit --inspect-url args. Set one of "
                "these to auto-include real top-clicked pages."
            )

    return urls[:max_urls], notes


def inspect_sample(cfg: Config, site_url: str, explicit_urls: list[str], max_urls: int) -> dict[str, Any]:
    integrations = cfg.available_integrations()
    if not integrations.get("google_search_console"):
        return {
            "checked": False,
            "reason": (
                "GOOGLE_APPLICATION_CREDENTIALS / GSC_SERVICE_ACCOUNT_JSON not set -- URL "
                "Inspection (index status, Google's selected canonical, rich-results verdict) "
                "requires Search Console access. See references/api-reference.md's Google Search "
                "Console API section."
            ),
        }

    urls, discovery_notes = _select_inspect_urls(cfg, site_url, explicit_urls, max_urls)

    pages: list[dict[str, Any]] = []
    for url in urls:
        try:
            raw = gsc.inspect_url(cfg, url)
        except MissingConfigError as exc:
            pages.append({"url": url, "error": str(exc)})
            continue
        except Exception as exc:  # noqa: BLE001 -- one bad URL must not kill the batch
            pages.append({"url": url, "error": "urlInspection.index.inspect failed: "
                          + http_util.sanitize_text(str(exc))})
            continue

        result_data = raw.get("inspectionResult", {}) or {}
        index_status = result_data.get("indexStatusResult", {}) or {}
        rich_results = result_data.get("richResultsResult", {}) or {}

        declared_canonical = index_status.get("userCanonical", "")
        selected_canonical = index_status.get("googleCanonical", "")
        canonical_mismatch = bool(
            declared_canonical and selected_canonical and declared_canonical != selected_canonical
        )

        entry = {
            "url": url,
            "verdict": index_status.get("verdict"),
            "coverage_state": index_status.get("coverageState"),
            "indexing_state": index_status.get("indexingState"),
            "robots_txt_state": index_status.get("robotsTxtState"),
            "page_fetch_state": index_status.get("pageFetchState"),
            "declared_canonical": declared_canonical,
            "google_selected_canonical": selected_canonical,
            "canonical_mismatch": canonical_mismatch,
            "last_crawl_time": index_status.get("lastCrawlTime"),
            "rich_results_verdict": rich_results.get("verdict"),
            "rich_results_detected_items": [
                item.get("richResultType") for item in rich_results.get("detectedItems", [])
            ],
        }
        if canonical_mismatch:
            entry["review_note"] = (
                "Google selected a different canonical than the one declared in <link "
                "rel=canonical>. Per references/seo-playbook.md section 5 this is a legitimate "
                "automated integrity check, not paranoia -- if the selected canonical points "
                "off-domain, treat it as a potential cross-domain canonical hijack (security "
                "incident, escalate per references/red-flags.md section 4) rather than auto-fixing."
            )
        pages.append(entry)

    not_indexed = [p for p in pages if "error" not in p and p.get("coverage_state") and "Submitted and indexed" not in (p.get("coverage_state") or "") and (p.get("verdict") or "").upper() != "PASS"]
    canonical_mismatches = [p for p in pages if p.get("canonical_mismatch")]

    return {
        "checked": True,
        "discovery_notes": discovery_notes,
        "pages_inspected": len(pages),
        "pages_not_indexed_or_flagged": len(not_indexed),
        "pages_with_canonical_mismatch": len(canonical_mismatches),
        "pages": pages,
    }


def submit_to_indexnow(cfg: Config, changed_urls: list[str], key_location: Optional[str]) -> dict[str, Any]:
    integrations = cfg.available_integrations()
    if not integrations.get("indexnow"):
        return {
            "checked": False,
            "reason": (
                "INDEXNOW_API_KEY not set -- no submission attempted. Run "
                "skills/seo-indexing/scripts/setup_indexnow_key.py <public-dir> to generate a key "
                "and scaffold the verification file, then set INDEXNOW_API_KEY."
            ),
            "disclaimer": INDEXNOW_DISCLAIMER,
        }

    if not changed_urls:
        return {
            "checked": True,
            "submitted": False,
            "reason": (
                "INDEXNOW_API_KEY is set, but no changed URLs were supplied. Pass them "
                "explicitly (--changed-url / --changed-urls-file), or use "
                "--changed-from-snapshots to derive them from the snapshot store's "
                "content_hash diff (latest crawl vs. its comparable baseline)."
            ),
            "disclaimer": INDEXNOW_DISCLAIMER,
        }

    try:
        status = indexnow.submit(cfg, changed_urls, key_location=key_location)
    except MissingConfigError as exc:
        return {"checked": True, "submitted": False, "error": str(exc), "disclaimer": INDEXNOW_DISCLAIMER}
    except ValueError as exc:
        # Mixed-host / off-site URLs — refused before any network call.
        return {"checked": True, "submitted": False, "error": str(exc), "disclaimer": INDEXNOW_DISCLAIMER}
    except Exception as exc:  # noqa: BLE001
        return {"checked": True, "submitted": False,
                "error": "IndexNow submit failed: " + http_util.sanitize_text(str(exc)),
                "disclaimer": INDEXNOW_DISCLAIMER}

    accepted = status in (200, 202)
    return {
        "checked": True,
        "submitted": True,
        "http_status": status,
        "accepted": accepted,
        "url_count": len(changed_urls),
        "participants": INDEXNOW_PARTICIPANTS,
        "urls": changed_urls,
        "notes": (
            "IndexNow does not return per-URL confirmation -- a 200/202 means the batch was "
            "accepted for processing, not that any specific URL has been (re)crawled or indexed."
            if accepted else
            f"Non-2xx-equivalent status ({status}) -- verify the key file is reachable at "
            f"https://{urlparse(changed_urls[0]).netloc}/{{key}}.txt and that all URLs share the "
            f"same host as the key."
        ),
        "disclaimer": INDEXNOW_DISCLAIMER,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync sitemap registration + GSC coverage sample + IndexNow submission "
                    "(Bing/Yandex/etc. only -- Google does not participate in IndexNow)."
    )
    parser.add_argument("--sitemap-url", default=None,
                        help="Full sitemap URL to confirm/submit registration for, e.g. "
                             "https://example.com/sitemap.xml. Required to actually sync (vs. "
                             "just list) sitemaps.")
    parser.add_argument("--force-resubmit", action="store_true",
                        help="Resubmit the sitemap even if already registered.")
    parser.add_argument("--no-sitemap-sync", action="store_true",
                        help="Skip the sitemap registration check/submit entirely.")
    parser.add_argument("--inspect-url", action="append", default=[],
                        help="Specific important URL to run URL Inspection against; repeatable. "
                             "Combined with the homepage and (if GSC configured) top-clicked pages.")
    parser.add_argument("--max-inspect", type=int, default=10,
                        help="Max URLs to run URL Inspection against in one run (rate-limit "
                             "friendly default; GSC's own quota is 600 QPM / 2,000 QPD per site).")
    parser.add_argument("--no-inspect", action="store_true",
                        help="Skip the URL Inspection sample entirely.")
    parser.add_argument("--changed-url", action="append", default=[], dest="changed_urls",
                        help="A URL that changed/was added/was deleted, to submit via IndexNow; "
                             "repeatable. Supply these yourself (e.g. from a crawl-snapshot diff) "
                             "-- this script does not auto-detect changes.")
    parser.add_argument("--changed-urls-file", default=None,
                        help="Path to a file with one changed URL per line, merged with any "
                             "--changed-url args.")
    parser.add_argument("--changed-from-snapshots", action="store_true",
                        help="Derive changed URLs from the snapshot store: pages whose "
                             "content_hash differs between the latest crawl and its comparable "
                             "baseline (refuses when no comparable baseline exists — never "
                             "guesses). Merged with any explicit --changed-url args.")
    parser.add_argument("--indexnow-key-location", default=None,
                        help="Override the key-file location if it's not at the default "
                             "https://{host}/{key}.txt (e.g. served from a non-root path). "
                             "Passed through as IndexNow's keyLocation field.")
    args = parser.parse_args()

    cfg = config_module.load()
    site_url = cfg.site_url

    changed_urls = list(args.changed_urls)
    snapshot_diff_note: Optional[str] = None
    if args.changed_urls_file:
        file_path = Path(args.changed_urls_file)
        if file_path.is_file():
            for line in file_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    changed_urls.append(line)
        else:
            print(f"Warning: --changed-urls-file {file_path} not found, ignoring.", file=sys.stderr)

    if args.changed_from_snapshots:
        current = snapshots.latest(cfg, max_age_hours=48)
        if current is None:
            snapshot_diff_note = (
                "--changed-from-snapshots: no crawl snapshot newer than 48h exists — run "
                "seo-maintain (or any crawling skill) first, then re-run this."
            )
        else:
            baseline = snapshots.find_baseline(cfg, current, require_comparable=True)
            if baseline.snapshot is None:
                snapshot_diff_note = (
                    f"--changed-from-snapshots refused: {baseline.refusal_reason}"
                )
            else:
                prev_hashes = {
                    urlnorm.canonical_key(r.get("url", "")): r.get("content_hash", "")
                    for r in baseline.snapshot.pages() if r.get("status") == 200
                }
                derived = []
                for rec in current.pages():
                    if rec.get("status") != 200 or rec.get("error"):
                        continue
                    key = urlnorm.canonical_key(rec.get("url", ""))
                    prev = prev_hashes.get(key)
                    if prev is not None and prev != rec.get("content_hash", ""):
                        derived.append(rec.get("url", ""))
                snapshot_diff_note = (
                    f"--changed-from-snapshots: {len(derived)} page(s) with changed "
                    f"content_hash between {baseline.snapshot.path.name} and "
                    f"{current.path.name}."
                )
                changed_urls.extend(derived)

    changed_urls = list(dict.fromkeys(changed_urls))  # de-dup, preserve order

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "site_url": site_url,
        "scope_note": (
            "Sitemap submission and URL Inspection apply to Google (via Search Console) and are "
            "the only supported mechanism for Google indexing signals in this script. IndexNow "
            "submission below is entirely separate and does NOT reach Google -- see the "
            "indexnow.disclaimer field."
        ),
        "sitemap": {"checked": False, "reason": "Skipped (--no-sitemap-sync)."} if args.no_sitemap_sync
                   else sync_sitemap(cfg, site_url, args.sitemap_url, args.force_resubmit),
        "url_inspection": {"checked": False, "reason": "Skipped (--no-inspect)."} if args.no_inspect
                   else inspect_sample(cfg, site_url, args.inspect_url, args.max_inspect),
        "indexnow": submit_to_indexnow(cfg, changed_urls, args.indexnow_key_location),
    }
    if snapshot_diff_note:
        report["indexnow"]["snapshot_diff_note"] = snapshot_diff_note

    reports_dir = cfg.reports_dir
    ts = time.strftime("%Y%m%d-%H%M%S")
    report_path = reports_dir / f"indexing-sync-{ts}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report_file"] = str(report_path)

    snapshots.prune(cfg)

    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
