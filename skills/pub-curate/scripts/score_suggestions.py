"""pub-curate: score open spokes and emit a ranked queue of headline
suggestions — the vendor's Curate step (publication-playbook §4).

Signals, each 0..1, weighted into one score with a per-signal breakdown so a
human can see WHY a headline ranks:
  competitor      a competitor covers this subject (weighted by its priority)
  geo             an AI-assistant prompt where a competitor is named and the
                  client is not (from pub-monitor's GEO opportunities state)
  seo             volume/difficulty on the spoke's keyword (log-scaled)
  cluster         pillar priority x client relevance
  authority       how under-covered the pillar is (build authority evenly)
  social          live conversation volume on the subject (SociaVault), cached
  cannibalization PENALTY: term overlap with anything already published or
                  drafted; >= 0.6 removes the spoke from the queue outright

Headlines: with an LLM key, each top spoke becomes a 6-11 word noun-phrase
title in the measured style ("X for Y", "X vs Y", "How X ...") plus a
one-sentence why; without one, the subtopic itself is the headline and the
brief is the why. Suggestions persist in .seo-engine/state so
pub-publish's planner can queue them; already-queued items are kept.

Usage:
    python3 score_suggestions.py --publication llm-billboard
    python3 score_suggestions.py --publication llm-billboard --target 15 --no-social
"""

from __future__ import annotations

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
import math  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from typing import Any  # noqa: E402

from scripts.lib import http_util, llm, publication, pubstate, sociavault  # noqa: E402
from scripts.lib.config import Config  # noqa: E402

WEIGHTS = {"competitor": 0.15, "geo": 0.20, "seo": 0.15, "cluster": 0.15, "authority": 0.15, "social": 0.10}
CANNIBAL_PENALTY = 0.30
CANNIBAL_DROP = 0.60
CANNIBAL_SOFT = 0.40
RELEVANCE = {"high": 1.0, "medium": 0.7, "low": 0.4}
PRIORITY = {"high": 1.0, "medium": 0.7, "low": 0.4}
SOCIAL_CACHE_HOURS = 24
HEADLINE_SYSTEM = (
    "You write headlines for an independent trade publication. Given article subjects with angles, return for each a "
    "headline of 6-11 words in the house style: a specific noun phrase, no clickbait, no year, no colon-plus-teaser; "
    "shapes that work are 'X for Y', 'X vs Y', 'How X ...', 'What X Means for Y'. Also return `why`: one sentence on why "
    "this piece earns its place now. Return ONLY JSON: [{\"i\": number, \"headline\": string, \"why\": string}]."
)


def competitor_signal(spoke: dict[str, Any], competitor_topics: list[dict[str, Any]]) -> tuple[float, str]:
    if spoke.get("source") == "competitor":
        return 1.0, "spoke came from a competitor gap"
    best, hit = 0.0, ""
    for t in competitor_topics:
        score = pubstate.overlap(spoke["subtopic"], t.get("title", ""))
        if score >= 0.5:
            weighted = score * PRIORITY.get(t.get("keyword_priority"), 0.7)
            if weighted > best:
                best, hit = weighted, f"{t.get('competitor')}: {t.get('title')}"
    return min(best, 1.0), hit


def geo_signal(spoke: dict[str, Any], opportunities: list[dict[str, Any]]) -> tuple[float, str]:
    best, hit = 0.0, ""
    for o in opportunities:
        text = str(o.get("prompt_text") or o.get("prompt") or "")
        if pubstate.overlap(spoke["subtopic"] + " " + (spoke.get("seo_keyword") or ""), text) >= 0.4:
            gap = float(o.get("gap_score") or 0.5)
            if gap > best:
                best, hit = min(gap, 1.0), text[:120]
    return best, hit


def seo_signal(spoke: dict[str, Any]) -> float:
    msv = spoke.get("seo_msv")
    if not msv:
        return 0.0
    volume = min(1.0, math.log10(float(msv) + 1) / 4)
    kd = spoke.get("seo_kd")
    ease = 1.0 - (float(kd) / 100) * 0.5 if kd is not None else 0.75
    return round(volume * ease, 4)


def cluster_signal(pillar: dict[str, Any], spoke: dict[str, Any]) -> float:
    return round((1.0 if pillar.get("is_priority") else 0.5) * RELEVANCE.get(spoke.get("client_relevance"), 0.7), 4)


