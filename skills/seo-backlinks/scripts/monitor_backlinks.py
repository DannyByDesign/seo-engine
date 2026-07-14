"""seo-backlinks: read-only backlink profile MONITORING.

This script NEVER acquires, builds, requests, or automates outbound link
building of any kind. It only reads the current backlink profile from
whichever provider is configured (Ahrefs preferred, DataForSEO fallback),
snapshots it, diffs it against the most recent prior snapshot to report
NEW and LOST backlinks, and separately surfaces "broken backlinks" -- cases
where an external site links to a URL on this domain that now returns a
bad status (404, 5xx, or a redirect chain/loop). Fixing a broken backlink
means fixing *your own site's response* to a link that already exists; it
is not link acquisition and is explicitly in-scope (see SKILL.md and
references/red-flags.md section 1, "Link spam / link schemes").

Determinism and honesty guarantees the diff depends on:
  * Rows are fetched oldest-first (first_seen ascending) with offset
    pagination up to --cap (default 1000), so the fetched window is stable
    across runs instead of provider-default ordering churn.
  * Before any link-level new/lost diff, the provider's own profile totals
    (ahrefs.backlinks_stats / dataforseo.backlinks_summary) are consulted.
    If the profile is larger than --cap (or the fetch filled the cap and
    the total is unknown), link-level diffing is SKIPPED
    (diff.skipped_reason = "backlink_count_exceeds_cap") and a
    referring-DOMAIN-level diff over the stable window is reported instead
    -- a truncated link window would fabricate churn.
  * An empty or failed fetch NEVER overwrites the stored snapshot: state is
    written only after a successful parse, and an empty list is accepted as
    real only when the provider summary also reports ~0 backlinks.
  * "New" requires absence from the previous snapshot AND a first_seen no
    older than 7 days before the previous run -- anything else that slides
    into the window is reported separately as appeared_but_not_recent.
  * "Lost" requires the provider's is_lost flag or absence on 2 consecutive
    runs; a first miss is only "possibly_lost" (low severity), tracked via
    a per-link missing_streak persisted in the snapshot.

A separate, clearly-labeled competitor-gap function surfaces which domains
rank for similar terms -- informational context for seo-content-optimize /
seo-keyword-research, never a target list for outreach.

Providers (checked in this order, first configured one wins for the
new/lost/broken monitoring; --provider can force one explicitly):
  1. Ahrefs (AHREFS_API_KEY)      -> scripts.lib.ahrefs.all_backlinks /
                                      backlinks_stats / broken_backlinks /
                                      organic_competitors
  2. DataForSEO (DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD)
                                   -> scripts.lib.dataforseo.backlinks_summary /
                                      backlinks_list / domain_intersection

If neither is configured, the script explains exactly which env vars unlock
which provider and exits with a structured "not configured" report instead
of crashing or silently no-opping.

Usage:
    python3 monitor_backlinks.py
    python3 monitor_backlinks.py --provider ahrefs --cap 2000
    python3 monitor_backlinks.py --competitor-gap example-competitor.com
    python3 monitor_backlinks.py --no-diff   # skip snapshot diff, just fetch+report current state

Output: structured JSON to stdout; a dated copy is ALWAYS written under
.seo-engine/reports/backlinks-<date>.json (including not-configured and
fetch-error runs). The current snapshot lives under
.seo-engine/state/backlinks-<date>.json (kept so the *next* run can diff
against it) and is only (over)written after a successful, confirmed fetch.
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
from datetime import date, datetime, timedelta, timezone  # noqa: E402
from typing import Any, Callable, Optional  # noqa: E402
from urllib.parse import urlparse  # noqa: E402

from scripts.lib import http_util, snapshots  # noqa: E402
from scripts.lib.config import Config  # noqa: E402

#: Max rows per provider API call while paginating up to --cap.
PAGE_SIZE = 1000
#: A backlink absent from the previous snapshot only counts as "new" when its
#: first_seen falls within this many days before the previous run.
NEW_BACKLINK_RECENCY_DAYS = 7
#: A backlink missing (without a provider is_lost flag) must be absent this
#: many consecutive runs before it is reported as lost.
LOST_CONFIRM_RUNS = 2


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

def choose_provider(cfg: Config, forced: Optional[str]) -> tuple[Optional[str], list[str]]:
    """Returns (provider_name_or_None, setup_notes). Ahrefs preferred over
    DataForSEO when both are configured, matching the assignment's stated
    preference order. Never raises -- absence is reported, not crashed on."""
    integrations = cfg.available_integrations()
    notes: list[str] = []

    if forced:
        if forced == "ahrefs" and not integrations.get("ahrefs"):
            notes.append(
                "Forced --provider ahrefs but AHREFS_API_KEY is not set. "
                "Create a key in Ahrefs > Account Settings > API Keys (owner/admin "
                "role required) -- see references/api-reference.md (Ahrefs API v3)."
            )
            return None, notes
        if forced == "dataforseo" and not integrations.get("dataforseo"):
            notes.append(
                "Forced --provider dataforseo but DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD "
                "are not both set. Create dedicated API credentials in the DataForSEO "
                "dashboard (distinct from your account login password) -- see "
                "references/api-reference.md (DataForSEO)."
            )
            return None, notes
        return forced, notes

    if integrations.get("ahrefs"):
        return "ahrefs", notes
    if integrations.get("dataforseo"):
        notes.append(
            "AHREFS_API_KEY not set -- using DataForSEO instead (DATAFORSEO_LOGIN / "
            "DATAFORSEO_PASSWORD detected)."
        )
        return "dataforseo", notes

    notes.append(
        "No backlink data provider configured. Set AHREFS_API_KEY (preferred -- see "
        "references/api-reference.md, Ahrefs API v3 section) or both DATAFORSEO_LOGIN "
        "and DATAFORSEO_PASSWORD (see references/api-reference.md, DataForSEO section) "
        "to unlock backlink monitoring. Nothing was fetched or changed."
    )
    return None, notes


# ---------------------------------------------------------------------------
# Small parsing helpers (provider fields are not trusted to be well-typed)
# ---------------------------------------------------------------------------

def _as_int(value: Any) -> Optional[int]:
    """Tolerant int coercion -- providers sometimes return status codes and
    counts as strings, floats, or junk. Never raises."""
    if isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _first_int(d: Any, keys: tuple) -> Optional[int]:
    if not isinstance(d, dict):
        return None
    for k in keys:
        v = _as_int(d.get(k))
        if v is not None:
            return v
    return None


def _parse_datetime(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _parse_date_prefix(value: Any) -> Optional[date]:
    """Date from the first 10 chars of a provider timestamp -- tolerant of
    both Ahrefs ("2026-07-01T09:00:00Z") and DataForSEO
    ("2026-07-01 09:00:00 +00:00") shapes."""
    s = str(value or "").strip()
    if len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Normalization -- both providers get flattened to the same shape so the
# diff logic and report format don't need to branch on provider identity.
# Normalized backlink dict shape:
#   { "url_from": str, "url_to": str, "first_seen": str|None,
#     "domain_rating_source": float|int|None, "link_type": str|None,
#     "is_lost": bool|None, "source_domain": str }
# ---------------------------------------------------------------------------

def _registrable_domain(url: str) -> str:
    host = urlparse(url if "//" in url else f"//{url}").netloc.lower()
    return host.removeprefix("www.")


def _ahrefs_rows(raw: dict[str, Any]) -> list[dict[str, Any]]:
    rows = raw.get("backlinks") or raw.get("data") or []
    if isinstance(rows, dict):
        rows = rows.get("backlinks", [])
    return rows if isinstance(rows, list) else []


def normalize_ahrefs_backlinks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        url_from = row.get("url_from", "")
        normalized.append({
            "url_from": url_from,
            "url_to": row.get("url_to", ""),
            "first_seen": row.get("first_seen"),
            "domain_rating_source": row.get("domain_rating_source"),
            "link_type": row.get("link_type"),
            "is_lost": row.get("is_lost"),
            "source_domain": _registrable_domain(url_from) if url_from else "",
        })
    return normalized


def normalize_ahrefs_broken(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        url_from = row.get("url_from", "")
        normalized.append({
            "url_from": url_from,
            "url_to": row.get("url_to", ""),
            "http_code": row.get("http_code"),
            "domain_rating_source": row.get("domain_rating_source"),
            "source_domain": _registrable_domain(url_from) if url_from else "",
        })
    return normalized


def _dataforseo_items(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """DataForSEO wraps results in tasks[0].result[0].items (standard v3 envelope)."""
    tasks = raw.get("tasks") or []
    if not tasks:
        return []
    result = tasks[0].get("result") or []
    if not result:
        return []
    return (result[0] or {}).get("items") or []


def normalize_dataforseo_backlinks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for row in items:
        url_from = row.get("url_from", "")
        normalized.append({
            "url_from": url_from,
            "url_to": row.get("url_to", ""),
            "first_seen": row.get("first_seen"),
            "domain_rating_source": row.get("rank") or row.get("domain_from_rank"),
            "link_type": row.get("item_type") or row.get("link_type"),
            "is_lost": row.get("is_lost"),
            "source_domain": _registrable_domain(url_from) if url_from else "",
        })
    return normalized


def normalize_dataforseo_broken(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """DataForSEO's backlinks/backlinks/live doesn't have a dedicated
    "broken backlinks" endpoint per api-reference.md -- broken links are
    derived here by filtering the full list for entries whose reported
    target status indicates a bad response. Rows missing those fields (or
    carrying non-numeric junk) simply won't be flagged (no false positives
    from guessing)."""
    normalized = []
    for row in items:
        status_code = _as_int(row.get("url_to_status_code"))
        if status_code is None:
            status_code = _as_int(row.get("http_code"))
        if status_code is None or status_code < 400:
            continue
        url_from = row.get("url_from", "")
        normalized.append({
            "url_from": url_from,
            "url_to": row.get("url_to", ""),
            "http_code": status_code,
            "domain_rating_source": row.get("rank") or row.get("domain_from_rank"),
            "source_domain": _registrable_domain(url_from) if url_from else "",
        })
    return normalized


# ---------------------------------------------------------------------------
# Fetch (per provider) -- deterministic first_seen-ascending pagination
# ---------------------------------------------------------------------------

def _paginate(fetch_page: Callable[[int, int], list[dict[str, Any]]], cap: int) -> list[dict[str, Any]]:
    """Accumulate raw provider rows page by page (limit, offset) up to `cap`,
    deduping on the url_from||url_to key in case the index shifts between
    page fetches."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    offset = 0
    while len(rows) < cap:
        page_limit = min(PAGE_SIZE, cap - len(rows))
        page = fetch_page(page_limit, offset)
        if not page:
            break
        for row in page:
            key = _backlink_key(row)
            if key not in seen:
                seen.add(key)
                rows.append(row)
        if len(page) < page_limit:
            break
        offset += len(page)
    return rows


