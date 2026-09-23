"""Report which optional seo-engine integrations are configured vs. missing.

Every row is derived from scripts.lib.config's `INTEGRATION_ENV_VARS` (the
single source of truth for which env vars unlock each integration) paired
with `Config.available_integrations()` for the configured/missing verdict —
this file adds only human-facing metadata (label, how-to, what it unlocks,
cost) and never re-hardcodes env-var lists, so it cannot contradict config.py
about which vendors exist or what enables them.

Zero integrations are required — seo-engine works with just the built-in
crawler (scripts/lib/crawler.py) and Google's free APIs. This script exists
to make the current state legible, not to gate anything. It is read-only and
side-effect-free (per the seo-setup SKILL.md contract it may run before
.seo-engine/ exists, so it must not create state).

Usage:
    cd /path/to/target-repo
    python3 <seo-engine>/skills/seo-setup/scripts/check_integrations.py
    python3 <seo-engine>/skills/seo-setup/scripts/check_integrations.py --format table

Output: a single JSON object to stdout (see `build_report()` for the shape),
or a human-readable table with --format table.
"""

import json
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


# Human-facing metadata ONLY — env vars and configured status come from
# config_module.INTEGRATION_ENV_VARS / cfg.available_integrations(). Any
# integration added to config.py but missing here still gets a row (with
# generic text), so nothing is ever silently omitted.
INTEGRATION_DETAILS = {
    "languagetool": {
        "label": "LanguageTool proofreading",
        "how": "Set LANGUAGETOOL_URL to an owned /v2/check server or https://api.languagetoolplus.com/v2/check with LANGUAGETOOL_USERNAME and LANGUAGETOOL_API_KEY. Run check_writing.py to verify readiness; a URL alone does not verify access.",
        "unlocks": "Grammar, spelling, punctuation and style suggestions during drafting and final editing.",
        "cost": "owned-server resources or authenticated API entitlement; public endpoint is not for automation",
    },
    "brave_search": {
        "label": "Brave Search API",
        "how": "Create a Search API key/subscription at https://api-dashboard.search.brave.com.",
        "unlocks": "Country/language-targeted web discovery for positioning and customer research; not Google rankings or search volume.",
        "cost": "quota/paid subscription; inspect current account terms",
    },
    "google_analytics": {
        "label": "Google Analytics Data API",
        "how": "Set GA4_PROPERTY_ID plus one Google service-account credential and grant property Viewer access.",
        "unlocks": "Actual Google organic and ChatGPT referral sessions/key events for intervention evaluation.",
        "cost": "API quota; requires a configured analytics property",
    },
    "google_search_console": {
        "label": "Google Search Console",
        "how": "Set ONE of the two env vars (not both required). "
               "GOOGLE_APPLICATION_CREDENTIALS = path to a service-account JSON key file, or "
               "GSC_SERVICE_ACCOUNT_JSON = the same JSON inline (for environments that can't "
               "mount a file). The service account's client_email must be added as a verified "
               "Owner/User on the property in Search Console (Settings > Users and permissions) "
               "— see references/api-reference.md.",
        "unlocks": "Search Analytics (clicks/impressions/CTR/position), sitemap submission, and "
                   "URL Inspection (real selected-canonical, indexing status, rich-results "
                   "verdict) — the free backbone most skills (seo-indexing, seo-rank-tracking, "
                   "seo-maintain) build on.",
        "cost": "free",
    },
    "pagespeed_insights": {
        "label": "PageSpeed Insights / CrUX",
        "how": "Get a key at https://developers.google.com/speed/docs/insights/v5/get-started "
               "(same key works for both PSI and the dedicated CrUX History API).",
        "unlocks": "Core Web Vitals for seo-performance: Lighthouse lab scores + real-user CrUX "
                   "field data (works keyless at reduced/shared-IP quota; a key unlocks a "
                   "higher, dedicated quota).",
        "cost": "free",
    },
    "ahrefs": {
        "label": "Ahrefs API v3",
        "how": "Account Settings > API Keys (owner/admin role required) at ahrefs.com. "
               "Requires an Ahrefs Lite plan or above.",
        "unlocks": "Domain Rating, backlink profile/gap analysis, organic keyword rankings, "
                   "keyword volume/difficulty — used by seo-backlinks and seo-keyword-research.",
        "cost": "paid (Lite plan and up)",
    },
    "dataforseo": {
        "label": "DataForSEO",
        "how": "Generate dedicated API credentials in the DataForSEO dashboard — these are "
               "distinct from your account login password (the two env vars are an HTTP Basic "
               "Auth pair).",
        "unlocks": "SERP data, keyword search volume, on-page crawl analysis, backlinks, "
                   "competitor/domain intersection — used by seo-keyword-research and as an "
                   "Ahrefs alternative/supplement.",
        "cost": "pay-as-you-go, $50 minimum deposit, no subscription gate",
    },
    "firecrawl": {
        "label": "Firecrawl",
        "how": "Get a key at firecrawl.dev.",
        "unlocks": "JS-rendered page snapshots (Scrape/Crawl/Map) — lets seo-technical-audit "
                   "diff raw-HTML vs. rendered content to catch JS-rendering traps "
                   "(red-flags.md §4) that a plain HTTP crawl would miss.",
        "cost": "free tier: 1,000 credits/month, then credit-based",
    },
    "indexnow": {
        "label": "IndexNow",
        "how": "Run skills/seo-indexing/scripts/setup_indexnow_key.py to generate a key and "
               "scaffold the {key}.txt verification file into the site's static source dir "
               "(no signup/account needed — IndexNow is an open protocol, not a vendor "
               "account).",
        "unlocks": "Push new/changed/deleted URLs to Bing, Yandex, Naver, Seznam.cz, Yep, and "
                   "Amazon in one call — used by seo-indexing. Does NOT include Google (Google "
                   "does not participate in IndexNow at all — use Search Console for Google). "
                   "Submission only signals a change and may earn a prioritized, not immediate, "
                   "crawl — see red-flags.md §4.",
        "cost": "free",
    },
    "semrush": {
        "label": "Semrush API",
        "how": "developer.semrush.com — requires a Business plan (SEO Toolkit tier) as a "
               "prerequisite for API access at all, plus a separate API-unit purchase.",
        "unlocks": "Domain/keyword/backlink reports and Site Audit via scripts/lib/semrush.py "
                   "(supplement/alternative to Ahrefs and DataForSEO).",
        "cost": "paid (Business plan + API units)",
    },
    "bing_webmaster": {
        "label": "Bing Webmaster Tools API",
        "how": "bing.com/webmasters — API key from account settings.",
        "unlocks": "Crawl stats and query/keyword performance reads for Bing (this API is "
                   "de facto frozen; use IndexNow for URL submission instead).",
        "cost": "free",
    },
    "openai": {
        "label": "OpenAI (GEO citation-probing)",
        "how": "platform.openai.com/api-keys",
        "unlocks": "Probing ChatGPT's web-search citations via the Responses API "
                   "(url_citation annotations) — used by geo-monitor to check whether/how "
                   "this domain gets cited.",
        "cost": "pay-as-you-go API pricing",
    },
    "anthropic": {
        "label": "Anthropic (GEO citation-probing)",
        "how": "console.anthropic.com",
        "unlocks": "Probing Claude's web-search citations via the web_search tool — used by "
                   "geo-monitor.",
        "cost": "pay-as-you-go API pricing",
    },
    "perplexity": {
        "label": "Perplexity Sonar (GEO citation-probing)",
        "how": "perplexity.ai/settings/api",
        "unlocks": "Probing Perplexity's citations/search_results directly — used by "
                   "geo-monitor. Note geo-playbook.md §4 flags Perplexity's crawler-blocking "
                   "behavior as a disputed, unresolved area independent of this API.",
        "cost": "pay-as-you-go API pricing",
    },
    "gemini": {
        "label": "Google Gemini grounding (GEO citation-probing)",
        "how": "aistudio.google.com/apikey",
        "unlocks": "Grounding-with-Google-Search citation metadata for geo-monitor. Note: this "
                   "is the Gemini API's own grounding feature, not literally AI Mode/AI "
                   "Overviews in Search (those have no public API).",
        "cost": "pay-as-you-go API pricing",
    },
    "profound": {
        "label": "Profound (commercial AI-visibility tracker)",
        "how": "tryprofound.com — optional, supplementary to the DIY vendor-API probes used "
               "by geo-monitor.",
        "unlocks": "Cross-validation of geo-monitor's citation tracking against Profound's "
                   "commercial dashboard.",
        "cost": "paid subscription (from $99/mo)",
    },
    "otterly": {
        "label": "Otterly.AI (commercial AI-visibility tracker)",
        "how": "otterly.ai — optional, supplementary to the DIY vendor-API probes used by "
               "geo-monitor.",
        "unlocks": "Cross-validation of geo-monitor's citation tracking against Otterly.AI's "
                   "commercial dashboard.",
        "cost": "paid subscription (Standard $189/mo for API access)",
    },
}


