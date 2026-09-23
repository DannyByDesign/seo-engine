"""pub-curate: build and maintain a publication's topic map — the pillars
(= the site's sections) and their spokes (candidate articles) that the
planner writes from.

Spoke record (mirrors the vendor's planner_topics — publication-playbook §4):
  id, subtopic, angle, brief (one-sentence reader benefit), status
  open|queued|covered|dismissed, client_relevance high|medium|low, source
  ai|user|competitor|seo|geo|social|seer, seo_keyword, seo_msv, seo_kd,
  article_slug, created_at, queued_at, covered_at

Generation: with OPENROUTER_API_KEY, spokes are drafted per pillar from the
strategy (direction, priority topics, stances, avoid list, client
description), the competitor inventory (gaps to fill) and the posts already
published (never duplicate). Without one, spokes come from competitor
topics mapped to pillars by term overlap plus the priority topics — weaker
but honest and deterministic. Existing spokes and their statuses always
survive a --refresh; duplicates are folded by term overlap.

--mark-covered reconciles the map with posts/ and drafts/ (by spoke_id in
frontmatter, else by title overlap) so a spoke is never written twice.

Usage:
    python3 build_topic_map.py --publication llm-billboard                 # first build
    python3 build_topic_map.py --publication llm-billboard --refresh        # add spokes, keep statuses
    python3 build_topic_map.py --publication llm-billboard --mark-covered
    python3 build_topic_map.py --publication llm-billboard --add "Deal ID structures for private AI supply" --pillar campaign-setup
    python3 build_topic_map.py --publication llm-billboard --dismiss sp-0007
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
from scripts.lib import config as config_module

import argparse
import json
from typing import Any, Optional

from scripts.lib import dataforseo, http_util, llm, publication, pubstate
from scripts.lib.config import Config

DUPLICATE_THRESHOLD = 0.6
COVERED_THRESHOLD = 0.7
MAP_SYSTEM = (
    "You plan the topic map of an independent trade publication: for each pillar (a site section) propose spokes — "
    "distinct, specific article subjects that build topical authority and that a buyer in the client's category would "
    "search or ask an AI assistant about. Each spoke: subtopic (a specific subject, 5-12 words, not a headline), angle "
    "(the point of view or framework the article will take, one sentence), brief (one sentence naming the concrete "
    "reader benefit), client_relevance high|medium|low (how naturally the client's product is part of this subject), "
    "seo_keyword (the 2-5 word query it targets, or null for a pure authority piece). Cover the priority topics, honor "
    "the stances, obey the avoid list, fill gaps competitors cover, and never repeat a subject already published. "
    "Return ONLY JSON: {\"pillars\": [{\"slug\": str, \"spokes\": [{subtopic, angle, brief, client_relevance, seo_keyword}]}]}."
)


def _pillars_from_site(pub: publication.Publication, strategy: dict[str, Any], existing: dict[str, Any]) -> list[dict[str, Any]]:
    by_slug = {p["slug"]: p for p in existing.get("pillars", [])}
    priority_terms = " ".join(strategy.get("priority_topics", []))
    pillars = []
    for s in pub.sections:
        old = by_slug.get(s["slug"], {})
        pillars.append({
            "slug": s["slug"], "name": s["name"], "description": s.get("description", ""),
            "is_priority": old.get("is_priority", pubstate.overlap(s["name"] + " " + s.get("description", ""), priority_terms) > 0.1 or not priority_terms),
            "is_muted": old.get("is_muted", False), "spokes": list(old.get("spokes", [])),
        })
    for slug, old in by_slug.items():
        if slug not in {p["slug"] for p in pillars}:
            old["is_muted"] = True
            pillars.append(old)
    return pillars


def _competitor_topics(root: Path) -> list[dict[str, Any]]:
    rows = []
    for f in sorted(pubstate.competitors_dir(root).glob("*.json")):
        data = pubstate.load_json(f, {})
        for t in data.get("topics", []):
            rows.append({**t, "competitor": data.get("name") or f.stem})
    return rows


def _existing_titles(pub: publication.Publication, root: Path) -> list[str]:
    titles = [p.title for p in pub.posts]
    for md in sorted((root / "drafts").glob("*.md")):
        meta, _ = publication.read_post(md)
        if meta.get("title"):
            titles.append(str(meta["title"]))
    return titles


def _add_spoke(topic_map: dict[str, Any], pillar: dict[str, Any], spoke: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Add unless a near-duplicate exists anywhere in the map."""
    text = spoke["subtopic"]
    for _, s in pubstate.all_spokes(topic_map):
        if pubstate.overlap(text, s["subtopic"]) >= DUPLICATE_THRESHOLD:
            return None
    record = {
        "id": pubstate.next_spoke_id(topic_map), "subtopic": text, "angle": spoke.get("angle") or "",
        "brief": spoke.get("brief") or "", "status": "open",
        "client_relevance": spoke.get("client_relevance") if spoke.get("client_relevance") in ("high", "medium", "low") else "medium",
        "source": spoke.get("source") or "ai", "seo_keyword": (spoke.get("seo_keyword") or None),
        "seo_msv": spoke.get("seo_msv"), "seo_kd": spoke.get("seo_kd"), "article_slug": None,
        "created_at": pubstate.now_iso(),
    }
    pillar.setdefault("spokes", []).append(record)
    return record


