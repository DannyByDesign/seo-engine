"""Rank tracking over time using Google Search Console's own position data as
the primary, free, always-available source.

Core idea (see this skill's SKILL.md "Why GSC first"): GSC's search_analytics
already contains real position data for every query/page combination the site
has impressions for -- there is no need to pay for a SERP-position tracker to
know "did this drop." What GSC can't give you is an exact, instantaneous SERP
snapshot (its data has an inherent ~2-3 day lag and internally-averaged/rounded
positions across devices and personalization) -- that gap is what
check_serp_position.py (DataForSEO/Ahrefs, optional) exists to fill for a
specific high-priority keyword, not as the default measurement mechanism.

Pipeline:
  1. gsc.search_analytics_query_all(dimensions=["query","date"] or
     ["page","date"]) over a rolling window (default: last 90 days, ending 3
     days before GSC "today" -- gsc.gsc_today(), America/Los_Angeles, GSC's
     own reporting timezone and lag). Rows are fetched with full startRow
     pagination, so nothing is silently truncated at the API's 25k-per-request
     ceiling; if the --max-rows safety cap is hit anyway, hit_cap is recorded
     in setup_notes and the summary instead of pretending coverage is
     complete. The GSC property identifier is resolved automatically from the
     configured site_url (gsc.resolve_property).
  2. Merge the TRACKED keys' rows into .seo-engine/state/rank-history.json
     (one row per tracked query/page per date, deduped, so re-running with a
     shorter --days doesn't lose older data already recorded). Only tracked
     keys are persisted -- the history is a curated record of the keys this
     skill watches, not a mirror of everything GSC returned.
  3. Bucket rows into impression-weighted ISO-week averages and detect drops
     via scripts.lib.gsc_trends (the same methodology seo-maintain reuses):
     the trailing PARTIAL ISO week is dropped first (a 1-3-day "week" average
     is not comparable to full-week baselines), then each key's latest
     complete week is compared against the mean of the prior --baseline-weeks
     weeks, and a DROP is flagged only when it exceeds both --drop-threshold
     positions and the baseline's own week-to-week standard deviation. An
     improvement is recorded but never "flagged" the same way -- see SKILL.md
     for why a drop is the actionable, time-sensitive signal and an
     improvement is not.

Tracking scope: if .seo-engine/config.yml has non-empty `target_topics`, those
strings are used as a substring/keyword filter against GSC's own `query`
dimension (case-insensitive). If target_topics is empty/absent, this script
falls back to "all queries above --min-impressions total impressions in the
window" -- so the skill is useful immediately, before a human has curated a
target-topic list.

Usage:
    python3 track_rankings.py                          # queries, last 90 days
    python3 track_rankings.py --dimension page          # track pages instead
    python3 track_rankings.py --days 60 --baseline-weeks 4
    python3 track_rankings.py --min-impressions 20
    python3 track_rankings.py --drop-threshold 3.0      # positions worse = "meaningful"

Output: structured JSON to stdout; also written to
.seo-engine/reports/rank-tracking-<timestamp>.json. Position history for
TRACKED keys (one row per tracked query/page per date) lives in
.seo-engine/state/rank-history.json and grows across runs.
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
from datetime import date, timedelta, datetime, timezone  # noqa: E402
from typing import Any  # noqa: E402

from scripts.lib import gsc, gsc_trends, http_util, snapshots  # noqa: E402
from scripts.lib.config import Config, MissingConfigError  # noqa: E402

REPORTING_LAG_DAYS = 3  # GSC data is unreliable/incomplete for the most recent ~2-3 days
HISTORY_FILENAME = "rank-history.json"


def _fetch_gsc_history(
    cfg: Config, dimension: str, days: int, max_rows: int,
) -> tuple[list[dict[str, Any]], date, bool, list[str]]:
    """Returns (rows, window_end, hit_cap, notes). Each row: {key, date,
    clicks, impressions, ctr, position} where `key` is the query string or
    page URL depending on `dimension`. Window math uses gsc.gsc_today()
    (America/Los_Angeles -- GSC's reporting timezone), and the property is
    resolved automatically from the configured site_url."""
    notes: list[str] = []
    end = gsc.gsc_today() - timedelta(days=REPORTING_LAG_DAYS)
    start = end - timedelta(days=days)

    raw_rows, hit_cap = gsc.search_analytics_query_all(
        cfg, start.isoformat(), end.isoformat(),
        dimensions=[dimension, "date"], max_rows=max_rows,
    )

    rows_out = []
    for row in raw_rows:
        keys = row.get("keys", [])
        if len(keys) < 2:
            continue
        rows_out.append({
            "key": keys[0],
            "date": keys[1],
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr": row.get("ctr", 0.0),
            "position": row.get("position", 0.0),
        })
    notes.append(
        f"GSC window: {start.isoformat()} to {end.isoformat()} ({days} days, "
        f"{REPORTING_LAG_DAYS}-day reporting lag applied, dates in GSC's "
        f"America/Los_Angeles reporting timezone), dimension={dimension}, "
        f"{len(rows_out)} {dimension}+date rows fetched via startRow pagination "
        f"(max_rows={max_rows})."
    )
    if hit_cap:
        notes.append(
            f"WARNING hit_cap: the --max-rows cap ({max_rows}) was reached -- the row "
            "set is truncated. Keys absent from this window may still have traffic; "
            "treat absence as unknown, not zero, and raise --max-rows for full coverage."
        )
    return rows_out, end, hit_cap, notes


def _select_tracked_keys(
    rows: list[dict[str, Any]], target_topics: list[str], min_impressions: int,
) -> tuple[set[str], list[str]]:
    """Decide which query/page 'key' values are in-scope for tracking this run.

    Prefers target_topics from .seo-engine/config.yml (case-insensitive
    substring match against each key) when non-empty; otherwise falls back to
    "every key whose total impressions across the window >= min_impressions",
    so the skill is useful before a human curates a target list.
    """
    notes: list[str] = []
    totals: dict[str, int] = {}
    for row in rows:
        totals[row["key"]] = totals.get(row["key"], 0) + row["impressions"]

    if target_topics:
        needles = [t.lower() for t in target_topics if t and t.strip()]
        tracked = {k for k in totals if any(n in k.lower() for n in needles)}
        notes.append(
            f"Tracking scope: {len(tracked)} of {len(totals)} distinct keys matched "
            f"{len(needles)} target_topics substring(s) from .seo-engine/config.yml."
        )
        if not tracked:
            notes.append(
                "No keys matched target_topics -- falling back to the impression-threshold "
                "selection so this run still produces useful output."
            )
    else:
        tracked = set()
        notes.append(
            "No target_topics configured in .seo-engine/config.yml -- falling back to "
            "impression-threshold selection."
        )

    if not target_topics or not tracked:
        tracked = {k for k, total in totals.items() if total >= min_impressions}
        notes.append(
            f"Tracking scope: {len(tracked)} of {len(totals)} distinct keys have >= "
            f"{min_impressions} total impressions in the window."
        )

    return tracked, notes


def _attach_pages_for_query_drops(
    cfg: Config, drops: list[dict[str, Any]], days: int,
) -> list[str]:
    """For query-dimension drops, look up which page(s) actually ranked for
    that query in the most recent window so the agent has enough context to
    investigate (a query drop is only actionable once you know which page to
    check for regressions)."""
    notes: list[str] = []
    if not drops:
        return notes
    end = gsc.gsc_today() - timedelta(days=REPORTING_LAG_DAYS)
    start = end - timedelta(days=min(days, 28))  # recent window is enough to identify the ranking page(s)
    try:
        result = gsc.search_analytics_query(
            cfg, start.isoformat(), end.isoformat(),
            dimensions=["query", "page"], row_limit=5000,
        )
    except Exception as exc:  # noqa: BLE001 -- page attribution is an enhancement, not a hard dependency
        notes.append(http_util.sanitize_text(
            f"Could not attach page context to query drops: {exc}"
        ))
        return notes

    pages_by_query: dict[str, list[dict[str, Any]]] = {}
    for row in result.get("rows", []):
        keys = row.get("keys", [])
        if len(keys) < 2:
            continue
        pages_by_query.setdefault(keys[0], []).append({
            "page": keys[1],
            "impressions": row.get("impressions", 0),
            "position": row.get("position", 0.0),
        })

    for drop in drops:
        pages = sorted(pages_by_query.get(drop["key"], []), key=lambda p: -p["impressions"])
        drop["ranking_pages"] = pages[:5]

    notes.append(f"Attached ranking-page context to {len(drops)} query drop(s) from the last "
                 f"{min(days, 28)} days.")
    return notes


def _load_history(cfg: Config) -> dict[str, Any]:
    path = cfg.state_dir / HISTORY_FILENAME
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_history(cfg: Config, history: dict[str, Any]) -> Path:
    path = cfg.state_dir / HISTORY_FILENAME
    path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    return path


def _merge_into_history(
    history: dict[str, Any], dimension: str, rows: list[dict[str, Any]], tracked_keys: set[str],
) -> int:
    """Merge rows for TRACKED keys only into history[dimension][key], deduped
    by date (a re-run with overlapping windows updates same-date rows rather
    than duplicating them). Untracked keys are deliberately NOT persisted --
    rank-history.json is a curated record of the keys this skill watches,
    not a mirror of everything GSC returned. Returns the number of
    new/updated date-rows written."""
    bucket = history.setdefault(dimension, {})
    written = 0
    for row in rows:
        if row["key"] not in tracked_keys:
            continue
        key_hist = bucket.setdefault(row["key"], {})
        prior = key_hist.get(row["date"])
        if prior != {
            "clicks": row["clicks"], "impressions": row["impressions"],
            "ctr": row["ctr"], "position": row["position"],
        }:
            key_hist[row["date"]] = {
                "clicks": row["clicks"], "impressions": row["impressions"],
                "ctr": row["ctr"], "position": row["position"],
            }
            written += 1
    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Track GSC ranking position over time for tracked queries/pages, "
                    "flag statistically meaningful drops against a trailing baseline."
    )
    parser.add_argument("--dimension", choices=["query", "page"], default="query",
                        help="Track by query or by page (default query).")
    parser.add_argument("--days", type=int, default=90,
                        help="GSC lookback window in days (default 90).")
    parser.add_argument("--baseline-weeks", type=int, default=4,
                        help="Number of prior weeks (excluding the latest) averaged into the "
                             "trailing baseline a drop is measured against (default 4).")
    parser.add_argument("--drop-threshold", type=float, default=3.0,
                        help="Minimum worsening in average position (e.g. 3.0 = moved from "
                             "#5 to #8) before a change is even considered for flagging "
                             "(default 3.0). A drop is only flagged if it also exceeds the "
                             "baseline's own week-to-week standard deviation.")
    parser.add_argument("--min-impressions", type=int, default=10,
                        help="Minimum total window impressions (fallback tracking-scope "
                             "selection) and minimum latest-week impressions (drop-detection "
                             "reliability floor) -- default 10.")
    parser.add_argument("--max-rows", type=int, default=100_000,
                        help="Safety cap on total rows fetched from GSC via startRow "
                             "pagination (default 100000). If hit, the run records "
                             "hit_cap=true in setup_notes/summary instead of silently "
                             "truncating.")
    args = parser.parse_args()

    cfg = config_module.load()
    snapshots.prune(cfg)
    integrations = cfg.available_integrations()
    setup_notes: list[str] = []

    if not integrations.get("google_search_console"):
        result = {
            "error": "Google Search Console is not configured -- this skill has no data "
                     "source without it (GSC is the primary, free, always-available position "
                     "source; DataForSEO/Ahrefs SERP checks are supplementary only, see "
                     "check_serp_position.py).",
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

    try:
        rows, window_end, hit_cap, gsc_notes = _fetch_gsc_history(
            cfg, args.dimension, args.days, args.max_rows,
        )
    except (MissingConfigError, gsc.GscPropertyError) as exc:
        json.dump({"error": str(exc)}, sys.stdout, indent=2)
        print()
        sys.exit(1)
    setup_notes.extend(gsc_notes)

    target_topics = []
    if args.dimension == "query":
        target_topics = list(cfg.site.get("target_topics") or [])
    tracked_keys, scope_notes = _select_tracked_keys(rows, target_topics, args.min_impressions)
    setup_notes.extend(scope_notes)

    tracked_rows = [r for r in rows if r["key"] in tracked_keys]
    # window_end drops the trailing PARTIAL ISO week -- a 1-3-day "week"
    # average is not comparable to the full-week baseline it would be
    # diffed against.
    series = gsc_trends.weekly_series(tracked_rows, window_end=window_end)
    drops, improvements = gsc_trends.detect_drops(
        series,
        baseline_weeks=args.baseline_weeks,
        drop_threshold=args.drop_threshold,
        min_impressions=args.min_impressions,
    )

    if args.dimension == "query":
        page_notes = _attach_pages_for_query_drops(cfg, drops, args.days)
        setup_notes.extend(page_notes)

    history = _load_history(cfg)
    rows_written = _merge_into_history(history, args.dimension, rows, tracked_keys)
    history_path = _save_history(cfg, history)
    setup_notes.append(
        f"Merged {rows_written} new/updated date-rows into {history_path.name} "
        f"(tracked keys only, deduped by {args.dimension}+date)."
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    report = {
        "generated_at": now_iso,
        "site_url": cfg.site_url,
        "dimension": args.dimension,
        "lookback_days": args.days,
        "thresholds": {
            "baseline_weeks": args.baseline_weeks,
            "drop_threshold_positions": args.drop_threshold,
            "min_impressions": args.min_impressions,
        },
        "methodology_note": (
            "Position is the impression-weighted average of GSC's own per-day position "
            "figures, bucketed into ISO calendar weeks to smooth day-to-day noise "
            "(scripts.lib.gsc_trends -- the same methodology seo-maintain reuses). The "
            "trailing partial ISO week is dropped before comparison, so 'latest week' "
            "always means the latest COMPLETE week. A drop is flagged only when that "
            "week's position is worse than the trailing "
            f"{args.baseline_weeks}-week baseline by at least {args.drop_threshold} positions "
            "AND that worsening exceeds the baseline's own week-to-week standard deviation -- "
            "this avoids flagging ordinary volatility on low-volume queries/pages. "
            "Improvements are recorded but never flagged as urgent: per this skill's SKILL.md, "
            "a drop is the time-sensitive, actionable signal (something may have broken); an "
            "improvement is worth noting but does not require investigation."
        ),
        "setup_notes": setup_notes,
        "summary": {
            "distinct_keys_returned_by_gsc": len({r['key'] for r in rows}),
            "distinct_keys_tracked_this_run": len(tracked_keys),
            "tracking_scope": "target_topics" if (target_topics and args.dimension == "query") else "impression_threshold",
            "gsc_hit_cap": hit_cap,
            "drops_flagged": len(drops),
            "improvements_noted": len(improvements),
        },
        "drops": drops,
        "improvements": improvements,
        "history_file": str(history_path),
        "investigation_guidance": (
            "For each flagged drop: (1) check `ranking_pages` (query dimension only) or the "
            "key itself (page dimension) against seo-technical-audit for a status-code, "
            "noindex, canonical, or Core-Web-Vitals regression that coincides with the drop "
            "week -- see references/red-flags.md section 4 for the technical-mistake classes "
            "that silently tank a page. (2) If no technical regression is found, check whether "
            "the drop date correlates with a known Google core/spam update rather than "
            "assuming a site-side cause. (3) Use check_serp_position.py (if DataForSEO or "
            "Ahrefs is configured) to validate the GSC-reported drop against a live, exact "
            "SERP snapshot before concluding it's real and not a GSC reporting artifact "
            "(rounding, sampling, or the ~2-3 day lag)."
        ),
    }

    reports_dir = cfg.reports_dir
    ts = time.strftime("%Y%m%d-%H%M%S")
    report_path = reports_dir / f"rank-tracking-{ts}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report_file"] = str(report_path)

    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