def fetch_ahrefs(cfg: Config, target: str, cap: int) -> dict[str, Any]:
    from scripts.lib import ahrefs

    def _page(limit: int, offset: int) -> list[dict[str, Any]]:
        raw = ahrefs.all_backlinks(
            cfg, target, limit=limit, order_by="first_seen:asc", offset=offset,
        )
        return _ahrefs_rows(raw)

    current_rows = _paginate(_page, cap)
    broken_raw = ahrefs.broken_backlinks(cfg, target, limit=min(cap, PAGE_SIZE))
    return {
        "current_backlinks": normalize_ahrefs_backlinks(current_rows),
        "broken_backlinks": normalize_ahrefs_broken(_ahrefs_rows(broken_raw)),
    }


def fetch_dataforseo(cfg: Config, target: str, cap: int) -> dict[str, Any]:
    from scripts.lib import dataforseo

    def _page(limit: int, offset: int) -> list[dict[str, Any]]:
        raw = dataforseo.backlinks_list(
            cfg, target, limit=limit, offset=offset, order_by="first_seen,asc",
        )
        return _dataforseo_items(raw)

    items = _paginate(_page, cap)
    return {
        "current_backlinks": normalize_dataforseo_backlinks(items),
        # DataForSEO's live backlinks/backlinks endpoint is the only source
        # available for this -- reuse the fetched rows and filter for bad
        # status codes rather than calling a second endpoint that doesn't
        # exist for this purpose (see api-reference.md, DataForSEO Backlinks).
        "broken_backlinks": normalize_dataforseo_broken(items),
    }