def spokes_from_llm(cfg: Config, pub: publication.Publication, strategy: dict[str, Any], topic_map: dict[str, Any],
                    per_pillar: int, competitor_topics: list[dict[str, Any]], existing_titles: list[str]) -> tuple[int, list[str]]:
    pillars_desc = "\n".join(
        f"- {p['slug']}: {p['name']} — {p.get('description') or ''} (open spokes now: "
        f"{sum(1 for s in p.get('spokes', []) if s.get('status') == 'open')})" for p in topic_map["pillars"] if not p.get("is_muted"))
    comp = "\n".join(f"- {t['title']} [{t.get('keyword_priority', 'medium')}] ({t['competitor']})" for t in competitor_topics[:60]) or "(none scraped)"
    have = "\n".join(f"- {t}" for t in existing_titles[:60]) or "(nothing yet)"
    current = "\n".join(f"- {s['subtopic']}" for _, s in pubstate.all_spokes(topic_map)) or "(empty)"
    client = strategy.get("client", {})
    user = (
        f"Publication: {pub.name} — {pub.tagline}\nClient: {client.get('name')} ({client.get('domain')}): {client.get('description')}\n"
        f"Direction: {strategy.get('direction')}\nPriority topics: {strategy.get('priority_topics')}\nStances: {strategy.get('stances')}\n"
        f"Avoid: {strategy.get('avoid_topics')}\nRanking targets: {[t.get('phrase') for t in strategy.get('ranking_targets', [])]}\n\n"
        f"Pillars (propose {per_pillar} NEW spokes each):\n{pillars_desc}\n\nSpokes already on the map (do not repeat):\n{current}\n\n"
        f"Already published or drafted (do not repeat):\n{have}\n\nCompetitor coverage to out-do or fill gaps in:\n{comp}"
    )
    data = llm.complete_json(cfg, MAP_SYSTEM, user, max_tokens=12000)
    added = 0
    notes: list[str] = []
    by_slug = {p["slug"]: p for p in topic_map["pillars"]}
    for entry in data.get("pillars", []) if isinstance(data, dict) else []:
        pillar = by_slug.get(str(entry.get("slug")))
        if pillar is None:
            notes.append(f"LLM proposed spokes for unknown pillar {entry.get('slug')!r}; skipped")
            continue
        for spoke in entry.get("spokes", []):
            if isinstance(spoke, dict) and spoke.get("subtopic"):
                spoke["source"] = "ai"
                if _add_spoke(topic_map, pillar, spoke):
                    added += 1
    return added, notes


