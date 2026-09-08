"""pub-monitor: Search Console performance for one publication — the vendor's
Insights / phantom_seo layer (publication-playbook §7).

Per rolling window (--period 14d|30d|90d, ending ~3 days ago because GSC
finalizes late) and the previous equal window:
  * site totals: clicks, impressions, CTR, impression-weighted position, deltas
  * per post: the same, plus indexing state `awaiting | receiving` keyed on the
    first day GSC ever served an impression (persisted in state)
  * per pillar: rollups via each post's section
  * top queries with the posts they drove
  * a zero-filled daily series for charting
  * deterministic insights: opinionated sentences with the numbers spelled out

--sync-geo folds the latest brand-mention run (geo-monitor
track_brand_mentions.py) into .seo-engine/state/pub-geo-opportunities-<slug>.json:
prompts where a competitor is named and the client is not, with a gap score —
the `geo` signal pub-curate scores against.

The property is resolved from the publication's own site_url without touching
the main site's cached GSC property.

Usage:
    python3 report_performance.py --publication llm-billboard --period 30d
    python3 report_performance.py --publication llm-billboard --sync-geo
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
from datetime import date, timedelta  # noqa: E402
from typing import Any, Optional  # noqa: E402
from urllib.parse import urlparse  # noqa: E402

from scripts.lib import publication, pubstate, urlnorm  # noqa: E402
from scripts.lib.config import Config  # noqa: E402

PERIODS = {"14d": 14, "30d": 30, "90d": 90}
GSC_LAG_DAYS = 3


# ---------- pure aggregation (unit-tested) ----------

def totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    clicks = sum(int(r.get("clicks", 0)) for r in rows)
    impressions = sum(int(r.get("impressions", 0)) for r in rows)
    weighted = sum(float(r.get("position", 0)) * int(r.get("impressions", 0)) for r in rows)
    return {"clicks": clicks, "impressions": impressions, "ctr": round(clicks / impressions, 4) if impressions else None,
            "position": round(weighted / impressions, 2) if impressions else None}


def delta(cur: dict[str, Any], prev: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("clicks", "impressions"):
        out[key] = cur.get(key, 0) - prev.get(key, 0)
    for key in ("ctr", "position"):
        if cur.get(key) is not None and prev.get(key) is not None:
            out[key] = round(cur[key] - prev[key], 4)
    return out


def post_slug_of(url: str) -> Optional[str]:
    path = urlparse(url).path.rstrip("/")
    return path.split("/posts/", 1)[1].split("/")[0] if "/posts/" in path else None


def aggregate(pub: publication.Publication, page_rows_cur: list[dict[str, Any]], page_rows_prev: list[dict[str, Any]],
              query_page_rows: list[dict[str, Any]], date_rows: list[dict[str, Any]], state: dict[str, Any],
              window: dict[str, str], today: str) -> dict[str, Any]:
    """Pure: rows are {page|query|date, clicks, impressions, ctr, position}."""
    by_slug_cur: dict[str, list[dict[str, Any]]] = {}
    by_slug_prev: dict[str, list[dict[str, Any]]] = {}
    for rows, bucket in ((page_rows_cur, by_slug_cur), (page_rows_prev, by_slug_prev)):
        for r in rows:
            slug = post_slug_of(str(r.get("page", "")))
            if slug:
                bucket.setdefault(slug, []).append(r)
    posts_out = []
    first_seen = state.setdefault("first_impression_at", {})
    for post in pub.posts:
        cur = totals(by_slug_cur.get(post.slug, []))
        prev = totals(by_slug_prev.get(post.slug, []))
        if cur["impressions"] and post.slug not in first_seen:
            first_seen[post.slug] = today
        posts_out.append({"slug": post.slug, "title": post.title, "section": pub.section_for(post)["name"],
                          "published_at": post.published_at[:10], "state": "receiving" if post.slug in first_seen else "awaiting",
                          "first_impression_at": first_seen.get(post.slug), "current": cur, "previous": prev, "delta": delta(cur, prev)})
    pillars: dict[str, dict[str, Any]] = {}
    for p in posts_out:
        b = pillars.setdefault(p["section"], {"section": p["section"], "posts": 0, "receiving": 0, "rows_cur": [], "rows_prev": []})
        b["posts"] += 1
        b["receiving"] += p["state"] == "receiving"
        b["rows_cur"] += by_slug_cur.get(p["slug"], [])
        b["rows_prev"] += by_slug_prev.get(p["slug"], [])
    pillar_out = [{"section": b["section"], "posts": b["posts"], "receiving": b["receiving"], "current": totals(b["rows_cur"]),
                   "previous": totals(b["rows_prev"]), "delta": delta(totals(b["rows_cur"]), totals(b["rows_prev"]))} for b in pillars.values()]
    pillar_out.sort(key=lambda x: -(x["current"]["impressions"] or 0))
    queries: dict[str, dict[str, Any]] = {}
    for r in query_page_rows:
        q = str(r.get("query", ""))
        slug = post_slug_of(str(r.get("page", "")))
        if not q or not slug:
            continue
        b = queries.setdefault(q, {"query": q, "clicks": 0, "impressions": 0, "_w": 0.0, "posts": set()})
        b["clicks"] += int(r.get("clicks", 0))
        b["impressions"] += int(r.get("impressions", 0))
        b["_w"] += float(r.get("position", 0)) * int(r.get("impressions", 0))
        b["posts"].add(slug)
    top_queries = sorted(({"query": b["query"], "clicks": b["clicks"], "impressions": b["impressions"],
                           "position": round(b["_w"] / b["impressions"], 2) if b["impressions"] else None, "posts": sorted(b["posts"])}
                          for b in queries.values()), key=lambda x: (-x["clicks"], -x["impressions"]))[:50]
    start, end = date.fromisoformat(window["start"]), date.fromisoformat(window["end"])
    by_date = {str(r.get("date")): r for r in date_rows}
    series = []
    d = start
    while d <= end:
        r = by_date.get(d.isoformat(), {})
        series.append({"date": d.isoformat(), "clicks": int(r.get("clicks", 0)), "impressions": int(r.get("impressions", 0)),
                       "position": round(float(r["position"]), 2) if r.get("position") is not None else None})
        d += timedelta(days=1)
    site_cur, site_prev = totals(page_rows_cur), totals(page_rows_prev)
    insights = []
    receiving = sum(1 for p in posts_out if p["state"] == "receiving")
    insights.append(f"{receiving} of {len(posts_out)} published posts have received at least one Search Console impression.")
    stale = [p for p in posts_out if p["state"] == "awaiting" and p["published_at"] and (date.fromisoformat(today) - date.fromisoformat(p["published_at"])).days > 21]
    if stale:
        insights.append(f"{len(stale)} post(s) older than 21 days are still awaiting a first impression: {', '.join(p['slug'] for p in stale[:5])}.")
    if pillar_out and pillar_out[0]["current"]["impressions"]:
        top = pillar_out[0]
        insights.append(f"The {top['section']} section drives {top['current']['impressions']} impressions this period, the most of any section.")
    if site_prev["impressions"] and site_cur["impressions"]:
        change = (site_cur["impressions"] - site_prev["impressions"]) / site_prev["impressions"]
        insights.append(f"Impressions moved {change:+.0%} versus the previous {len(series)}-day window ({site_prev['impressions']} → {site_cur['impressions']}).")
    movers = [p for p in posts_out if p["previous"]["impressions"] >= 20 and p["current"]["impressions"] >= p["previous"]["impressions"] * 1.5]
    if movers:
        insights.append(f"Fastest riser: {movers[0]['slug']} ({movers[0]['previous']['impressions']} → {movers[0]['current']['impressions']} impressions).")
    return {"site": {"current": site_cur, "previous": site_prev, "delta": delta(site_cur, site_prev)},
            "posts": {"published": len(posts_out), "receiving": receiving, "items": posts_out},
            "pillars": pillar_out, "top_queries": top_queries, "series": series, "insights": insights}


def sync_geo(cfg: Config, slug: str) -> dict[str, Any]:
    mentions = pubstate.load_json(pubstate.state_path(cfg, "mentions", slug), {})
    runs = mentions.get("runs") or []
    if not runs:
        return {"synced": 0, "note": "no brand-mention runs yet (geo-monitor track_brand_mentions.py --publication ...)"}
    latest = runs[-1]
    items = []
    for p in latest.get("per_prompt", []):
        brand_rate = float((p.get("entities") or {}).get("brand", {}).get("mention_rate") or 0)
        comps = {k: v for k, v in (p.get("entities") or {}).items() if k != "brand"}
        if not comps:
            continue
        top_key, top = max(comps.items(), key=lambda kv: float(kv[1].get("mention_rate") or 0))
        top_rate = float(top.get("mention_rate") or 0)
        if top_rate > brand_rate:
            items.append({"prompt_text": p.get("prompt"), "topic": p.get("topic"), "brand_mentioned": brand_rate > 0,
                          "competitor_top": top.get("name") or top_key, "gap_score": round(top_rate - brand_rate, 3), "run_id": latest.get("run_id")})
    items.sort(key=lambda x: -x["gap_score"])
    pubstate.save_json(pubstate.state_path(cfg, "geo-opportunities", slug), {"publication": slug, "synced_at": pubstate.now_iso(), "items": items})
    return {"synced": len(items), "from_run": latest.get("run_id")}


def main() -> int:
    parser = argparse.ArgumentParser(description="Search Console rollups for one publication.")
    parser.add_argument("--publication", help="Publication slug")
    parser.add_argument("--period", choices=sorted(PERIODS), default="30d")
    parser.add_argument("--sync-geo", action="store_true", help="Refresh the GEO-opportunities state from the latest brand-mention run")
    parser.add_argument("--publications-dir", help="Override the publications directory")
    args = parser.parse_args()

    cfg = config_module.load()
    if args.publications_dir:
        cfg.site["publications_dir"] = args.publications_dir
    root = publication.find_publication(cfg, args.publication)
    pub = publication.load_publication(root)
    report: dict[str, Any] = {"checked": True, "publication": root.name, "site_url": pub.site_url, "period": args.period}
    if args.sync_geo:
        report["geo_sync"] = sync_geo(cfg, root.name)
    if not cfg.integration_available("google_search_console"):
        report.update({"checked": False, "not_checked": {"search_console": "set GOOGLE_APPLICATION_CREDENTIALS or GSC_SERVICE_ACCOUNT_JSON and add the service account to the publication's property"}})
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if args.sync_geo else 1
    from scripts.lib import gsc  # lazy: needs google libs only here

    entries = gsc.list_sites(cfg)
    prop, candidates = gsc._match_property(pub.site_url, entries)
    if prop is None:
        report.update({"checked": False, "error": f"no Search Console property matches {pub.site_url}; visible: {[e.get('siteUrl') for e in entries]}"})
        print(json.dumps(report, indent=2))
        return 1
    days = PERIODS[args.period]
    end = gsc.gsc_today() - timedelta(days=GSC_LAG_DAYS)
    start = end - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    window = {"start": start.isoformat(), "end": end.isoformat()}
    previous = {"start": prev_start.isoformat(), "end": prev_end.isoformat()}

    def rows(dims: list[str], s: date, e: date, max_rows: int = 5000) -> list[dict[str, Any]]:
        raw, _ = gsc.search_analytics_query_all(cfg, s.isoformat(), e.isoformat(), dimensions=dims, max_rows=max_rows, property_id=prop)
        out = []
        for r in raw:
            keys = r.get("keys", [])
            rec = {dims[i]: keys[i] for i in range(min(len(dims), len(keys)))}
            rec.update({"clicks": r.get("clicks", 0), "impressions": r.get("impressions", 0), "ctr": r.get("ctr"), "position": r.get("position", 0)})
            out.append(rec)
        return out

    page_cur = rows(["page"], start, end)
    page_prev = rows(["page"], prev_start, prev_end)
    query_page = rows(["query", "page"], start, end)
    date_rows = rows(["date"], start, end)
    state_path = pubstate.state_path(cfg, "performance", root.name)
    state = pubstate.load_json(state_path, {})
    agg = aggregate(pub, page_cur, page_prev, query_page, date_rows, state, window, gsc.gsc_today().isoformat())
    state["last_run"] = {"at": pubstate.now_iso(), "period": args.period, "site": agg["site"]}
    history = state.setdefault("history", [])
    history.append({"at": pubstate.now_iso(), "period": args.period, "window": window, "site": agg["site"]["current"],
                    "posts": {p["slug"]: p["current"] for p in agg["posts"]["items"]}})
    state["history"] = history[-60:]
    pubstate.save_json(state_path, state)
    report.update({"property": prop, "window": window, "previous_window": previous, **agg})
    out = pubstate.report_path(cfg, "performance", root.name)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    report["report_file"] = str(out)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
