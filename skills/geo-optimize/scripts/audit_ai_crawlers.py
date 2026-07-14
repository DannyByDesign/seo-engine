"""geo-optimize: AI-crawler robots.txt audit.

Fetches the target site's robots.txt and evaluates it against the exact
per-vendor table in references/geo-playbook.md §4. This is NOT a generic
"block/allow all AI bots" toggle — different crawlers from the same vendor
serve completely different purposes, and treating them as one category is
exactly the mistake this script exists to catch (red-flags.md §5, "Blocking
the wrong AI crawler").

Parsing/evaluation is delegated to scripts.lib.robots, which is RFC 9309
correct: ALL matching groups merge (keeping only the last matching group
produces false "not blocked" verdicts), empty Allow/Disallow patterns match
nothing, longest-match wins with Allow breaking ties, and a 4xx robots.txt
means "no restrictions exist" — a missing robots.txt is a benign,
zero-findings outcome, not an error.

Three classes of finding, deliberately kept separate:

  1. CITATION-RELEVANT crawlers blocked at the site root (real GEO cost) —
     OAI-SearchBot, ChatGPT-User, Claude-SearchBot, Claude-User,
     PerplexityBot, Perplexity-User, Bingbot, BingPreview, Amazonbot, and
     standard Googlebot. Emitted as `severity: high` findings.

  2. CITATION-RELEVANT crawlers partially blocked (`severity: medium`) —
     the bot is allowed at `/` but robots.txt disallows specific paths for
     it (e.g. `Disallow: /blog/`). If those paths cover citable content,
     the same blocking cost applies to just those sections.

  3. TRAINING-ONLY crawlers blocked (informational, not a problem) —
     GPTBot, ClaudeBot, Google-Extended, Applebot-Extended. Blocking these
     affects ONLY model-training data collection and has zero documented
     effect on citation visibility. Many sites block these intentionally
     (a legitimate content-licensing/training-opt-out choice unrelated to
     GEO). Reported as `severity: info`; this script explicitly does NOT
     recommend unblocking them.

Usage:
    python3 audit_ai_crawlers.py
    python3 audit_ai_crawlers.py --url https://example.com
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urljoin


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
from scripts.lib import http_util, robots, snapshots  # noqa: E402
from scripts.lib.config import MissingConfigError  # noqa: E402


# ---------------------------------------------------------------------------
# The exact per-vendor table from references/geo-playbook.md §4.
# Every user-agent token a real AI/search vendor publishes for crawling.
# ---------------------------------------------------------------------------

# Crawlers whose purpose is powering live citations/search answers/indexing
# used for citation. Blocking these has a real, documented GEO cost.
CITATION_RELEVANT = {
    "OAI-SearchBot": {
        "vendor": "OpenAI",
        "purpose": "Powers ChatGPT search citations",
        "blocking_effect": (
            "Site excluded from ChatGPT search answers (may still appear as a "
            "bare navigational link)"
        ),
    },
    "ChatGPT-User": {
        "vendor": "OpenAI",
        "purpose": "Live fetch during user actions/browsing",
        "blocking_effect": "Breaks live-fetch features, not indexing",
    },
    "Claude-SearchBot": {
        "vendor": "Anthropic",
        "purpose": "Indexing for Claude's search quality",
        "blocking_effect": (
            "Blocking reduces/prevents indexing -> less visibility and "
            "accuracy in citations"
        ),
    },
    "Claude-User": {
        "vendor": "Anthropic",
        "purpose": "Live fetch for user-directed web search",
        "blocking_effect": "Blocking reduces visibility for user-directed queries",
    },
    "PerplexityBot": {
        "vendor": "Perplexity",
        "purpose": "Builds/refreshes the citation index",
        "blocking_effect": (
            "Blocking excludes from citations (page may still show as "
            "domain/headline/summary). NOTE: Cloudflare has documented "
            "undeclared 'stealth' Perplexity-adjacent crawlers evading "
            "robots.txt blocks entirely -- a disputed, unresolved pattern "
            "per geo-playbook.md §4 -- so a block here is not an airtight "
            "guarantee of exclusion either way."
        ),
    },
    "Perplexity-User": {
        "vendor": "Perplexity",
        "purpose": "Live fetch",
        "blocking_effect": "Affects live-fetch, not the standing index",
    },
    "Amazonbot": {
        "vendor": "Amazon",
        "purpose": "Indexing for Alexa/search answers",
        "blocking_effect": "Blocking removes from Alexa/search answer citations",
    },
    "Bingbot": {
        "vendor": "Bing/Copilot",
        "purpose": "Single unified crawler and index",
        "blocking_effect": (
            "Blocking removes the site from BOTH classic Bing results and "
            "Copilot citations at once -- there is no separate training-only "
            "bot to block selectively"
        ),
    },
    "BingPreview": {
        "vendor": "Bing/Copilot",
        "purpose": "Single unified crawler and index",
        "blocking_effect": (
            "Blocking removes the site from BOTH classic Bing results and "
            "Copilot citations at once -- there is no separate training-only "
            "bot to block selectively"
        ),
    },
    "Googlebot": {
        "vendor": "Google",
        "purpose": "Same index powers AI Overviews/AI Mode",
        "blocking_effect": (
            "Google states there are no additional crawl requirements for AI "
            "Overviews -- it uses the standard Search index, so blocking "
            "Googlebot removes the site from classic Search AND AI Overviews/"
            "AI Mode simultaneously"
        ),
    },
}

# Crawlers whose purpose is model-training/grounding-data collection only.
# Blocking these is a legitimate, unrelated choice this skill must NOT
# second-guess -- reported informationally, never as a "fix this" finding.
TRAINING_ONLY = {
    "GPTBot": {
        "vendor": "OpenAI",
        "purpose": "Model training only",
        "blocking_effect": "No effect on ChatGPT search/citation",
    },
    "ClaudeBot": {
        "vendor": "Anthropic",
        "purpose": "Model training only",
        "blocking_effect": "No effect on Claude's live web-search citations",
    },
    "Google-Extended": {
        "vendor": "Google",
        "purpose": "Training/grounding data for the Gemini app & Vertex AI",
        "blocking_effect": (
            "Does not affect AI Overview/AI Mode inclusion or ranking -- you "
            "cannot opt out of AI Overviews without opting out of Search "
            "entirely"
        ),
    },
    "Applebot-Extended": {
        "vendor": "Apple",
        "purpose": "Training/Apple Intelligence generation (opt-out model)",
        "blocking_effect": (
            "Blocking doesn't affect regular Applebot, which still powers "
            "Siri/Spotlight/Safari results"
        ),
    },
}

ALL_KNOWN_BOTS = {**CITATION_RELEVANT, **TRAINING_ONLY}

HUMAN_REVIEW_REASON = (
    "Whether to allow this crawler is a site-owner policy decision "
    "(e.g. some sites deliberately keep AI crawlers out for legal/"
    "capacity reasons even at a citation-visibility cost) -- this "
    "script surfaces the tradeoff, it does not decide it."
)


def _matches_root(pattern: str) -> bool:
    """True if a robots pattern matches the root path `/` under lib/robots
    semantics (`*` = any chars, trailing `$` = end anchor, empty = matches
    nothing). Used only for *reporting* which rule blocks the root — the
    verdict itself always comes from policy.allowed()."""
    return bool(pattern) and pattern.strip("*$") in ("", "/")


def _bot_group_view(policy: "robots.RobotsPolicy", bot_name: str) -> dict:
    """How robots.txt addresses this bot: via exact group(s), the wildcard
    group, or not at all — plus the agent tokens of the groups that apply
    (RFC 9309: all matching groups merge; exact groups shadow the wildcard)."""
    token = bot_name.casefold()
    exact = [g for g in policy.groups if token in g.agents]
    wildcard = [g for g in policy.groups if "*" in g.agents]
    used = exact if exact else wildcard
    matched_via = "exact" if exact else ("wildcard" if wildcard else "none")
    agents = sorted({agent for g in used for agent in g.agents})
    return {"matched_via": matched_via, "agents": agents}


def _root_blocking_rule(policy: "robots.RobotsPolicy", bot_name: str) -> str:
    """Human-readable rule text for a bot blocked at `/`: the longest
    root-matching Disallow pattern in the bot's merged rule set."""
    view = _bot_group_view(policy, bot_name)
    candidates = [
        p for kind, p in policy.rules_for(bot_name)
        if kind == "disallow" and _matches_root(p)
    ]
    if not candidates:
        return ""
    pattern = max(candidates, key=len)
    return f"User-agent: {', '.join(view['agents'])} / Disallow: {pattern}"