def spokes_from_heuristics(strategy: dict[str, Any], topic_map: dict[str, Any], competitor_topics: list[dict[str, Any]],
                           per_pillar: int) -> int:
    pillars = [p for p in topic_map["pillars"] if not p.get("is_muted")]
    if not pillars:
        return 0
    added = 0
    counts = {p["slug"]: 0 for p in pillars}

    def pillar_for(text: str) -> dict[str, Any]:
        best, best_p = -1.0, pillars[0]
        for p in pillars:
            score = pubstate.overlap(text, f"{p['name']} {p.get('description', '')}")
            if score > best:
                best, best_p = score, p
        return best_p

    for topic in strategy.get("priority_topics", []):
        p = pillar_for(topic)
        if counts[p["slug"]] < per_pillar and _add_spoke(topic_map, p, {"subtopic": str(topic), "brief": f"Own the priority topic: {topic}.",
                                                                          "client_relevance": "high", "source": "user"}):
            counts[p["slug"]] += 1
            added += 1
    ranked = sorted(competitor_topics, key=lambda t: {"high": 0, "medium": 1, "low": 2}.get(t.get("keyword_priority"), 1))
    for t in ranked:
        p = pillar_for(t["title"])
        if counts[p["slug"]] >= per_pillar:
            continue
        rel = {"high": "high", "medium": "medium", "low": "low"}.get(t.get("keyword_priority"), "medium")
        if _add_spoke(topic_map, p, {"subtopic": t["title"], "brief": f"Competitor {t['competitor']} covers this; write the more useful version.",
                                     "client_relevance": rel, "source": "competitor", "seo_keyword": t.get("inferred_keyword"),
                                     "seo_msv": t.get("msv"), "seo_kd": t.get("kd")}):
            counts[p["slug"]] += 1
            added += 1
    return added


def enrich_volume(cfg: Config, topic_map: dict[str, Any]) -> list[str]:
    if not cfg.integration_available("dataforseo"):
        return ["DATAFORSEO_LOGIN/PASSWORD not set — spokes carry no volume/difficulty"]
    pending = [s for _, s in pubstate.all_spokes(topic_map) if s.get("seo_keyword") and s.get("seo_msv") is None]
    keywords = sorted({s["seo_keyword"] for s in pending})
    if not keywords:
        return []
    data = dataforseo.volume_and_difficulty(cfg, keywords)
    for s in pending:
        row = data.get(s["seo_keyword"])
        if row:
            s["seo_msv"], s["seo_kd"] = row["msv"], row["kd"]
    return []


def mark_covered(pub: publication.Publication, root: Path, topic_map: dict[str, Any]) -> int:
    marked = 0
    entries: list[tuple[str, str, Optional[str]]] = [(p.title, p.slug, str(p.meta.get("spoke_id") or "") or None) for p in pub.posts]
    for md in sorted((root / "drafts").glob("*.md")):
        meta, _ = publication.read_post(md)
        entries.append((str(meta.get("title") or md.stem), str(meta.get("slug") or md.stem), str(meta.get("spoke_id") or "") or None))
    for title, slug, spoke_id in entries:
        target = pubstate.find_spoke(topic_map, spoke_id) if spoke_id else None
        if target is None:
            best, best_spoke = 0.0, None
            for _, s in pubstate.all_spokes(topic_map):
                score = pubstate.overlap(title, s["subtopic"])
                if score > best:
                    best, best_spoke = score, s
            target = best_spoke if best >= COVERED_THRESHOLD else None
        if target is not None and target.get("status") != "covered":
            target.update({"status": "covered", "article_slug": slug, "covered_at": pubstate.now_iso()})
            marked += 1
    return marked


