"""Opportunity mining: find realistic, valuable keyword/topic gaps by combining
Google Search Console's own performance data with paid keyword-volume/difficulty
context from Ahrefs or DataForSEO (either optional).

Core idea (see references/seo-playbook.md section 1, "people-first" principle,
and this skill's own SKILL.md "How to interpret results"): a query where the
site already has real impressions but a position outside the top 10, or a CTR
notably below what that position would typically expect, is a "near-miss" --
Google's own systems already consider the page topically relevant enough to
surface it. Improving that page's genuine usefulness for that query is a much
more realistic path to a ranking gain than starting a new page/topic from zero.

This script NEVER recommends publishing a new page purely to "cover" a query,
and never suggests keyword-density/stuffing tactics -- see red-flags.md section
1 (scaled content abuse) and section 6 (the meta-rule). It surfaces WHERE an
existing page could be made more genuinely useful; the calling agent decides
HOW, and should route "how" through geo-playbook.md section 5 (citations,
direct quotations, and concrete statistics are the one evidence-backed
content-improvement tactic found in the research this system is built on).

Pipeline:
  1. GSC search_analytics_query_all(dimensions=["query","page"]) over a recent
     window (default: last 90 days ending 3 days before gsc_today() -- GSC
     buckets data in America/Los_Angeles days and reports with a ~3-day lag).
     Rows are fetched with startRow pagination up to --row-limit; if that cap
     is hit, the sample is truncated and the report says so. --country/
     --device are applied by adding the country/device dimension and
     filtering client-side (equivalent granularity to a server-side filter).
  2. Flag "near-miss" rows: impressions >= --min-impressions AND
     (position > 10 OR ctr is notably below the expected CTR for that
     position band, using a widely-replicated organic CTR-by-position curve
     as a rough expectation, not a precise model of any single SERP).
  3. For the flagged (query) set, attach real search-volume/difficulty
     context: DataForSEO search_volume() if configured (preferred -- no
     subscription-tier gate, cheaper per api-reference.md), else Ahrefs
     keywords_overview() if configured, else none (flagged purely on GSC
     signal, clearly labeled as such).
  4. Score and rank by realistic upside (impressions x row-level "headroom"),
     not by raw search volume alone -- a page already getting real impressions
     for a query is a stronger, cheaper signal than a keyword's total search
     volume, which this script treats as prioritization context, not the
     primary signal.

Usage:
    python3 find_opportunities.py                       # last 90 days, GSC only or with paid context if configured
    python3 find_opportunities.py --days 28
    python3 find_opportunities.py --min-impressions 25 --min-position 8
    python3 find_opportunities.py --max-queries 50 --no-keyword-data
    python3 find_opportunities.py --country usa --device MOBILE

Output: structured JSON to stdout; also written to
.seo-engine/reports/keyword-opportunities-<timestamp>.json. Each run appends
the run's FLAGGED opportunities (only those) to
.seo-engine/state/keyword-opportunities-history.json, keyed by
query::primary_page and capped at the last 52 entries per key -- so trend is
visible for queries that keep getting flagged across runs. A key absent from
a run means "not flagged that run" (below thresholds, or improved), never
"zero traffic".
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

from scripts.lib import gsc, http_util, snapshots  # noqa: E402
from scripts.lib.config import Config, MissingConfigError  # noqa: E402

# A widely-replicated organic CTR-by-position curve (multiple independent
# industry CTR studies broadly agree on the shape: steep drop-off from #1,
# long shallow tail past #10). This is a rough band-based *expectation*, not a
# claim about any specific SERP -- it exists only to catch rows where CTR is
# unusually low for the position already achieved (e.g. a irrelevant/weak
# title or snippet undercutting a position that should otherwise earn clicks),
# distinct from rows that are simply ranking outside the top 10 entirely.
EXPECTED_CTR_BY_POSITION_BAND = [
    (1, 2, 0.25),
    (2, 3, 0.15),
    (3, 5, 0.10),
    (5, 8, 0.06),
    (8, 11, 0.035),
    (11, 20, 0.015),
    (20, 9999, 0.005),
]


def _expected_ctr(position: float) -> float:
    for lo, hi, expected in EXPECTED_CTR_BY_POSITION_BAND:
        if lo <= position < hi:
            return expected
    return EXPECTED_CTR_BY_POSITION_BAND[-1][2]


def _fetch_gsc_rows(
    cfg: Config, days: int, max_rows: int, country: Optional[str], device: Optional[str],
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Returns (rows, notes, hit_cap). Each row: {query, page, clicks,
    impressions, ctr, position}.

    Fetches ALL rows via startRow pagination (up to max_rows). --country/
    --device are handled by adding those dimensions and filtering client-side:
    a row segmented to one country/device carries the same metrics a
    server-side dimensionFilterGroups filter would return for it."""
    notes: list[str] = []
    end = gsc.gsc_today() - timedelta(days=3)  # GSC data has a reporting lag of ~2-3 days
    start = end - timedelta(days=days)

    dimensions = ["query", "page"]
    if country:
        dimensions.append("country")
    if device:
        dimensions.append("device")
    country_idx = dimensions.index("country") if country else -1
    device_idx = dimensions.index("device") if device else -1

    rows, hit_cap = gsc.search_analytics_query_all(
        cfg, start.isoformat(), end.isoformat(),
        dimensions=dimensions, max_rows=max_rows,
    )

    rows_out = []
    for row in rows:
        keys = row.get("keys", [])
        if len(keys) < len(dimensions):
            continue
        if country and str(keys[country_idx]).lower() != country.lower():
            continue
        if device and str(keys[device_idx]).upper() != device.upper():
            continue
        rows_out.append({
            "query": keys[0],
            "page": keys[1],
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr": row.get("ctr", 0.0),
            "position": row.get("position", 0.0),
        })

    filter_note = ""
    if country or device:
        filter_note = (
            f" after client-side country/device filtering (fetched {len(rows)} "
            "segmented rows)"
        )
    notes.append(
        f"GSC window: {start.isoformat()} to {end.isoformat()} "
        f"({days} days, 3-day reporting lag applied, dates in GSC's "
        f"America/Los_Angeles reporting timezone), {len(rows_out)} query+page rows"
        f"{filter_note} (paginated fetch, --row-limit {max_rows})."
    )
    if hit_cap:
        notes.append(
            f"GSC returned more rows than the --row-limit cap ({max_rows}) -- the "
            "sample is TRUNCATED: queries absent from this report may simply not "
            "have been fetched. Raise --row-limit for full coverage."
        )
    return rows_out, notes, hit_cap