# ---------------------------------------------------------------------------
# Profile totals (the refuse-to-diff guard)
# ---------------------------------------------------------------------------

def _extract_ahrefs_totals(raw: dict[str, Any]) -> tuple[Optional[int], Optional[int]]:
    metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else raw
    total = _first_int(metrics, ("live", "live_backlinks", "backlinks"))
    refdomains = _first_int(
        metrics, ("live_refdomains", "live_referring_domains", "refdomains", "referring_domains"),
    )
    return total, refdomains


def _extract_dataforseo_totals(raw: dict[str, Any]) -> tuple[Optional[int], Optional[int]]:
    tasks = raw.get("tasks") or []
    result = (tasks[0].get("result") or []) if tasks else []
    r0 = result[0] if result and isinstance(result[0], dict) else {}
    return _first_int(r0, ("backlinks",)), _first_int(r0, ("referring_domains",))


def fetch_profile_totals(cfg: Config, provider: str, target: str) -> tuple[Optional[int], Optional[int]]:
    """(total_live_backlinks, referring_domains) from the provider's own
    profile summary. Raises on API failure -- the caller decides how to
    degrade."""
    if provider == "ahrefs":
        from scripts.lib import ahrefs
        return _extract_ahrefs_totals(ahrefs.backlinks_stats(cfg, target))
    from scripts.lib import dataforseo
    return _extract_dataforseo_totals(dataforseo.backlinks_summary(cfg, target))