def audit(site_url: str) -> dict:
    robots_url = urljoin(site_url.rstrip("/") + "/", "robots.txt")
    result: dict = {
        "site_url": site_url,
        "robots_txt_url": robots_url,
        "fetched": False,
        "findings": [],
        "training_only_notes": [],
    }

    def _finish(res: dict) -> dict:
        res["severity_counts"] = {
            "high": sum(1 for f in res["findings"] if f["severity"] == "high"),
            "medium": sum(1 for f in res["findings"] if f["severity"] == "medium"),
            "info": len(res["training_only_notes"]),
        }
        return res

    try:
        resp = http_util.get(robots_url, min_interval=0.5)
    except http_util.HttpError as exc:
        # Network failure: we honestly do not know what the policy says.
        result["effective"] = "indeterminate"
        result["error"] = str(exc)  # pre-sanitized by http_util
        result["note"] = (
            "robots.txt could not be fetched (network error) -- the actual "
            "policy is unknown, so no per-bot verdicts were computed. Re-run "
            "when the site is reachable."
        )
        return _finish(result)

    result["fetched"] = True
    result["status_code"] = resp.status_code

    if resp.status_code >= 500:
        # 5xx: unreadable, NOT the same as "no restrictions". Honest
        # indeterminate outcome — zero findings, zero false reassurance.
        result["effective"] = "indeterminate"
        result["note"] = (
            f"robots.txt returned HTTP {resp.status_code} -- the actual policy "
            "is unreadable, so no per-bot verdicts were computed (RFC 9309 "
            "treats an unreadable robots.txt as disallow-all for crawling, "
            "but auditing cannot verify vendor access either way). Re-run "
            "when the server recovers."
        )
        return _finish(result)

    if resp.status_code >= 400:
        # RFC 9309 §2.3.1: 4xx means no robots restrictions exist. A missing
        # robots.txt blocks nothing — benign, zero findings, not an error.
        result["effective"] = "allow_all"
        if resp.status_code == 404:
            result["note"] = (
                "no robots.txt — nothing blocked (RFC 9309: 4xx = unrestricted)"
            )
        else:
            result["note"] = (
                f"robots.txt returned HTTP {resp.status_code} — treated as "
                "unrestricted (RFC 9309: 4xx = no robots restrictions exist); "
                "nothing is blocked by robots.txt"
            )
        return _finish(result)

    result["effective"] = "parsed"
    policy = robots.parse(resp.text or "", source_status=resp.status_code)
    result["groups_found"] = [
        {"agents": g.agents, "rule_count": len(g.rules)} for g in policy.groups
    ]
    if policy.sitemaps:
        result["sitemaps_declared"] = policy.sitemaps

    for bot_name, meta in CITATION_RELEVANT.items():
        view = _bot_group_view(policy, bot_name)
        root_allowed = policy.allowed(bot_name, site_url)
        if not root_allowed:
            result["findings"].append({
                "type": "citation_relevant_crawler_blocked",
                "severity": "high",
                "bot": bot_name,
                "vendor": meta["vendor"],
                "purpose": meta["purpose"],
                "blocking_effect": meta["blocking_effect"],
                "matched_via": view["matched_via"],
                "blocking_rule": _root_blocking_rule(policy, bot_name),
                "detail": (
                    f"{bot_name} ({meta['vendor']}) is blocked at the site root via "
                    f"{'a bot-specific rule' if view['matched_via'] == 'exact' else 'the wildcard (*) rule'} "
                    f"in robots.txt. {meta['purpose']}. {meta['blocking_effect']}"
                ),
                "geo_playbook_ref": "geo-playbook.md §4 (AI crawler access: precise, per-vendor guidance)",
                "red_flags_ref": "red-flags.md §5 (Blocking the wrong AI crawler)",
                "auto_fixable": False,
                "human_review_reason": HUMAN_REVIEW_REASON,
            })
            continue

        # Allowed at "/" but disallowed from specific paths — a real partial
        # block (e.g. Disallow: /blog/ still costs citations for /blog/).
        partial_paths = sorted(
            {p for p in policy.disallowed_paths(bot_name) if not _matches_root(p)}
        )
        if partial_paths:
            result["findings"].append({
                "type": "citation_relevant_partial_block",
                "severity": "medium",
                "bot": bot_name,
                "vendor": meta["vendor"],
                "purpose": meta["purpose"],
                "blocking_effect": meta["blocking_effect"],
                "matched_via": view["matched_via"],
                "disallowed_paths": partial_paths,
                "detail": (
                    f"{bot_name} ({meta['vendor']}) is allowed at the site root but "
                    f"disallowed from {len(partial_paths)} path pattern(s) "
                    f"({', '.join(partial_paths)}) via "
                    f"{'a bot-specific rule' if view['matched_via'] == 'exact' else 'the wildcard (*) rule'} "
                    f"in robots.txt. {meta['purpose']}. If these paths cover content "
                    f"that should be citable, the documented blocking cost applies to "
                    f"just those sections: {meta['blocking_effect']}"
                ),
                "geo_playbook_ref": "geo-playbook.md §4 (AI crawler access: precise, per-vendor guidance)",
                "red_flags_ref": "red-flags.md §5 (Blocking the wrong AI crawler)",
                "auto_fixable": False,
                "human_review_reason": (
                    "Path-level disallows are often deliberate (admin areas, "
                    "search results, cart pages). Review whether the listed "
                    "paths cover content that matters for citations before "
                    "treating this as a misconfiguration. "
                ) + HUMAN_REVIEW_REASON,
            })

    for bot_name, meta in TRAINING_ONLY.items():
        view = _bot_group_view(policy, bot_name)
        if not policy.allowed(bot_name, site_url):
            result["training_only_notes"].append({
                "type": "training_only_crawler_blocked",
                "severity": "info",
                "bot": bot_name,
                "vendor": meta["vendor"],
                "purpose": meta["purpose"],
                "blocking_effect": meta["blocking_effect"],
                "matched_via": view["matched_via"],
                "detail": (
                    f"{bot_name} ({meta['vendor']}) is blocked. This affects ONLY "
                    f"{meta['purpose'].lower()} and has zero documented effect on "
                    "AI-search citation visibility. This is commonly an intentional, "
                    "legitimate choice (opting out of training-data collection) -- "
                    "this script does not recommend changing it."
                ),
                "geo_playbook_ref": "geo-playbook.md §4",
            })
            continue

        partial_paths = sorted(
            {p for p in policy.disallowed_paths(bot_name) if not _matches_root(p)}
        )
        if partial_paths:
            result["training_only_notes"].append({
                "type": "training_only_partial_block",
                "severity": "info",
                "bot": bot_name,
                "vendor": meta["vendor"],
                "purpose": meta["purpose"],
                "matched_via": view["matched_via"],
                "disallowed_paths": partial_paths,
                "detail": (
                    f"{bot_name} ({meta['vendor']}) is allowed at the site root but "
                    f"disallowed from {len(partial_paths)} path pattern(s) "
                    f"({', '.join(partial_paths)}). This affects ONLY "
                    f"{meta['purpose'].lower()} for those paths and has zero "
                    "documented effect on AI-search citation visibility -- this "
                    "script does not recommend changing it."
                ),
                "geo_playbook_ref": "geo-playbook.md §4",
            })

    # Sanity-check: any group targeting a bot name not in our known table at
    # all (e.g. a typo'd user-agent, or a real bot this table hasn't been
    # updated for) -- surfaced as a note so a human can decide whether the
    # playbook table needs updating, never silently dropped. (lib/robots
    # lowercases agent tokens; matching is casefolded on both sides.)
    known_lower = {b.casefold() for b in ALL_KNOWN_BOTS}
    unknown_agents = sorted({
        agent for g in policy.groups for agent in g.agents
        if agent.casefold() not in known_lower and agent != "*"
    })
    if unknown_agents:
        result["unrecognized_user_agents"] = unknown_agents

    return _finish(result)