def _flag_near_misses(
    rows: list[dict[str, Any]], min_impressions: int, min_position_for_flag: float, ctr_ratio_threshold: float,
) -> list[dict[str, Any]]:
    """A row is a 'near-miss opportunity' if it already gets meaningful
    impressions AND either:
      (a) ranks outside the top 10 (position > min_position_for_flag), or
      (b) ranks in/near the top 10 but CTR is well below what that position
          band would typically expect (ctr < expected_ctr * ctr_ratio_threshold)
          -- a sign the snippet/title isn't earning the clicks the position
          could otherwise support, independent of the deeper content question.
    """
    flagged = []
    for row in rows:
        if row["impressions"] < min_impressions:
            continue
        position = row["position"]
        expected_ctr = _expected_ctr(position)
        ctr_gap_ratio = (row["ctr"] / expected_ctr) if expected_ctr else 1.0

        reason = None
        if position > min_position_for_flag:
            reason = "ranks_outside_target_position"
        elif ctr_gap_ratio < ctr_ratio_threshold:
            reason = "ctr_below_position_expectation"

        if reason:
            row_out = dict(row)
            row_out["expected_ctr_for_position"] = round(expected_ctr, 4)
            row_out["ctr_vs_expected_ratio"] = round(ctr_gap_ratio, 2)
            row_out["flag_reason"] = reason
            # Headroom: rough "clicks left on the table" if this row reached
            # its position band's expected CTR (or, for out-of-target-position
            # rows, if it reached the #5-8 band's expected CTR as a
            # conservative "made the first page properly" reference point).
            reference_ctr = expected_ctr if reason == "ctr_below_position_expectation" else EXPECTED_CTR_BY_POSITION_BAND[3][2]
            headroom_clicks = max(0.0, row["impressions"] * reference_ctr - row["clicks"])
            row_out["estimated_headroom_clicks"] = round(headroom_clicks, 1)
            flagged.append(row_out)
    return flagged