# ---------------------------------------------------------------------------
# Snapshot + diff
# ---------------------------------------------------------------------------

def _backlink_key(bl: dict[str, Any]) -> str:
    return f"{bl.get('url_from', '')}||{bl.get('url_to', '')}"


def load_previous_snapshot(cfg: Config, exclude_path: Path) -> Optional[dict[str, Any]]:
    """Most recent parseable backlinks-<date>.json in state_dir other than the
    one we are about to write this run. Returns None if this is the first run."""
    candidates = sorted(
        p for p in cfg.state_dir.glob("backlinks-*.json") if p != exclude_path
    )
    for candidate in reversed(candidates):
        try:
            return json.loads(candidate.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
    return None


def diff_backlinks(
    previous: Optional[dict[str, Any]], current: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Link-level diff. Returns (diff, missing_streaks_to_persist).

    New  = absent from the previous snapshot AND first_seen within
           NEW_BACKLINK_RECENCY_DAYS before the previous run. Rows that
           appear without a recent first_seen are window/index artifacts and
           are listed separately (appeared_but_not_recent), never as "new".
    Lost = present before, absent now, AND either the provider's is_lost
           flag or absence on LOST_CONFIRM_RUNS consecutive runs. A first
           miss is only "possibly_lost" (low severity) -- its missing_streak
           is persisted so the next run can confirm or clear it.
    If there is no previous snapshot, this is a baseline run -- everything
    is reported under `is_baseline: true` rather than misleadingly labeled
    "new"."""
    current_by_key: dict[str, dict[str, Any]] = {}
    for bl in current:
        current_by_key.setdefault(_backlink_key(bl), bl)

    if previous is None:
        return ({
            "is_baseline": True,
            "mode": "link",
            "previous_snapshot_date": None,
            "new_backlinks": [],
            "lost_backlinks": [],
            "possibly_lost": [],
            "new_count": 0,
            "lost_count": 0,
            "possibly_lost_count": 0,
            "note": (
                "No prior snapshot found -- this is the first recorded run. "
                f"{len(current)} current backlink(s) saved as the baseline for "
                "the next run to diff against."
            ),
        }, {})

    prev_links: dict[str, dict[str, Any]] = {}
    for bl in previous.get("current_backlinks", []):
        prev_links.setdefault(_backlink_key(bl), bl)
    prev_streaks: dict[str, Any] = previous.get("missing_streaks") or {}

    prev_generated = _parse_datetime(previous.get("generated_at"))
    recency_cutoff = (
        (prev_generated - timedelta(days=NEW_BACKLINK_RECENCY_DAYS)).date()
        if prev_generated else None
    )

    # Rows the provider itself flags as lost are not part of the live set.
    provider_lost_keys = {k for k, bl in current_by_key.items() if bl.get("is_lost")}
    live_keys = set(current_by_key) - provider_lost_keys

    new_backlinks: list[dict[str, Any]] = []
    appeared_not_recent: list[dict[str, Any]] = []
    for k in sorted(live_keys - set(prev_links)):
        bl = current_by_key[k]
        first_seen = _parse_date_prefix(bl.get("first_seen"))
        if recency_cutoff is None or (first_seen is not None and first_seen >= recency_cutoff):
            new_backlinks.append(bl)
        else:
            appeared_not_recent.append(bl)

    lost: list[dict[str, Any]] = []
    possibly_lost: list[dict[str, Any]] = []
    new_streaks: dict[str, Any] = {}

    def _track_missing(key: str, bl: dict[str, Any], streak: int) -> None:
        if streak >= LOST_CONFIRM_RUNS:
            lost.append({**bl, "lost_evidence": f"absent_{streak}_consecutive_runs"})
        else:
            possibly_lost.append({
                **bl,
                "status": "possibly_lost",
                "severity": "low",
                "missing_streak": streak,
                "note": (
                    "Absent from this run's fetch but not flagged is_lost by the "
                    f"provider -- confirmed as lost only after {LOST_CONFIRM_RUNS} "
                    "consecutive missing runs (transient index churn is common)."
                ),
            })
            new_streaks[key] = {"missing_streak": streak, "backlink": bl}

    for k, bl in prev_links.items():
        if k in live_keys:
            continue  # still present and live
        if k in provider_lost_keys:
            lost.append({**current_by_key[k], "lost_evidence": "provider_is_lost"})
        elif bl.get("is_lost"):
            lost.append({**bl, "lost_evidence": "provider_is_lost"})
        else:
            _track_missing(k, bl, 1)

    for k, entry in prev_streaks.items():
        if not isinstance(entry, dict) or k in prev_links:
            continue
        if k in live_keys:
            continue  # reappeared -- streak cleared, nothing to report
        bl = entry.get("backlink") or {}
        if k in provider_lost_keys:
            lost.append({**current_by_key[k], "lost_evidence": "provider_is_lost"})
            continue
        streak = (_as_int(entry.get("missing_streak")) or 1) + 1
        _track_missing(k, bl, streak)

    sort_key = lambda bl: (bl.get("url_from", ""), bl.get("url_to", ""))  # noqa: E731
    lost.sort(key=sort_key)
    possibly_lost.sort(key=sort_key)

    return ({
        "is_baseline": False,
        "mode": "link",
        "previous_snapshot_date": previous.get("generated_at"),
        "new_backlinks": new_backlinks,
        "new_count": len(new_backlinks),
        "appeared_but_not_recent": appeared_not_recent,
        "appeared_but_not_recent_count": len(appeared_not_recent),
        "lost_backlinks": lost,
        "lost_count": len(lost),
        "possibly_lost": possibly_lost,
        "possibly_lost_count": len(possibly_lost),
        "rules": {
            "new": (
                f"absent from the previous snapshot AND first_seen within "
                f"{NEW_BACKLINK_RECENCY_DAYS} days before the previous run; rows "
                "appearing without a recent first_seen are window/index artifacts "
                "(see appeared_but_not_recent)."
            ),
            "lost": (
                "provider is_lost flag, or absent for "
                f"{LOST_CONFIRM_RUNS} consecutive runs; a first miss is only "
                "possibly_lost (low severity)."
            ),
        },
    }, new_streaks)


def diff_referring_domains(
    previous: Optional[dict[str, Any]], current: list[dict[str, Any]],
) -> dict[str, Any]:
    """Fallback diff when the profile exceeds --cap: link-level new/lost over
    a truncated window would fabricate churn, but the set of referring
    DOMAINS observed in the stable (first_seen-ascending) window is still
    comparable run-over-run."""
    cur_domains = {bl.get("source_domain", "") for bl in current if bl.get("source_domain")}

    if previous is None:
        return {
            "is_baseline": True,
            "mode": "referring_domain",
            "previous_snapshot_date": None,
            "new_referring_domains": [],
            "lost_referring_domains": [],
            "new_count": 0,
            "lost_count": 0,
            "referring_domains_in_window": len(cur_domains),
            "note": (
                "No prior snapshot found -- this is the first recorded run. "
                f"{len(cur_domains)} referring domain(s) in the fetched window "
                "saved as the baseline."
            ),
        }

    prev_domains = {
        bl.get("source_domain", "")
        for bl in previous.get("current_backlinks", [])
        if bl.get("source_domain")
    }
    new_domains = sorted(cur_domains - prev_domains)
    lost_domains = sorted(prev_domains - cur_domains)
    return {
        "is_baseline": False,
        "mode": "referring_domain",
        "previous_snapshot_date": previous.get("generated_at"),
        "new_referring_domains": new_domains,
        "lost_referring_domains": lost_domains,
        "new_count": len(new_domains),
        "lost_count": len(lost_domains),
        "referring_domains_in_window": len(cur_domains),
    }


# ---------------------------------------------------------------------------
# Broken-backlink reporting (actionable, via seo-redirects -- fixing your own
# site's response to an existing link, not acquiring anything new)
# ---------------------------------------------------------------------------

def build_broken_backlink_findings(broken: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings = []
    for bl in broken:
        http_code = bl.get("http_code")
        code = _as_int(http_code)
        severity = "high" if code is None or code >= 500 else "medium"
        findings.append({
            "type": "broken_backlink",
            "severity": severity,
            "url_to": bl.get("url_to", ""),
            "url_from": bl.get("url_from", ""),
            "source_domain": bl.get("source_domain", ""),
            "http_code": http_code,
            "domain_rating_source": bl.get("domain_rating_source"),
            "detail": (
                f"External page {bl.get('url_from', '(unknown)')} links to "
                f"{bl.get('url_to', '(unknown)')} on this domain, which currently "
                f"returns HTTP {http_code if http_code is not None else '(unknown/unreachable)'}. "
                "This is an existing inbound link losing its value because of your "
                "own site's response, not a link-acquisition opportunity."
            ),
            "seo_playbook_ref": "seo-playbook.md §5 (Canonicalization and indexing hygiene) — "
                                 "broken backlinks are frequently the result of an unplanned "
                                 "redirect/404 rather than a canonical issue, but the same "
                                 "'don't silently break existing equity' principle applies.",
            "auto_fixable": False,
            "human_review_reason": (
                "The correct fix (301 redirect to the current equivalent page, restore "
                "the original URL, or accept the loss if the page is genuinely gone) "
                "requires knowing what replaced the old content. Route to seo-redirects "
                "to implement a 301 once the correct destination is confirmed."
            ),
        })
    return findings


# ---------------------------------------------------------------------------
# Competitor-gap AWARENESS (never an outreach/acquisition target list)
# ---------------------------------------------------------------------------

def competitor_gap_ahrefs(cfg: Config, target: str, competitor: Optional[str], limit: int) -> dict[str, Any]:
    from scripts.lib import ahrefs

    result: dict[str, Any] = {
        "organic_competitors": ahrefs.organic_competitors(cfg, target, limit=limit),
    }
    if competitor:
        result["note"] = (
            "Ahrefs' all-backlinks endpoint used above is a domain-level backlink list, "
            "not a two-domain intersection tool -- this reports your own organic "
            "competitor set, not a link-source overlap with the named competitor. For a "
            "true link-source intersection, configure DataForSEO (domain_intersection) "
            "as well."
        )
    return result


def competitor_gap_dataforseo(cfg: Config, target: str, competitor: Optional[str], limit: int) -> dict[str, Any]:
    from scripts.lib import dataforseo

    result: dict[str, Any] = {
        "competitors_domain": dataforseo.competitors_domain(cfg, target, limit=limit),
    }
    if competitor:
        result["domain_intersection"] = dataforseo.domain_intersection(cfg, target, competitor)
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _emit_report(report: dict[str, Any], cfg: Config, today: str) -> None:
    """Write the dated report copy (ALWAYS -- including not-configured and
    error runs, which SKILL.md promises a report file for) and print the
    report to stdout."""
    dated_report_path = cfg.reports_dir / f"backlinks-{today}.json"
    dated_report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report_file"] = str(dated_report_path)
    json.dump(report, sys.stdout, indent=2)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "seo-backlinks: read-only backlink profile monitoring (new/lost backlinks, "
            "broken backlinks, competitor-gap awareness). Never acquires or builds links."
        )
    )
    parser.add_argument("--provider", choices=["ahrefs", "dataforseo"], default=None,
                        help="Force a specific provider instead of auto-selecting "
                             "(Ahrefs preferred if both configured).")
    parser.add_argument("--cap", type=int, default=1000,
                        help="Max total backlink rows to fetch, paginated oldest-first "
                             "(first_seen ascending) in pages of up to 1000. If the "
                             "provider's profile total exceeds this cap, link-level "
                             "new/lost diffing is skipped in favor of a referring-domain "
                             "diff (default 1000; provider plan limits still apply).")
    parser.add_argument("--no-diff", action="store_true",
                        help="Skip diffing against the previous snapshot -- just fetch and "
                             "report the current state (missing-streak state is preserved, "
                             "not advanced).")
    parser.add_argument("--competitor-gap", metavar="COMPETITOR_DOMAIN", nargs="?",
                        const="", default=None,
                        help="Also run competitor-gap AWARENESS reporting (never an outreach "
                             "target list). Bare flag reports your organic-competitor set only; "
                             "naming a COMPETITOR_DOMAIN additionally runs a link-source "
                             "intersection (DataForSEO only).")
    parser.add_argument("--competitor-limit", type=int, default=20,
                        help="Max competitor rows to fetch for the gap-awareness report.")
    args = parser.parse_args()

    cfg = config_module.load()
    snapshots.prune(cfg)
    site_url = cfg.site_url
    target = urlparse(site_url).netloc or site_url

    provider, setup_notes = choose_provider(cfg, args.provider)

    generated_at = datetime.now(timezone.utc).isoformat()
    today = time.strftime("%Y-%m-%d")
    snapshot_path = cfg.state_dir / f"backlinks-{today}.json"

    warnings: list[str] = []
    report: dict[str, Any] = {
        "site_url": site_url,
        "target": target,
        "generated_at": generated_at,
        "provider_used": provider,
        "integrations_available": cfg.available_integrations(),
        "setup_notes": setup_notes,
        "warnings": warnings,
        "scope_note": (
            "This skill is READ-ONLY monitoring. It never acquires, builds, requests, or "
            "automates outbound link-building of any kind (references/red-flags.md §1, "
            "'Link spam / link schemes'). New/lost backlinks and competitor-gap data below "
            "are for awareness and research only."
        ),
        "findings": [],
    }

    if provider is None:
        report["current_backlink_count"] = 0
        report["diff"] = {"is_baseline": None, "note": "No provider configured -- nothing fetched."}
        report["broken_backlinks"] = []
        _emit_report(report, cfg, today)
        return

    # -- Refuse-to-diff guard (a): provider profile totals first -------------
    total: Optional[int] = None
    referring_domains: Optional[int] = None
    try:
        total, referring_domains = fetch_profile_totals(cfg, provider, target)
        if total is None:
            warnings.append(
                f"{provider} profile summary returned no recognizable live-backlink "
                "total -- cap enforcement falls back to the fetched-row count."
            )
    except Exception as exc:  # noqa: BLE001 -- degrade, don't crash: totals gate the diff, not the fetch
        warnings.append(http_util.sanitize_text(
            f"{provider} profile-summary call failed ({exc}) -- profile totals unknown. "
            "An empty fetch cannot be confirmed as real and will not overwrite state; "
            "a cap-filling fetch will skip link-level diffing."
        ))
    report["profile_totals"] = {
        "backlinks": total,
        "referring_domains": referring_domains,
        "source": ("ahrefs.backlinks_stats" if provider == "ahrefs"
                   else "dataforseo.backlinks_summary"),
    }

    try:
        if provider == "ahrefs":
            fetched = fetch_ahrefs(cfg, target, args.cap)
        else:
            fetched = fetch_dataforseo(cfg, target, args.cap)
    except Exception as exc:  # noqa: BLE001 -- report the failure, don't crash uninformatively
        report["error"] = http_util.sanitize_text(f"{provider} API call failed: {exc}")
        report["current_backlink_count"] = 0
        report["diff"] = {
            "is_baseline": None,
            "skipped_reason": "fetch_error",
            "note": "Fetch failed -- see 'error' field. The stored snapshot was NOT overwritten.",
        }
        report["broken_backlinks"] = []
        _emit_report(report, cfg, today)
        return

    current_backlinks = fetched.get("current_backlinks", [])
    broken_backlinks = fetched.get("broken_backlinks", [])

    if len(current_backlinks) >= args.cap:
        warnings.append(
            f"Fetched row count ({len(current_backlinks)}) hit --cap ({args.cap}) -- "
            "the fetched window is truncated. It is stable across runs (oldest-first "
            "ordering), but it does not cover the whole profile; raise --cap for "
            "fuller coverage."
        )

    previous = load_previous_snapshot(cfg, snapshot_path)
    prev_streaks: dict[str, Any] = dict((previous or {}).get("missing_streaks") or {})

    # -- Refuse-to-diff guard (b): an empty fetch is only real if the provider
    #    summary agrees the profile is ~0. Otherwise never overwrite state. --
    write_snapshot = True
    new_streaks: dict[str, Any] = prev_streaks
    exceeds_cap = (total is not None and total > args.cap) or (
        total is None and len(current_backlinks) >= args.cap
    )

    if not current_backlinks and (total is None or total > 0):
        write_snapshot = False
        diff: dict[str, Any] = {
            "is_baseline": None,
            "skipped_reason": "empty_fetch_unconfirmed",
            "note": (
                "Provider returned zero backlink rows but the profile summary "
                + (f"reports {total} live backlinks" if total is not None
                   else "is unavailable")
                + " -- treated as a failed/partial fetch, not a real empty profile. "
                "The stored snapshot was NOT overwritten and no new/lost diff was made."
            ),
        }
        warnings.append(
            "Empty backlink fetch could not be confirmed against the provider summary -- "
            "snapshot preserved, diff skipped."
        )
    elif args.no_diff:
        diff = {"is_baseline": None, "note": "--no-diff passed; skipped."}
    elif exceeds_cap:
        # Guard (a): link-level diff over a truncated window fabricates churn.
        diff = diff_referring_domains(previous, current_backlinks)
        diff["skipped_reason"] = "backlink_count_exceeds_cap"
        diff["note"] = (
            (f"Provider reports {total} live backlinks, more than --cap ({args.cap})"
             if total is not None
             else f"Fetch filled --cap ({args.cap}) and the profile total is unknown")
            + " -- link-level new/lost diffing over a truncated window would fabricate "
            "churn, so it was SKIPPED. Referring domains within the stable oldest-first "
            "window are diffed instead. Raise --cap"
            + (f" to at least {total}" if total is not None else "")
            + " for link-level diffing. Per-link missing-streak state was preserved, "
            "not advanced."
        )
    else:
        diff, new_streaks = diff_backlinks(previous, current_backlinks)

    if write_snapshot:
        snapshot_payload = {
            "generated_at": generated_at,
            "provider": provider,
            "target": target,
            "fetch_cap": args.cap,
            "profile_total_backlinks": total,
            "current_backlinks": current_backlinks,
            "missing_streaks": new_streaks,
        }
        snapshot_path.write_text(json.dumps(snapshot_payload, indent=2), encoding="utf-8")
        report["snapshot_file"] = str(snapshot_path)
    else:
        report["snapshot_file"] = None

    broken_findings = build_broken_backlink_findings(broken_backlinks)
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    broken_findings.sort(key=lambda f: severity_order.get(f.get("severity", "low"), 9))

    report["current_backlink_count"] = len(current_backlinks)
    report["diff"] = diff
    report["broken_backlink_count"] = len(broken_findings)
    report["broken_backlinks"] = broken_findings
    report["findings"] = broken_findings  # top-level alias for callers that scan `findings` uniformly

    if args.competitor_gap is not None:
        try:
            if provider == "ahrefs":
                gap = competitor_gap_ahrefs(cfg, target, args.competitor_gap, args.competitor_limit)
            else:
                gap = competitor_gap_dataforseo(cfg, target, args.competitor_gap, args.competitor_limit)
            gap["scope_note"] = (
                "Informational only -- competitor domains listed here are context for "
                "seo-content-optimize / seo-keyword-research, never a target list for link "
                "outreach or acquisition."
            )
            report["competitor_gap"] = gap
        except Exception as exc:  # noqa: BLE001
            report["competitor_gap"] = {
                "error": http_util.sanitize_text(f"{provider} competitor-gap call failed: {exc}"),
            }

    _emit_report(report, cfg, today)


if __name__ == "__main__":
    main()