def summary(topic_map: dict[str, Any]) -> dict[str, Any]:
    spokes = [s for _, s in pubstate.all_spokes(topic_map)]
    return {"pillars": len(topic_map["pillars"]), "spokes": len(spokes),
            **{st: sum(1 for s in spokes if s.get("status") == st) for st in ("open", "queued", "covered", "dismissed")}}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build/refresh a publication's topic map (pillars + spokes).")
    parser.add_argument("--publication", help="Publication slug")
    parser.add_argument("--spokes-per-pillar", type=int, default=10, help="New spokes to propose per pillar (default 10)")
    parser.add_argument("--refresh", action="store_true", help="Propose more spokes into an existing map (statuses kept)")
    parser.add_argument("--no-llm", action="store_true", help="Heuristic spokes from competitors + priority topics only")
    parser.add_argument("--no-volume", action="store_true", help="Skip DataForSEO volume/difficulty enrichment")
    parser.add_argument("--mark-covered", action="store_true", help="Reconcile spokes with posts/ and drafts/")
    parser.add_argument("--add", help="Add one spoke (subtopic text) with source=user")
    parser.add_argument("--pillar", help="Pillar slug for --add (default: best-matching pillar)")
    parser.add_argument("--brief", help="Reader-benefit sentence for --add")
    parser.add_argument("--dismiss", help="Dismiss a spoke by id")
    parser.add_argument("--publications-dir", help="Override the publications directory")
    args = parser.parse_args()

    cfg = config_module.load()
    if args.publications_dir:
        cfg.site["publications_dir"] = args.publications_dir
    root = publication.find_publication(cfg, args.publication)
    pub = publication.load_publication(root)
    strategy = pubstate.load_strategy(root)
    existing = pubstate.load_topic_map(root)
    topic_map = {"publication": root.name, "generated_at": existing.get("generated_at") or pubstate.now_iso(),
                 "pillars": _pillars_from_site(pub, strategy, existing)}
    result: dict[str, Any] = {"checked": True, "publication": root.name, "topic_map_file": str(pubstate.topic_map_path(root)), "notes": []}

    if args.dismiss:
        spoke = pubstate.find_spoke(topic_map, args.dismiss)
        if spoke is None:
            parser.error(f"no spoke {args.dismiss}")
        spoke["status"] = "dismissed"
        result["dismissed"] = args.dismiss
    if args.add:
        pillar = next((p for p in topic_map["pillars"] if p["slug"] == args.pillar), None) if args.pillar else None
        if pillar is None:
            best, pillar = -1.0, topic_map["pillars"][0]
            for p in topic_map["pillars"]:
                score = pubstate.overlap(args.add, f"{p['name']} {p.get('description', '')}")
                if score > best:
                    best, pillar = score, p
        added = _add_spoke(topic_map, pillar, {"subtopic": args.add, "brief": args.brief or "", "client_relevance": "high", "source": "user"})
        result["added"] = added["id"] if added else None
        if not added:
            result["notes"].append("a near-duplicate spoke already exists; nothing added")

    fresh = not pubstate.all_spokes(topic_map)
    if fresh or args.refresh:
        competitor_topics = _competitor_topics(root)
        existing_titles = _existing_titles(pub, root)
        if args.no_llm or not llm.configured_providers(cfg):
            if not args.no_llm:
                result["notes"].append("no OPENROUTER_API_KEY configured — heuristic spokes only (competitor titles + priority topics)")
            result["spokes_added"] = spokes_from_heuristics(strategy, topic_map, competitor_topics, args.spokes_per_pillar)
        else:
            try:
                result["spokes_added"], notes = spokes_from_llm(cfg, pub, strategy, topic_map, args.spokes_per_pillar, competitor_topics, existing_titles)
                result["notes"] += notes
            except llm.LlmError as exc:
                result["notes"].append(f"LLM map generation failed ({http_util.sanitize_text(str(exc))[:160]}); falling back to heuristics")
                result["spokes_added"] = spokes_from_heuristics(strategy, topic_map, competitor_topics, args.spokes_per_pillar)
        if not result["spokes_added"] and not pubstate.all_spokes(topic_map):
            result["notes"].append("no spokes yet — set priority_topics (pub-strategy positioning.py --apply), scrape competitors "
                                   "(scrape_competitors.py), configure OPENROUTER_API_KEY, or --add one by hand; the planner cannot queue an empty map")
        if not args.no_volume:
            result["notes"] += enrich_volume(cfg, topic_map)
    if args.mark_covered or fresh or args.refresh:
        result["marked_covered"] = mark_covered(pub, root, topic_map)

    pubstate.save_topic_map(root, topic_map)
    result["summary"] = summary(topic_map)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