def _aggregate_by_query(flagged_rows: list[dict[str, Any]], max_queries: int) -> list[dict[str, Any]]:
    """Multiple pages can rank for the same query; group so the agent sees one
    opportunity per query with its best-performing page as the primary
    remediation target, ranked by total estimated headroom."""
    by_query: dict[str, dict[str, Any]] = {}
    for row in flagged_rows:
        q = row["query"]
        entry = by_query.setdefault(q, {
            "query": q,
            "pages": [],
            "total_impressions": 0,
            "total_clicks": 0,
            "total_estimated_headroom_clicks": 0.0,
            "best_position": None,
        })
        entry["pages"].append({
            "page": row["page"],
            "impressions": row["impressions"],
            "clicks": row["clicks"],
            "ctr": row["ctr"],
            "position": row["position"],
            "expected_ctr_for_position": row["expected_ctr_for_position"],
            "ctr_vs_expected_ratio": row["ctr_vs_expected_ratio"],
            "flag_reason": row["flag_reason"],
            "estimated_headroom_clicks": row["estimated_headroom_clicks"],
        })
        entry["total_impressions"] += row["impressions"]
        entry["total_clicks"] += row["clicks"]
        entry["total_estimated_headroom_clicks"] += row["estimated_headroom_clicks"]
        if entry["best_position"] is None or row["position"] < entry["best_position"]:
            entry["best_position"] = row["position"]

    aggregated = list(by_query.values())
    for entry in aggregated:
        entry["pages"].sort(key=lambda p: -p["estimated_headroom_clicks"])
        entry["primary_page"] = entry["pages"][0]["page"] if entry["pages"] else None
        entry["total_estimated_headroom_clicks"] = round(entry["total_estimated_headroom_clicks"], 1)
    aggregated.sort(key=lambda e: -e["total_estimated_headroom_clicks"])
    return aggregated[:max_queries]