def authority_signal(pillar: dict[str, Any]) -> float:
    spokes = pillar.get("spokes", [])
    if not spokes:
        return 1.0
    covered = sum(1 for s in spokes if s.get("status") == "covered")
    return round(1.0 - covered / len(spokes), 4)


def cannibalization(spoke: dict[str, Any], existing_titles: list[str]) -> tuple[float, str]:
    best, hit = pubstate.best_overlap(spoke["subtopic"] + " " + (spoke.get("seo_keyword") or ""), existing_titles)
    return round(best, 4), hit or ""


def social_signal(cfg: Config, spoke: dict[str, Any], cache: dict[str, Any], *, refresh: bool) -> tuple[float, str, bool]:
    """Conversation volume for the spoke's keyword in the last week, cached
    for SOCIAL_CACHE_HOURS. Returns (signal, note, called_api)."""
    key = (spoke.get("seo_keyword") or spoke["subtopic"])[:80]
    entry = cache.get(key)
    if entry and not refresh:
        fetched = publication.parse_iso(entry.get("fetched_at"))
        if fetched and datetime.now(timezone.utc) - fetched < timedelta(hours=SOCIAL_CACHE_HOURS):
            return entry["signal"], entry.get("note", "cached"), False
    result = sociavault.search_conversations(cfg, key, platforms=("reddit", "twitter", "tiktok", "youtube"), limit=20)
    posts = result["posts"]
    engagement = sum(float(p.get("score") or 0) + 2 * float(p.get("comments") or 0) for p in posts)
    signal = min(1.0, len(posts) / 40 + min(engagement, 5000) / 10000)
    note = f"{len(posts)} posts across {', '.join(sorted({p['platform'] for p in posts})) or 'no platform'}; engagement {int(engagement)}"
    if result["errors"]:
        note += f"; errors: {list(result['errors'])}"
    cache[key] = {"signal": round(signal, 4), "note": note, "fetched_at": pubstate.now_iso(), "credits_used": result["credits_used"]}
    return round(signal, 4), note, True


