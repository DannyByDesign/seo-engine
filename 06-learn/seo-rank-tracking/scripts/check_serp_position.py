"""Supplementary, on-demand exact SERP-position check for a single keyword.

This is NOT the primary rank-tracking mechanism -- track_rankings.py (GSC's
own search_analytics data) is free, always-available, and already covers every
query/page combination the site has impressions for. This script exists for
the narrower case where a site owner wants an exact, live, right-now SERP
position for one high-priority keyword -- to validate a GSC-reported drop
against live reality (GSC position is an internally-averaged/rounded figure
with an inherent ~2-3 day reporting lag; a live SERP check has neither
property), or to watch a specific competitor's position for the same keyword.

Requires DataForSEO (preferred -- pay-as-you-go, no subscription-tier gate,
cheaper per call per references/api-reference.md) or Ahrefs (requires an
active paid plan) to be configured. If neither is configured, this script
prints a clear, actionable explanation of what unlocks it and exits
non-error -- it never crashes or silently no-ops.

Domain matching against SERP results is subdomain-aware (urlnorm.same_site):
a result on blog.example.com counts as a match for example.com, and www/case
variants are folded -- an exact-host string compare would miss rankings that
live on a subdomain of the configured site.

Usage:
    python3 check_serp_position.py --keyword "best running shoes"
    python3 check_serp_position.py --keyword "best running shoes" --location-code 2826  # UK
    python3 check_serp_position.py --keyword "best running shoes" --domain example.com
    python3 check_serp_position.py --keyword "best running shoes" --source ahrefs

Output: structured JSON to stdout; also appended to a per-keyword history file
in .seo-engine/state/serp-check-history.json so repeated ad-hoc checks on the
same keyword build a light trend line over time, distinct from (and much
sparser than) the GSC-driven weekly series in rank-history.json.
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
from datetime import datetime, timezone
from typing import Any

from scripts.lib import http_util, snapshots, urlnorm
from scripts.lib.config import Config, MissingConfigError

HISTORY_FILENAME = "serp-check-history.json"


def _domain_from_site_url(site_url: str) -> str:
    """Folded (lowercased, www-stripped) host of the configured site URL."""
    return urlnorm.host_key(site_url) or site_url


def _check_via_dataforseo(
    cfg: Config, keyword: str, domain: str, location_code: int, language_code: str,
) -> dict[str, Any]:
    from scripts.lib import dataforseo

    result = dataforseo.serp_live(cfg, keyword, location_code=location_code, language_code=language_code)
    tasks = result.get("tasks", []) or []
    if not tasks or not tasks[0].get("result"):
        return {
            "source": "dataforseo", "found": False, "position": None,
            "note": "DataForSEO returned no SERP result for this keyword/location.",
            "raw_task_status": tasks[0].get("status_message") if tasks else None,
        }

    items = (tasks[0]["result"][0] or {}).get("items", []) or []
    organic_items = [i for i in items if i.get("type") == "organic"]

    matched = None
    for item in organic_items:
        candidate = item.get("url") or item.get("domain") or ""
        if candidate and urlnorm.same_site(candidate, domain, include_subdomains=True):
            matched = item
            break

    top_10 = [
        {
            "rank_absolute": i.get("rank_absolute"),
            "domain": i.get("domain"),
            "url": i.get("url"),
            "title": i.get("title"),
        }
        for i in organic_items[:10]
    ]

    return {
        "source": "dataforseo",
        "found": matched is not None,
        "position": matched.get("rank_absolute") if matched else None,
        "matched_url": matched.get("url") if matched else None,
        "total_organic_results_returned": len(organic_items),
        "top_10_context": top_10,
        "note": (
            f"{domain} found at absolute rank {matched.get('rank_absolute')} "
            "(subdomain-aware host match)."
            if matched else
            f"{domain} (including subdomains) not present in the organic results "
            f"DataForSEO returned ({len(organic_items)} organic items checked)."
        ),
    }


def _check_via_ahrefs(cfg: Config, keyword: str, domain: str) -> dict[str, Any]:
    from scripts.lib import ahrefs

    result = ahrefs.organic_keywords(cfg, domain, limit=1000)
    rows = result.get("keywords", result.get("data", [])) or []
    matched = next((r for r in rows if (r.get("keyword") or "").lower() == keyword.lower()), None)

    return {
        "source": "ahrefs",
        "found": matched is not None,
        "position": matched.get("best_position") if matched else None,
        "matched_url": matched.get("best_position_url") if matched else None,
        "note": (
            f"Found in Ahrefs' organic_keywords index for {domain} at best position "
            f"{matched.get('best_position')}. Note: this is Ahrefs' own crawl-based index, "
            "not a synchronous live SERP fetch -- expect some lag vs. check-this-second "
            "reality, though typically less averaging/rounding than GSC."
            if matched else
            f"Keyword not found in Ahrefs' organic_keywords index for {domain} "
            f"(checked up to 1000 ranking keywords) -- either the domain doesn't rank in "
            "Ahrefs' index for this exact keyword string, or it ranks outside what this "
            "call returned."
        ),
    }


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="On-demand exact SERP-position check for one keyword via DataForSEO "
                    "(preferred, live) or Ahrefs (index-based) -- supplementary to "
                    "track_rankings.py's GSC-based history, not a replacement for it."
    )
    parser.add_argument("--keyword", required=True, help="Exact keyword/query to check.")
    parser.add_argument("--domain", default=None,
                        help="Domain to look for in results (default: derived from "
                             ".seo-engine/config.yml's site_url).")
    parser.add_argument("--location-code", type=int, default=2840,
                        help="DataForSEO location_code (default 2840 = United States). "
                             "Ignored for --source ahrefs.")
    parser.add_argument("--language-code", default="en",
                        help="DataForSEO language_code (default 'en'). Ignored for --source ahrefs.")
    parser.add_argument("--source", choices=["auto", "dataforseo", "ahrefs"], default="auto",
                        help="Which provider to use (default auto: DataForSEO if configured, "
                             "else Ahrefs, else explain what's missing).")
    args = parser.parse_args()

    cfg = config_module.load()
    snapshots.prune(cfg)
    integrations = cfg.available_integrations()

    try:
        domain = args.domain or _domain_from_site_url(cfg.site_url)
    except MissingConfigError as exc:
        json.dump({"error": str(exc)}, sys.stdout, indent=2)
        print()
        sys.exit(1)

    use_dataforseo = integrations.get("dataforseo") and args.source in ("auto", "dataforseo")
    use_ahrefs = (not use_dataforseo) and integrations.get("ahrefs") and args.source in ("auto", "ahrefs")

    if args.source == "dataforseo" and not integrations.get("dataforseo"):
        use_dataforseo = False
    if args.source == "ahrefs" and not integrations.get("ahrefs"):
        use_ahrefs = False

    if not use_dataforseo and not use_ahrefs:
        result = {
            "error": "No SERP-position provider is configured for this supplementary check.",
            "keyword": args.keyword,
            "domain": domain,
            "remediation": (
                "This script is optional and supplementary -- track_rankings.py's GSC-based "
                "position history (free, always-available) is the primary mechanism and needs "
                "no additional setup. To unlock an exact, live single-keyword SERP snapshot: "
                "set DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD (preferred -- pay-as-you-go, no "
                "subscription-tier gate, ~$0.002/query live per references/api-reference.md), "
                "or AHREFS_API_KEY (requires an active paid plan, Lite tier or above; answers "
                "from Ahrefs' own crawl index rather than a synchronous live fetch)."
            ),
        }
        json.dump(result, sys.stdout, indent=2)
        print()
        sys.exit(0)

    try:
        if use_dataforseo:
            check = _check_via_dataforseo(cfg, args.keyword, domain, args.location_code, args.language_code)
        else:
            check = _check_via_ahrefs(cfg, args.keyword, domain)
    except MissingConfigError as exc:
        json.dump({"error": str(exc)}, sys.stdout, indent=2)
        print()
        sys.exit(1)
    except Exception as exc:
        json.dump({
            "error": http_util.sanitize_text(
                f"SERP check via {'dataforseo' if use_dataforseo else 'ahrefs'} failed: {exc}"
            ),
            "keyword": args.keyword,
            "domain": domain,
        }, sys.stdout, indent=2)
        print()
        sys.exit(1)

    now_iso = datetime.now(timezone.utc).isoformat()
    history = _load_history(cfg)
    key = f"{args.keyword}::{domain}::{check['source']}"
    history.setdefault(key, [])
    history[key].append({
        "checked_at": now_iso,
        "position": check.get("position"),
        "found": check.get("found"),
    })
    history[key] = history[key][-200:]
    history_path = _save_history(cfg, history)

    report = {
        "generated_at": now_iso,
        "keyword": args.keyword,
        "domain": domain,
        "check": check,
        "how_to_interpret": (
            "Compare `check.position` against the corresponding key's `latest_position` in "
            "track_rankings.py's output (or rank-history.json) for the same query. A close "
            "match increases confidence that a GSC-reported drop is real. A meaningful "
            "mismatch (e.g. GSC shows position 14 but this live check shows position 6) is "
            "more likely GSC's inherent averaging/rounding/lag than a real discrepancy -- see "
            "references/api-reference.md's Google Search Console section on reporting "
            "characteristics, and treat this live check as the tie-breaker when it disagrees "
            "with GSC, not the other way around, since it reflects one exact moment/location/"
            "device rather than GSC's aggregate."
        ),
        "history_file": str(history_path),
        "history_entries_for_this_keyword": len(history[key]),
    }

    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