def _attach_ahrefs_context(cfg: Config, queries: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    from scripts.lib import ahrefs

    notes: list[str] = []
    context: dict[str, dict[str, Any]] = {}
    batch_size = 100  # keep well under any single-request row/unit ceiling
    try:
        for i in range(0, len(queries), batch_size):
            batch = queries[i:i + batch_size]
            result = ahrefs.keywords_overview(cfg, batch)
            # Row fields track ahrefs.keywords_overview's select list exactly:
            # keyword, volume, keyword_difficulty, cpc. (The renamed Ahrefs v3
            # fields best_position/sum_traffic/best_position_url belong to
            # organic_keywords, which this script does not call.)
            for item in result.get("keywords", result.get("data", [])) or []:
                kw = item.get("keyword")
                if kw:
                    context[kw] = {
                        "volume": item.get("volume"),
                        "keyword_difficulty": item.get("keyword_difficulty"),
                        "cpc": item.get("cpc"),
                        "source": "ahrefs",
                    }
        notes.append(f"Attached Ahrefs keyword-volume/difficulty context for {len(context)} of {len(queries)} queries.")
    except MissingConfigError as exc:
        notes.append(f"Ahrefs configured but credentials incomplete: {exc}")
    except Exception as exc:  # noqa: BLE001 -- keyword context is an enhancement, not a hard dependency
        notes.append(
            "Ahrefs keywords_overview() call failed, continuing without it: "
            f"{http_util.sanitize_text(str(exc))}"
        )
    return context, notes


def _attach_dataforseo_context(cfg: Config, queries: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    from scripts.lib import dataforseo

    notes: list[str] = []
    context: dict[str, dict[str, Any]] = {}
    batch_size = 1000  # DataForSEO search_volume max per request
    try:
        for i in range(0, len(queries), batch_size):
            batch = queries[i:i + batch_size]
            result = dataforseo.search_volume(cfg, batch)
            for task in result.get("tasks", []) or []:
                for item in (task.get("result") or []):
                    kw = item.get("keyword")
                    if kw:
                        context[kw] = {
                            "volume": item.get("search_volume"),
                            "cpc": item.get("cpc"),
                            "competition": item.get("competition"),
                            "source": "dataforseo",
                        }
        notes.append(f"Attached DataForSEO search-volume context for {len(context)} of {len(queries)} queries.")
    except MissingConfigError as exc:
        notes.append(f"DataForSEO configured but credentials incomplete: {exc}")
    except dataforseo.DataForSeoError as exc:
        # The client raises this for application-level failures DataForSEO
        # hides inside HTTP 200 (auth/task errors) -- degrade, never crash.
        notes.append(
            "DataForSEO reported an application-level error, continuing without "
            f"keyword context: {http_util.sanitize_text(str(exc))}"
        )
    except Exception as exc:  # noqa: BLE001 -- keyword context is an enhancement, not a hard dependency
        notes.append(
            "DataForSEO search_volume() call failed, continuing without it: "
            f"{http_util.sanitize_text(str(exc))}"
        )
    return context, notes


def _load_history(cfg: Config) -> dict[str, Any]:
    path = cfg.state_dir / "keyword-opportunities-history.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_history(cfg: Config, history: dict[str, Any]) -> Path:
    path = cfg.state_dir / "keyword-opportunities-history.json"
    path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mine GSC near-miss keyword opportunities (real impressions, "
                    "weak position/CTR) and attach paid volume/difficulty context "
                    "from DataForSEO (preferred) or Ahrefs when configured."
    )
    parser.add_argument("--days", type=int, default=90,
                        help="GSC lookback window in days (default 90).")
    parser.add_argument("--min-impressions", type=int, default=10,
                        help="Minimum impressions for a query+page row to be considered (default 10). "
                             "Below this, GSC's own position/CTR figures are too noisy to act on.")
    parser.add_argument("--min-position", dest="min_position", type=float, default=10.0,
                        help="Position threshold beyond which a row is flagged as 'outside target "
                             "position' regardless of CTR (default 10.0, i.e. outside page 1).")
    parser.add_argument("--ctr-ratio-threshold", type=float, default=0.6,
                        help="Flag a row already at/near top 10 if its CTR is below this fraction "
                             "of the expected CTR for its position band (default 0.6).")
    parser.add_argument("--row-limit", type=int, default=100_000,
                        help="Max total query+page rows to fetch from GSC across paginated "
                             "requests (default 100000). If the cap is hit, the sample is "
                             "truncated and the report says so.")
    parser.add_argument("--max-queries", type=int, default=100,
                        help="Max distinct queries to include in the final ranked output (default 100).")
    parser.add_argument("--country", default=None,
                        help="Optional GSC country filter, ISO 3166-1 alpha-3 (e.g. 'usa').")
    parser.add_argument("--device", default=None, choices=["DESKTOP", "MOBILE", "TABLET"],
                        help="Optional GSC device filter.")
    parser.add_argument("--no-keyword-data", action="store_true",
                        help="Skip the Ahrefs/DataForSEO enrichment step even if configured "
                             "(GSC-only, faster, no paid-API cost).")
    parser.add_argument("--prefer-ahrefs", action="store_true",
                        help="Use Ahrefs instead of DataForSEO when both are configured "
                             "(default prefers DataForSEO per references/api-reference.md: "
                             "no subscription-tier gate, cheaper per call).")
    args = parser.parse_args()

    cfg = config_module.load()
    integrations = cfg.available_integrations()
    setup_notes: list[str] = []

    if not integrations.get("google_search_console"):
        result = {
            "error": "Google Search Console is not configured -- this skill has no meaningful "
                     "signal without it.",
            "remediation": (
                "Set GOOGLE_APPLICATION_CREDENTIALS (path to a service-account JSON) or "
                "GSC_SERVICE_ACCOUNT_JSON (inline JSON), and add that service account's "
                "client_email as a verified Owner/User on the property in Search Console "
                "(Settings > Users and permissions). See references/api-reference.md, "
                "Google Search Console API section."
            ),
        }
        json.dump(result, sys.stdout, indent=2)
        print()
        sys.exit(1)

    snapshots.prune(cfg)  # retention housekeeping -- state must not grow unbounded

    try:
        rows, gsc_notes, gsc_hit_cap = _fetch_gsc_rows(
            cfg, args.days, args.row_limit, args.country, args.device,
        )
    except MissingConfigError as exc:
        json.dump({"error": str(exc)}, sys.stdout, indent=2)
        print()
        sys.exit(1)
    except gsc.GscPropertyError as exc:
        # resolve_property() found no matching GSC property -- the exception
        # message already lists the visible properties and remediation.
        json.dump({"error": str(exc)}, sys.stdout, indent=2)
        print()
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001 -- GSC is a hard dependency; fail with clean JSON
        json.dump({
            "error": "GSC query failed: " + http_util.sanitize_text(str(exc)),
            "remediation": (
                "Check the service-account credentials and the property access "
                "(see references/api-reference.md, Google Search Console API section)."
            ),
        }, sys.stdout, indent=2)
        print()
        sys.exit(1)
    setup_notes.extend(gsc_notes)

    flagged_rows = _flag_near_misses(
        rows, args.min_impressions, args.min_position, args.ctr_ratio_threshold,
    )
    opportunities = _aggregate_by_query(flagged_rows, args.max_queries)

    keyword_context: dict[str, dict[str, Any]] = {}
    if not args.no_keyword_data:
        queries = [o["query"] for o in opportunities]
        if not queries:
            setup_notes.append("No near-miss queries found -- skipping keyword-volume enrichment.")
        elif integrations.get("dataforseo") and not (args.prefer_ahrefs and integrations.get("ahrefs")):
            keyword_context, kw_notes = _attach_dataforseo_context(cfg, queries)
            setup_notes.extend(kw_notes)
        elif integrations.get("ahrefs"):
            keyword_context, kw_notes = _attach_ahrefs_context(cfg, queries)
            setup_notes.extend(kw_notes)
        else:
            setup_notes.append(
                "Neither DATAFORSEO_LOGIN/DATAFORSEO_PASSWORD nor AHREFS_API_KEY is set -- "
                "opportunities below are flagged on GSC signal alone (impressions/position/CTR), "
                "with no real search-volume or keyword-difficulty context to prioritize by. "
                "DataForSEO is recommended first (no subscription-tier gate, pay-as-you-go, "
                "cheaper per api-reference.md) -- set DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD. "
                "Ahrefs is also supported -- set AHREFS_API_KEY (requires at least the Lite plan)."
            )
    else:
        setup_notes.append("--no-keyword-data passed -- skipped Ahrefs/DataForSEO enrichment.")

    for opp in opportunities:
        ctx = keyword_context.get(opp["query"])
        opp["keyword_context"] = ctx  # None if not available/not looked up

    # Sort again with keyword context folded in: prioritize by a simple
    # composite of realistic upside (headroom, from GSC's own signal -- the
    # primary driver) and search volume (secondary tie-breaker context only,
    # never the primary driver, per this skill's SKILL.md).
    def _priority_key(opp: dict[str, Any]) -> tuple[float, float]:
        headroom = opp["total_estimated_headroom_clicks"]
        volume = 0
        if opp.get("keyword_context") and opp["keyword_context"].get("volume"):
            volume = opp["keyword_context"]["volume"]
        return (-headroom, -(volume or 0))

    opportunities.sort(key=_priority_key)

    history = _load_history(cfg)
    now_iso = datetime.now(timezone.utc).isoformat()
    for opp in opportunities:
        key = f"{opp['query']}::{opp['primary_page']}"
        history.setdefault(key, [])
        history[key].append({
            "fetched_at": now_iso,
            "total_impressions": opp["total_impressions"],
            "total_clicks": opp["total_clicks"],
            "best_position": opp["best_position"],
            "total_estimated_headroom_clicks": opp["total_estimated_headroom_clicks"],
        })
        history[key] = history[key][-52:]  # cap ~1yr of weekly runs per query+page
    history_path = _save_history(cfg, history)

    report = {
        "generated_at": now_iso,
        "site_url": cfg.site_url,
        "lookback_days": args.days,
        "thresholds": {
            "min_impressions": args.min_impressions,
            "min_position_for_outside_target_flag": args.min_position,
            "ctr_ratio_threshold_for_underperforming_position": args.ctr_ratio_threshold,
        },
        "methodology_note": (
            "Opportunities are query+page rows where GSC already shows real impressions "
            "but either the position is outside the target band or CTR is notably below "
            "what that position typically earns (see EXPECTED_CTR_BY_POSITION_BAND -- a "
            "rough, widely-replicated industry curve, not a precise per-SERP model). This "
            "is the cheapest, most realistic class of opportunity because Google's own "
            "systems already consider the page relevant enough to surface for the query -- "
            "refining that page is a faster path to a ranking gain than starting a new "
            "topic from zero. Search-volume/difficulty context (when available) is "
            "prioritization context only, never the primary signal, and this script never "
            "recommends creating a new page purely to 'cover' a query -- see "
            "references/seo-playbook.md section 1 and references/red-flags.md section 1."
        ),
        "setup_notes": setup_notes,
        "summary": {
            "query_page_rows_returned_by_gsc": len(rows),
            "gsc_row_cap_hit": gsc_hit_cap,
            "rows_flagged_as_near_miss": len(flagged_rows),
            "distinct_opportunities_returned": len(opportunities),
            "keyword_context_source": (
                "dataforseo" if any(o.get("keyword_context", {}) and o["keyword_context"].get("source") == "dataforseo" for o in opportunities)
                else "ahrefs" if any(o.get("keyword_context", {}) and o["keyword_context"].get("source") == "ahrefs" for o in opportunities)
                else "none"
            ),
        },
        "opportunities": opportunities,
        "history_file": str(history_path),
        "history_note": (
            "History persists ONLY the opportunities flagged in each run (keyed by "
            "query::primary_page, capped at the last 52 entries per key). Trend across "
            "runs is therefore visible only for queries that keep getting flagged -- a "
            "key absent from a run means it was not flagged that run (below thresholds, "
            "or improved past them), never that its traffic went to zero."
        ),
        "remediation_guidance": (
            "For each opportunity, the fix is improving the primary_page's genuine "
            "usefulness for that query -- not keyword-stuffing the existing page and not "
            "spinning up a new thin page to 'target' the keyword (references/red-flags.md "
            "section 1, scaled content abuse; section 6, the meta-rule). The one "
            "evidence-backed content-improvement tactic in this system's research base is "
            "adding citations/sources, direct quotations, and concrete statistics "
            "(references/geo-playbook.md section 5, Aggarwal et al. KDD 2024) -- prefer "
            "that remediation style over generic prose expansion or heading/list "
            "restructuring, which that same research found no evidence for."
        ),
    }

    reports_dir = cfg.reports_dir
    ts = time.strftime("%Y%m%d-%H%M%S")
    report_path = reports_dir / f"keyword-opportunities-{ts}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report_file"] = str(report_path)

    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