def headlines(cfg: Config, items: list[dict[str, Any]]) -> None:
    if not items or not llm.configured_providers(cfg):
        return
    listing = "\n".join(f"{i}. subject: {it['subtopic']} | angle: {it.get('angle') or '-'} | brief: {it.get('brief') or '-'}"
                        for i, it in enumerate(items))
    try:
        data = llm.complete_json(cfg, HEADLINE_SYSTEM, listing, tier="cheap", max_tokens=4000)
    except llm.LlmError:
        return
    for row in data if isinstance(data, list) else data.get("items", []):
        try:
            it = items[int(row["i"])]
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        if row.get("headline"):
            it["headline"] = str(row["headline"]).strip()
        if row.get("why"):
            it["why"] = str(row["why"]).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Score open spokes into a ranked headline queue.")
    parser.add_argument("--publication", help="Publication slug")
    parser.add_argument("--target", type=int, default=10, help="Suggestions to emit (default 10)")
    parser.add_argument("--no-llm", action="store_true", help="Use subtopics as headlines (no LLM rewrite)")
    parser.add_argument("--no-social", action="store_true", help="Skip the SociaVault conversation signal")
    parser.add_argument("--refresh-social", action="store_true", help="Ignore the social cache and re-query")
    parser.add_argument("--publications-dir", help="Override the publications directory")
    args = parser.parse_args()

    cfg = config_module.load()
    if args.publications_dir:
        cfg.site["publications_dir"] = args.publications_dir
    root = publication.find_publication(cfg, args.publication)
    pub = publication.load_publication(root)
    topic_map = pubstate.load_topic_map(root)
    if not topic_map.get("pillars"):
        print(json.dumps({"checked": False, "error": "no topic map — run build_topic_map.py first"}, indent=2))
        return 1
    competitor_topics = []
    for f in sorted(pubstate.competitors_dir(root).glob("*.json")):
        data = pubstate.load_json(f, {})
        competitor_topics += [{**t, "competitor": data.get("name") or f.stem} for t in data.get("topics", [])]
    opportunities = pubstate.load_json(pubstate.state_path(cfg, "geo-opportunities", root.name), {}).get("items", [])
    existing_titles = [p.title for p in pub.posts]
    for md in (root / "drafts").glob("*.md"):
        meta, _ = publication.read_post(md)
        if meta.get("title"):
            existing_titles.append(str(meta["title"]))
    social_cache = pubstate.load_json(pubstate.state_path(cfg, "social-cache", root.name), {})
    social_on = not args.no_social and cfg.integration_available("sociavault")
    notes: list[str] = []
    if not opportunities:
        notes.append("no GEO opportunities state yet (pub-monitor writes it) — geo signal is 0 for every spoke")
    if not args.no_social and not cfg.integration_available("sociavault"):
        notes.append("SOCIAVAULT_API_KEY not set — social signal is 0")

    scored: list[dict[str, Any]] = []
    dropped = 0
    api_calls = 0
    for pillar, spoke in pubstate.all_spokes(topic_map):
        if spoke.get("status") != "open" or pillar.get("is_muted"):
            continue
        cannibal, cannibal_hit = cannibalization(spoke, existing_titles)
        if cannibal >= CANNIBAL_DROP:
            dropped += 1
            continue
        comp, comp_hit = competitor_signal(spoke, competitor_topics)
        geo, geo_hit = geo_signal(spoke, opportunities)
        breakdown = {"competitor": round(comp, 4), "geo": round(geo, 4), "seo": seo_signal(spoke),
                     "cluster": cluster_signal(pillar, spoke), "authority": authority_signal(pillar), "social": 0.0,
                     "cannibalization": cannibal}
        evidence = {"competitor": comp_hit, "geo": geo_hit, "cannibalization": cannibal_hit}
        scored.append({"spoke_id": spoke["id"], "pillar": pillar["slug"], "subtopic": spoke["subtopic"], "angle": spoke.get("angle"),
                       "brief": spoke.get("brief"), "seo_keyword": spoke.get("seo_keyword"), "client_relevance": spoke.get("client_relevance"),
                       "signal_breakdown": breakdown, "evidence": evidence})

    def total(item: dict[str, Any]) -> float:
        b = item["signal_breakdown"]
        score = sum(WEIGHTS[k] * b[k] for k in WEIGHTS)
        if b["cannibalization"] >= CANNIBAL_SOFT:
            score -= CANNIBAL_PENALTY * b["cannibalization"]
        return round(score, 4)

    for item in scored:
        item["score"] = total(item)
    scored.sort(key=lambda x: x["score"], reverse=True)
    if social_on:  # only spend credits on the plausible top of the list
        for item in scored[: max(args.target * 2, 10)]:
            spoke = pubstate.find_spoke(topic_map, item["spoke_id"]) or {}
            try:
                signal, note, called = social_signal(cfg, spoke, social_cache, refresh=args.refresh_social)
                api_calls += int(called)
                item["signal_breakdown"]["social"] = signal
                item["evidence"]["social"] = note
                item["score"] = total(item)
            except Exception as exc:  # noqa: BLE001
                item["evidence"]["social"] = http_util.sanitize_text(str(exc))[:120]
        pubstate.save_json(pubstate.state_path(cfg, "social-cache", root.name), social_cache)
        scored.sort(key=lambda x: x["score"], reverse=True)

    top = scored[: args.target]
    for item in top:
        item["headline"] = item["subtopic"] if item["subtopic"][:1].isupper() else item["subtopic"].capitalize()
        item["why"] = item.get("brief") or "Open spoke in a priority pillar."
    if not args.no_llm:
        headlines(cfg, top)

    state_path = pubstate.state_path(cfg, "suggestions", root.name)
    previous = pubstate.load_json(state_path, {})
    queued = [s for s in previous.get("items", []) if s.get("status") == "queued"]
    items = queued + [{"id": f"sg-{i + 1:04d}", "status": "suggested", "created_at": pubstate.now_iso(), **it} for i, it in enumerate(top)]
    pubstate.save_json(state_path, {"publication": root.name, "generated_at": pubstate.now_iso(), "items": items})
    report = {"checked": True, "publication": root.name, "suggestions_file": str(state_path), "target": args.target,
              "open_spokes_scored": len(scored), "dropped_as_cannibalizing": dropped, "social_api_calls": api_calls,
              "weights": WEIGHTS, "notes": notes,
              "suggestions": [{k: v for k, v in it.items() if k != "evidence"} | {"evidence": it["evidence"]} for it in top]}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