def main() -> None:
    import argparse
    import time

    parser = argparse.ArgumentParser(
        description="Audit robots.txt against the per-vendor AI-crawler table (geo-playbook.md §4)"
    )
    parser.add_argument("--url", help="Site URL (defaults to .seo-engine/config.yml site_url)")
    args = parser.parse_args()

    cfg = config_module.load()
    snapshots.prune(cfg)
    try:
        site_url = args.url or cfg.site_url
    except MissingConfigError as exc:
        result = {
            "fetched": False,
            "error": (
                f"No site URL configured: {exc}. Pass --url https://example.com, "
                "or run the seo-setup skill to write .seo-engine/config.yml, or "
                "export SEO_SITE_URL."
            ),
        }
        json.dump(result, sys.stdout, indent=2)
        print()
        sys.exit(1)

    result = audit(site_url)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    report_path = cfg.reports_dir / f"geo-ai-crawler-audit-{stamp}.json"
    report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    state_path = cfg.state_dir / "geo-ai-crawler-audit-last-run.json"
    state_path.write_text(json.dumps({
        "site_url": site_url,
        "fetched": result.get("fetched", False),
        "effective": result.get("effective", ""),
        "severity_counts": result.get("severity_counts", {}),
        "report_path": str(report_path),
    }, indent=2), encoding="utf-8")

    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
