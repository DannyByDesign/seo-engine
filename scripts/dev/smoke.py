"""Opt-in LIVE smoke harness — one cheapest real call per configured
integration, plus a small real crawl. This is the test the offline suite
cannot be: first contact with the actual endpoints (auth shape, required
params, response format). It spends real quota/money — NEVER runs in CI.

Usage (from the target repo root, or anywhere with SEO_REPO_ROOT set):
    python3 scripts/dev/smoke.py --site https://your-site.example
    python3 scripts/dev/smoke.py --site https://... --only gsc,psi,crawl

Prints a PASS/FAIL/SKIP table (SKIP = env var not configured, named).
Exit 1 if anything FAILs.
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
    raise SystemExit("Could not locate seo-engine root; set SEO_ENGINE_ROOT.")


sys.path.insert(0, str(_find_engine_root(Path(__file__).resolve())))

import argparse
import tempfile
import traceback
from typing import Callable, Optional

from scripts.lib import config as config_module
from scripts.lib import http_util, urlnorm


def check_crawl(cfg, site: str) -> str:
    from scripts.lib import crawler

    with tempfile.TemporaryDirectory() as tmp:
        stats: dict = {}
        out = Path(tmp) / "smoke-crawl.jsonl"
        summary = crawler.crawl_to_file(site, out, max_pages=5, stats=stats)
    if summary.get("all_blocked"):
        raise RuntimeError(f"crawl blocked: robots_status={summary.get('robots_status')}")
    if summary["pages"] == 0:
        raise RuntimeError("crawl returned zero pages")
    return f"{summary['pages']} pages, robots={summary.get('robots_status')}"


def check_gsc(cfg, site: str) -> str:
    from scripts.lib import gsc

    entries = gsc.list_sites(cfg)
    prop = gsc.resolve_property(cfg, site)
    return f"{len(entries)} properties visible; resolved {prop!r}"


def check_psi(cfg, site: str) -> str:
    from scripts.lib import psi

    report = psi.run_pagespeed(cfg, site, categories=["performance"])
    score = (report.get("lighthouseResult", {}).get("categories", {})
             .get("performance", {}).get("score"))
    return f"lighthouse performance score={score}"


def check_crux(cfg, site: str) -> str:
    from scripts.lib import psi

    record = psi.crux_record(cfg, origin=site)
    metrics = list((record.get("record", {}).get("metrics") or {}).keys())
    return f"{len(metrics)} field metrics" if metrics else "no field data for origin (thin-traffic site is normal)"


def check_ahrefs(cfg, site: str) -> str:
    from scripts.lib import ahrefs

    result = ahrefs.domain_rating(cfg, urlnorm.host_key(site))
    return f"domain_rating response keys: {sorted(result)[:4]}"


def check_dataforseo(cfg, site: str) -> str:
    from scripts.lib import dataforseo

    result = dataforseo.backlinks_summary(cfg, urlnorm.host_key(site))
    task = (result.get("tasks") or [{}])[0]
    return f"task status {task.get('status_code')} ({task.get('status_message')})"


def check_semrush(cfg, site: str) -> str:
    from scripts.lib import semrush

    text = semrush.domain_overview(cfg, urlnorm.host_key(site))
    return f"domain_ranks: {text.splitlines()[0][:60]}"


def check_bing(cfg, site: str) -> str:
    from scripts.lib import bing_webmaster

    stats = bing_webmaster.get_crawl_stats(cfg, site)
    n = len(stats) if isinstance(stats, list) else "?"
    return f"GetCrawlStats returned {n} rows"


def check_firecrawl(cfg, site: str) -> str:
    from scripts.lib import firecrawl

    result = firecrawl.scrape(cfg, site, formats=["markdown"])
    words = len((result.get("data", result).get("markdown") or "").split())
    return f"rendered {words} words"


def check_indexnow(cfg, site: str) -> str:
    key = cfg.require("INDEXNOW_API_KEY", "set INDEXNOW_API_KEY")
    key_url = f"{site.rstrip('/')}/{key}.txt"
    resp = http_util.get(key_url)
    if resp.status_code != 200:
        raise RuntimeError(f"key file {key_url} returned HTTP {resp.status_code}")
    if resp.text.strip() != key:
        raise RuntimeError("key file content does not match INDEXNOW_API_KEY")
    return "key file reachable and content matches (no submission sent)"


def check_openrouter(cfg, site: str) -> str:
    from scripts.lib import llm
    result = llm.complete(cfg, "", "Reply with OK.", tier="cheap", max_tokens=32)
    return f"text completion via OpenRouter model {result['model']}"


def check_profound(cfg, site: str) -> str:
    from scripts.lib import ai_visibility

    result = ai_visibility.profound_visibility(cfg)
    return f"visibility response keys: {sorted(result)[:4]}"


def check_otterly(cfg, site: str) -> str:
    from scripts.lib import ai_visibility

    project = cfg.require("OTTERLY_PROJECT_ID", "set OTTERLY_PROJECT_ID for the smoke test")
    result = ai_visibility.otterly_visibility(cfg, project)
    return f"visibility response keys: {sorted(result)[:4]}"


def check_ga4(cfg, site: str) -> str:
    from datetime import date, timedelta
    from scripts.lib import ga4
    cfg.site['site_url'] = site
    end = date.today() - timedelta(days=4)
    result = ga4.export(cfg, (end-timedelta(days=13)).isoformat(), end.isoformat())
    if not result['complete'] or result['sampled'] or result['thresholded']:
        raise RuntimeError('GA4 response has incomplete or limited coverage; inspect export before analysis')
    return f"{len(result['rows'])} attributed landing-page rows, timezone={result['timezone']}; authentication and API shape checked, not growth"


def check_languagetool(cfg, site):
    from scripts.lib import languagetool
    result = languagetool.check(cfg, 'This is an test.', format='text', language='en-US')
    if not result['checked']: raise RuntimeError(result['error'])
    if not result['match_count']: raise RuntimeError('Known grammar error produced no suggestions; inspect server rules')
    return f"{result['match_count']} suggestions; report: {result['output']}"


CHECKS: dict[str, tuple[Optional[str], Callable]] = {
    "languagetool": ("languagetool", check_languagetool),
    "crawl": (None, check_crawl),
    "gsc": ("google_search_console", check_gsc),
    "ga4": ("google_analytics", check_ga4),
    "psi": (None, check_psi),
    "crux": ("pagespeed_insights", check_crux),
    "ahrefs": ("ahrefs", check_ahrefs),
    "dataforseo": ("dataforseo", check_dataforseo),
    "semrush": ("semrush", check_semrush),
    "bing": ("bing_webmaster", check_bing),
    "firecrawl": ("firecrawl", check_firecrawl),
    "indexnow": ("indexnow", check_indexnow),
    "openrouter": ("openrouter", check_openrouter),
    "profound": ("profound", check_profound),
    "otterly": ("otterly", check_otterly),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="LIVE per-integration smoke harness (spends real quota)")
    parser.add_argument("--site", required=True, help="site URL to exercise against (yours!)")
    parser.add_argument("--only", default=None,
                        help="comma-separated subset of checks: " + ",".join(CHECKS))
    parser.add_argument("--verbose", action="store_true", help="print tracebacks on failure")
    args = parser.parse_args()

    cfg = config_module.load()
    selected = [s.strip() for s in args.only.split(",")] if args.only else list(CHECKS)
    unknown = [s for s in selected if s not in CHECKS]
    if unknown:
        parser.error(f"unknown check(s): {', '.join(unknown)}")

    rows = []
    failed = 0
    for name in selected:
        integration, fn = CHECKS[name]
        if integration and not cfg.integration_available(integration):
            from scripts.lib.config import INTEGRATION_ENV_VARS
            spec = INTEGRATION_ENV_VARS[integration]
            env_vars = " / ".join(spec.get("any") or spec.get("all") or [])
            rows.append((name, "SKIP", f"not configured ({env_vars})"))
            continue
        try:
            detail = fn(cfg, args.site)
            rows.append((name, "PASS", detail))
        except Exception as exc:
            failed += 1
            rows.append((name, "FAIL", http_util.sanitize_text(str(exc))[:140]))
            if args.verbose:
                traceback.print_exc()

    width = max(len(name) for name, _, _ in rows)
    print(f"\nsmoke results for {args.site}:\n")
    for name, status, detail in rows:
        print(f"  {name:<{width}}  {status:<4}  {detail}")
    passed = sum(1 for _, s, _ in rows if s == "PASS")
    skipped = sum(1 for _, s, _ in rows if s == "SKIP")
    print(f"\n  {passed} passed, {failed} failed, {skipped} skipped\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