def build_report(cfg: "config_module.Config") -> dict:
    configured = cfg.available_integrations()

    rows = []
    for key, spec in config_module.INTEGRATION_ENV_VARS.items():
        env_vars = spec.get("any") or spec.get("all") or []
        if "any" in spec and len(env_vars) > 1:
            env_var_rule = "any one of these suffices"
        elif len(env_vars) > 1:
            env_var_rule = "all of these are required together"
        else:
            env_var_rule = "required"
        details = INTEGRATION_DETAILS.get(key, {})
        is_configured = bool(configured.get(key, False))
        rows.append({
            "integration": details.get("label", key),
            "key": key,
            "configured": is_configured,
            "env_vars": env_vars,
            "env_var_rule": env_var_rule,
            "how_to_configure": (details.get("how") or "See references/api-reference.md.")
                                if not is_configured else None,
            "unlocks": details.get("unlocks",
                                   "See references/api-reference.md for what this unlocks."),
            "cost": details.get("cost", "see references/api-reference.md"),
        })

    configured_count = sum(1 for r in rows if r["configured"])
    return {
        "site_url": cfg.site.get("site_url") if cfg.site else None,
        "summary": f"{configured_count}/{len(rows)} optional integrations configured "
                   f"(zero are required — every row derives from scripts/lib/config.py's "
                   f"INTEGRATION_ENV_VARS via Config.available_integrations()).",
        "integrations": rows,
        "note": "google_search_console and pagespeed_insights are the free backbone — "
                "prioritize configuring those first if any budget for setup effort exists. "
                "IndexNow is the free next step; everything else is a paid, optional "
                "extension. See references/api-reference.md for full auth/quota details "
                "on each.",
    }


def render_table(report: dict) -> str:
    lines = []
    lines.append(report["summary"])
    lines.append("")
    header = f"{'Integration':<44} {'Status':<12} {'Env var(s)':<58} Cost"
    lines.append(header)
    lines.append("-" * len(header))
    for row in report["integrations"]:
        status = "configured" if row["configured"] else "MISSING"
        joiner = " | " if row["env_var_rule"].startswith("any") else " + "
        env = joiner.join(row["env_vars"])
        lines.append(f"{row['integration']:<44} {status:<12} {env:<58} {row['cost']}")
    lines.append("")
    lines.append("Env var(s) column: 'A | B' = either one suffices; 'A + B' = both required together.")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Report which optional seo-engine integrations are configured."
    )
    parser.add_argument(
        "--format", choices=["json", "table"], default="json",
        help="Output format (default: json, for agent consumption).",
    )
    args = parser.parse_args()

    cfg = config_module.load()
    report = build_report(cfg)

    if args.format == "table":
        print(render_table(report))
    else:
        json.dump(report, sys.stdout, indent=2)
        print()
