"""pub-publish: the Planner — the recurring autopilot that turns the topic map
and the suggestion queue into dated publish slots (publication-playbook §4).

Configuration lives in site.yml under `planner:`:
  enabled, cadence_per_week (default 6 — the measured phantoms run ~1/day),
  sourcing_mode curate_first|topic_map|curate_only, approval_mode
  manual|review_window|autopilot, review_window_hours (24), publish_hour_utc
  (seeded per publication so a fleet never publishes in lockstep),
  jitter_minutes (45 — "de-robotized" times), launch_burst (4 — the measured
  first-day burst before the daily rhythm).

Slots live in .seo-engine/state/pub-planner-<slug>.json:
  {id, scheduled_for, status planned|queued|published|skipped, spoke_id,
   suggestion_id, headline, draft_slug, section}

Commands:
  --configure     write planner settings from flags
  --materialize   create slots for the next --days (default 14) on the cadence
  --queue         fill planned slots: suggestions first (curate_first), else
                  open spokes rotating across the least-covered pillars;
                  marks the spoke queued, creates drafts/<slug>.md with the brief
  --due           list slots whose time has come (what to run the pipeline on)
  (none)          status

Usage:
    python3 planner.py --publication llm-billboard --configure --cadence-per-week 6 --approval-mode manual
    python3 planner.py --publication llm-billboard --materialize --days 14 --queue
    python3 planner.py --publication llm-billboard --due
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
import hashlib  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from typing import Any, Optional  # noqa: E402

from scripts.lib import publication, pubstate  # noqa: E402

DEFAULT_PLANNER = {"enabled": True, "cadence_per_week": 6, "sourcing_mode": "curate_first", "approval_mode": "manual",
                   "review_window_hours": 24, "publish_hour_utc": None, "jitter_minutes": 45, "launch_burst": 4}


def planner_config(pub: publication.Publication) -> dict[str, Any]:
    conf = dict(DEFAULT_PLANNER)
    conf.update({k: v for k, v in (pub.site.get("planner") or {}).items() if v is not None})
    if conf.get("publish_hour_utc") is None:
        conf["publish_hour_utc"] = 12 + int(hashlib.sha256(pub.slug.encode()).hexdigest(), 16) % 10  # 12..21 UTC
    return conf


def save_planner_config(root: Path, conf: dict[str, Any]) -> None:
    site = pubstate.load_yaml(root / "site.yml", {})
    site["planner"] = conf
    pubstate.save_yaml(root / "site.yml", site)


def publish_days(cadence_per_week: int) -> set[int]:
    """Weekday numbers (0=Mon) for a cadence: spread across the week, weekends last."""
    order = [0, 2, 4, 1, 3, 5, 6]
    return set(order[: max(0, min(7, cadence_per_week))])


def materialize(state: dict[str, Any], conf: dict[str, Any], slug: str, *, days: int, published_count: int,
                now: Optional[datetime] = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    rng = random.Random(f"{slug}:{now.date().isoformat()}")
    existing_days = {s.get("cadence_day") or s["scheduled_for"][:10] for s in state.get("slots", [])}
    wanted = publish_days(int(conf["cadence_per_week"]))
    created = []
    burst_left = int(conf.get("launch_burst") or 0) if published_count == 0 and not state.get("slots") else 0
    for offset in range(days):
        day = (now + timedelta(days=offset)).date()
        if day.isoformat() in existing_days or day.weekday() not in wanted:
            continue
        n = max(1, burst_left) if offset == 0 and burst_left else 1
        burst_left = 0
        for k in range(n):
            minute = rng.randint(0, int(conf.get("jitter_minutes") or 0)) if conf.get("jitter_minutes") else 0
            when = datetime(day.year, day.month, day.day, int(conf["publish_hour_utc"]), 0, tzinfo=timezone.utc) + timedelta(minutes=minute + k * 25)
            if when < now - timedelta(hours=1) and offset == 0:
                when = now + timedelta(minutes=10 + k * 25)
            slot = {"cadence_day": day.isoformat(), "id": f"slot-{when.strftime('%Y%m%dT%H%M')}-{k}", "scheduled_for": when.isoformat().replace("+00:00", "Z"),
                    "status": "planned", "spoke_id": None, "suggestion_id": None, "headline": None, "draft_slug": None, "section": None}
            state.setdefault("slots", []).append(slot)
            created.append(slot)
    state["slots"].sort(key=lambda s: s["scheduled_for"])
    return created


def pick_next(topic_map: dict[str, Any], suggestions: dict[str, Any], mode: str, used_spokes: set[str]) -> Optional[dict[str, Any]]:
    """The next thing to write: a suggestion (by score) or an open spoke from the least-covered active pillar."""
    def from_suggestions() -> Optional[dict[str, Any]]:
        items = [i for i in suggestions.get("items", []) if i.get("status") == "suggested" and i.get("spoke_id") not in used_spokes]
        items.sort(key=lambda i: (i.get("score") is None, -(i.get("score") or 0), i.get("created_at") or ""))
        for it in items:
            spoke = pubstate.find_spoke(topic_map, str(it.get("spoke_id") or ""))
            if it.get("spoke_id") and (spoke is None or spoke.get("status") != "open"):
                continue
            return {"suggestion": it, "spoke": spoke}
        return None

    def from_map() -> Optional[dict[str, Any]]:
        pillars = [p for p in topic_map.get("pillars", []) if not p.get("is_muted")]
        pillars.sort(key=lambda p: (sum(1 for s in p.get("spokes", []) if s.get("status") in ("covered", "queued")) / max(len(p.get("spokes", [])), 1), not p.get("is_priority")))
        for p in pillars:
            for s in p.get("spokes", []):
                if s.get("status") == "open" and s["id"] not in used_spokes:
                    return {"suggestion": None, "spoke": s}
        return None

    if mode == "topic_map":
        return from_map()
    if mode == "curate_only":
        return from_suggestions()
    return from_suggestions() or from_map()


def pillar_of(topic_map: dict[str, Any], spoke_id: Optional[str]) -> Optional[dict[str, Any]]:
    for pillar, spoke in pubstate.all_spokes(topic_map):
        if spoke.get("id") == spoke_id:
            return pillar
    return None


def queue_slots(root: Path, pub: publication.Publication, state: dict[str, Any], topic_map: dict[str, Any],
                suggestions: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    used = {s["spoke_id"] for s in state.get("slots", []) if s.get("spoke_id")}
    queued = []
    for slot in state.get("slots", []):
        if slot["status"] != "planned":
            continue
        pick = pick_next(topic_map, suggestions, mode, used)
        if pick is None:
            break
        spoke, sugg = pick["spoke"], pick["suggestion"]
        headline = (sugg or {}).get("headline") or (spoke or {}).get("subtopic") or "Untitled"
        refresh_of = (spoke or {}).get("refresh_of")
        slug = refresh_of or publication.slugify(headline, max_len=70)
        pillar = pillar_of(topic_map, (spoke or {}).get("id")) or next((p for p in topic_map.get("pillars", []) if p["slug"] == (sugg or {}).get("pillar")), None)
        section = next((s["name"] for s in pub.sections if pillar and s["slug"] == pillar["slug"]), pub.sections[0]["name"] if pub.sections else "Features")
        draft = root / "drafts" / f"{slug}.md"
        if not draft.exists():
            old_meta, old_body = publication.read_post(root / "posts" / f"{slug}.md") if refresh_of and (root / "posts" / f"{slug}.md").is_file() else ({}, "")
            if refresh_of and not old_meta:
                raise ValueError(f"refresh target missing: {slug}")
            headline = old_meta.get("title") or headline
            publication.write_post(draft, {
                "title": headline, "slug": slug, "status": "draft",
                "refresh_of": refresh_of, "original_published_at": old_meta.get("published_at"),
                "asset_slug": old_meta.get('asset_slug'), "cover": old_meta.get('cover'),
                "original_author": old_meta.get("author"), "original_body": old_body, "section": section, "spoke_id": (spoke or {}).get("id"),
                "brief": (spoke or {}).get("brief") or (sugg or {}).get("why") or "", "angle": (spoke or {}).get("angle") or "",
                "seo_keyword": (spoke or {}).get("seo_keyword"), "planned_for": slot["scheduled_for"], "created_at": pubstate.now_iso(),
                "source_urls": [((sugg or {}).get("event") or {}).get("url")] if (sugg or {}).get("event") else [],
            }, "")
        slot.update({"status": "queued", "spoke_id": (spoke or {}).get("id"), "suggestion_id": (sugg or {}).get("id"), "headline": headline,
                     "draft_slug": slug, "section": section, "queued_at": pubstate.now_iso()})
        if spoke is not None:
            spoke.update({"status": "queued", "queued_at": pubstate.now_iso(), "article_slug": slug})
            used.add(spoke["id"])
        if sugg is not None:
            sugg["status"] = "queued"
            sugg["draft_slug"] = slug
        queued.append(slot)
    return queued


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure, materialize and fill a publication's publish slots.")
    parser.add_argument("--publication", help="Publication slug")
    parser.add_argument("--configure", action="store_true", help="Write planner settings from the flags below")
    parser.add_argument("--enable", action="store_true")
    parser.add_argument("--disable", action="store_true")
    parser.add_argument("--cadence-per-week", type=int, help="Posts per week (default 6)")
    parser.add_argument("--sourcing-mode", choices=["curate_first", "topic_map", "curate_only"])
    parser.add_argument("--approval-mode", choices=["manual", "review_window", "autopilot"])
    parser.add_argument("--publish-hour", type=int, help="UTC hour for slots (default: seeded 12-21)")
    parser.add_argument("--materialize", action="store_true", help="Create upcoming slots")
    parser.add_argument("--days", type=int, default=14, help="Horizon for --materialize (default 14)")
    parser.add_argument("--queue", action="store_true", help="Fill planned slots from suggestions / the topic map")
    parser.add_argument("--due", action="store_true", help="List queued slots whose time has come")
    parser.add_argument("--publications-dir", help="Override the publications directory")
    args = parser.parse_args()

    cfg = config_module.load()
    if args.publications_dir:
        cfg.site["publications_dir"] = args.publications_dir
    root = publication.find_publication(cfg, args.publication)
    pub = publication.load_publication(root)
    conf = planner_config(pub)
    result: dict[str, Any] = {"checked": True, "publication": root.name}
    if args.configure:
        if args.enable:
            conf["enabled"] = True
        if args.disable:
            conf["enabled"] = False
        for key, val in (("cadence_per_week", args.cadence_per_week), ("sourcing_mode", args.sourcing_mode),
                         ("approval_mode", args.approval_mode), ("publish_hour_utc", args.publish_hour)):
            if val is not None:
                conf[key] = val
        save_planner_config(root, conf)
        result["configured"] = True
    result["planner"] = conf
    state_path = pubstate.state_path(cfg, "planner", root.name)
    state = pubstate.load_json(state_path, {"slots": []})
    if args.materialize:
        if not conf.get("enabled", True):
            result["notes"] = ["planner disabled — enable with --configure --enable"]
        else:
            result["materialized"] = [s["scheduled_for"] for s in materialize(state, conf, root.name, days=args.days, published_count=len(pub.posts))]
    if args.queue:
        topic_map = pubstate.load_topic_map(root)
        suggestions = pubstate.load_json(pubstate.state_path(cfg, "suggestions", root.name), {"items": []})
        queued = queue_slots(root, pub, state, topic_map, suggestions, str(conf.get("sourcing_mode") or "curate_first"))
        pubstate.save_topic_map(root, topic_map)
        pubstate.save_json(pubstate.state_path(cfg, "suggestions", root.name), suggestions)
        result["queued"] = [{"slot": s["id"], "scheduled_for": s["scheduled_for"], "headline": s["headline"], "draft": s["draft_slug"]} for s in queued]
        if not queued and any(s["status"] == "planned" for s in state.get("slots", [])):
            result.setdefault("notes", []).append("planned slots remain empty — no open spokes or suggestions (run pub-curate)")
    pubstate.save_json(state_path, state)
    now = datetime.now(timezone.utc)
    slots = state.get("slots", [])
    result["status"] = {st: sum(1 for s in slots if s["status"] == st) for st in ("planned", "queued", "building", "published", "skipped")}
    result["upcoming"] = [{k: s[k] for k in ("id", "scheduled_for", "status", "headline", "draft_slug")} for s in slots if s["status"] in ("planned", "queued", "building")][:10]
    if args.due:
        result["due"] = [{k: s[k] for k in ("id", "scheduled_for", "headline", "draft_slug", "section")} for s in slots
                         if s["status"] in ("queued", "building") and publication.parse_iso(s["scheduled_for"]) is not None and publication.parse_iso(s["scheduled_for"]) <= now]
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
