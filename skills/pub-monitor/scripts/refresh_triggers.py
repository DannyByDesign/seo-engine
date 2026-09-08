"""pub-monitor: which published posts have earned a refresh — the vendor's
"get notified when an article needs a refresh" (publication-playbook §4).

Triggers (each named in the output, never merged into one score):
  clicks_drop      clicks fell >= --drop-ratio (0.5) between the last two
                   performance runs with prior clicks >= --min-prior-clicks (10)
  aged             published more than --max-age-days (180) ago and never updated
  never_indexed    published more than --awaiting-days (45) ago and still awaiting
                   a first impression (re-research and re-source, or retire)
  dated_numbers    the prose cites a year older than the current one alongside a
                   figure (a "2024" in a 2026 article), from the markdown itself

--queue adds one refresh spoke per flagged post to the topic map
(source user, `refresh_of: <slug>`) so the planner can schedule the rewrite;
the refresh runs through pub-research (new sources) and pub-enhance
(`--posts`) — never a bare date bump (red-flags §3).

Usage:
    python3 refresh_triggers.py --publication llm-billboard
    python3 refresh_triggers.py --publication llm-billboard --queue --max-age-days 120
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
import re  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Any  # noqa: E402

from scripts.lib import publication, pubstate  # noqa: E402

_YEAR_NEAR_NUMBER = re.compile(r"(?:\$?\d[\d,.]*%?\s+\w+\s+(?:in|for|of)\s+(20\d\d)\b)|(?:\b(20\d\d)\b[^.\n]{0,40}\$?\d[\d,.]*%)")


def triggers_for(post: publication.Post, history: list[dict[str, Any]], first_seen: dict[str, str], *, now: datetime,
                 drop_ratio: float, min_prior_clicks: int, max_age_days: int, awaiting_days: int) -> list[dict[str, Any]]:
    out = []
    published = publication.parse_iso(post.published_at)
    updated = publication.parse_iso(post.updated_at) or published
    age = (now - published).days if published else 0
    if len(history) >= 2:
        prev = (history[-2].get("posts") or {}).get(post.slug, {})
        cur = (history[-1].get("posts") or {}).get(post.slug, {})
        p, c = int(prev.get("clicks") or 0), int(cur.get("clicks") or 0)
        if p >= min_prior_clicks and c <= p * (1 - drop_ratio):
            out.append({"trigger": "clicks_drop", "detail": f"clicks {p} → {c} between the last two runs", "dispatch": "pub-research + pub-enhance --posts"})
    if published and age > max_age_days and (updated is None or (now - updated).days > max_age_days):
        out.append({"trigger": "aged", "detail": f"published {age} days ago, never substantively updated", "dispatch": "pub-research + pub-enhance --posts"})
    if published and age > awaiting_days and post.slug not in first_seen:
        out.append({"trigger": "never_indexed", "detail": f"{age} days without a Search Console impression", "dispatch": "pub-research (re-source) or retire"})
    stale_years = sorted({y for m in _YEAR_NEAR_NUMBER.finditer(post.body_md) for y in m.groups() if y and int(y) < now.year - 1})
    if stale_years:
        out.append({"trigger": "dated_numbers", "detail": f"figures dated {', '.join(stale_years)} in the prose", "dispatch": "pub-research + pub-enhance --posts"})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Flag published posts that need a refresh.")
    parser.add_argument("--publication", help="Publication slug")
    parser.add_argument("--drop-ratio", type=float, default=0.5)
    parser.add_argument("--min-prior-clicks", type=int, default=10)
    parser.add_argument("--max-age-days", type=int, default=180)
    parser.add_argument("--awaiting-days", type=int, default=45)
    parser.add_argument("--queue", action="store_true", help="Add a refresh spoke per flagged post to the topic map")
    parser.add_argument("--publications-dir", help="Override the publications directory")
    args = parser.parse_args()

    cfg = config_module.load()
    if args.publications_dir:
        cfg.site["publications_dir"] = args.publications_dir
    root = publication.find_publication(cfg, args.publication)
    pub = publication.load_publication(root)
    perf = pubstate.load_json(pubstate.state_path(cfg, "performance", root.name), {})
    history = perf.get("history") or []
    first_seen = perf.get("first_impression_at") or {}
    now = datetime.now(timezone.utc)
    flagged = []
    for post in pub.posts:
        t = triggers_for(post, history, first_seen, now=now, drop_ratio=args.drop_ratio, min_prior_clicks=args.min_prior_clicks,
                         max_age_days=args.max_age_days, awaiting_days=args.awaiting_days)
        if t:
            flagged.append({"slug": post.slug, "title": post.title, "published_at": post.published_at[:10], "triggers": t})
    result: dict[str, Any] = {"checked": True, "publication": root.name, "posts_checked": len(pub.posts), "flagged": flagged,
                              "notes": [] if history else ["no performance history yet — run report_performance.py first; only age/date triggers apply"]}
    if args.queue and flagged:
        topic_map = pubstate.load_topic_map(root)
        added = []
        for f in flagged:
            if any(s.get("refresh_of") == f["slug"] and s.get("status") in ("open", "queued") for _, s in pubstate.all_spokes(topic_map)):
                continue
            post = next(p for p in pub.posts if p.slug == f["slug"])
            section = pub.section_for(post)
            pillar = next((p for p in topic_map.get("pillars", []) if p["slug"] == section["slug"]), None)
            if pillar is None:
                pillar = {"slug": section["slug"], "name": section["name"], "is_priority": True, "is_muted": False, "spokes": []}
                topic_map.setdefault("pillars", []).append(pillar)
            spoke = {"id": pubstate.next_spoke_id(topic_map), "subtopic": f"Refresh: {post.title}", "angle": "update every figure to the newest source",
                     "brief": "; ".join(t["detail"] for t in f["triggers"]), "status": "open", "client_relevance": "medium", "source": "user",
                     "seo_keyword": None, "refresh_of": f["slug"], "created_at": pubstate.now_iso()}
            pillar.setdefault("spokes", []).append(spoke)
            added.append(spoke["id"])
        pubstate.save_topic_map(root, topic_map)
        result["queued_spokes"] = added
    pubstate.save_json(pubstate.state_path(cfg, "refresh", root.name), {"checked_at": pubstate.now_iso(), "flagged": flagged})
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
