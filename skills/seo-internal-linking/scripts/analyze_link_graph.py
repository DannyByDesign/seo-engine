"""seo-internal-linking: build and analyze the site's internal link graph.

Reads pages from the shared crawl-snapshot store (scripts.lib.snapshots —
reuses a snapshot under 24h old, else crawls fresh) and builds an
alias-folded directed graph via scripts.lib.linkgraph, so a page linked only
through its redirecting /old alias or www variant still counts as linked.
Per references/seo-playbook.md §6 (Internal linking and topical authority):

  - "No orphan pages -- every indexable page should be reachable from at
    least one other indexed page via a normal <a href>."
  - "Link depth matters: pages more than ~3-4 clicks from the homepage get
    crawled and refreshed less often."

Orphan detection is only honest against a URL universe gathered
INDEPENDENTLY of the link graph (sitemap.xml, GSC page data) — a
link-following crawl cannot discover an unlinked page by construction.
When no independent source is available, the report's `orphans` section is
`{"checked": false, "reason": ...}`, never an empty-but-authoritative list.

Findings emitted:
  - orphan_page (high; low when the crawl was truncated): in the universe,
    crawled, indexable, but unreachable from the homepage via <a href> links.
  - orphan_candidate (medium): in the universe, never seen by the crawl,
    and live-confirmed (bounded polite sample) to currently return HTTP 200.
    Non-200/errored sample URLs are noted, not flagged.
  - unreachable_page (high): crawled, indexable, but disconnected from the
    homepage-rooted graph (an island) — crawl-only signal, no universe needed.
  - deep_page (medium): indexable page more than --max-depth (default 4)
    clicks from the homepage.
  - single_inbound_link (low): indexable page with exactly one distinct
    inbound internal link — one navigation/template change away from
    becoming unreachable.

This script only reads and reports -- it never edits source files or inserts
links. See SKILL.md and scripts/suggest_link_opportunities.py for how findings
here feed into reviewable, contextual link-insertion suggestions.

Usage:
    python3 analyze_link_graph.py [--max-depth 4] [--max-pages 500] [--force-recrawl]
"""

from __future__ import annotations

import json
import sys
from collections import deque
from pathlib import Path
from typing import Any


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
from scripts.lib import http_util, linkgraph, pagerules, robots, snapshots, urlnorm  # noqa: E402

DEFAULT_MAX_DEPTH = 4  # per seo-playbook.md §6: "~3-4 clicks from the homepage"
SNAPSHOT_MAX_AGE_HOURS = 24
LIVE_CONFIRM_SAMPLE = 20  # bounded, polite live check of uncrawled orphan candidates
LIVE_CONFIRM_MIN_INTERVAL = 1.0


def _bfs_depths(graph: linkgraph.LinkGraph, root: str) -> dict[str, int]:
    """Shortest link-depth (in <a href> hops) from the resolved homepage node
    over the alias-folded adjacency. Nodes absent from the result are
    unreachable from the homepage."""
    depths: dict[str, int] = {root: 0}
    queue: deque[str] = deque([root])
    while queue:
        node = queue.popleft()
        for target in graph.adjacency.get(node, ()):
            if target not in depths:
                depths[target] = depths[node] + 1
                queue.append(target)
    return depths


def _display_url(rec: dict[str, Any]) -> str:
    return rec.get("final_url") or rec.get("url", "")


def _live_confirm_candidates(keys: list[str]) -> dict[str, Any]:
    """Politely fetch a bounded sample of uncrawled orphan-candidate URLs.
    (canonical_key output is itself a fetchable https URL.) Only a confirmed
    HTTP 200 earns an orphan_candidate finding — anything else is noted so a
    stale sitemap entry is never reported as a live orphan."""
    confirmed: list[str] = []
    other: list[dict[str, Any]] = []
    for key in keys[:LIVE_CONFIRM_SAMPLE]:
        try:
            resp = http_util.get(key, min_interval=LIVE_CONFIRM_MIN_INTERVAL)
            status = resp.status_code
            resp.close()
        except http_util.HttpError as exc:
            other.append({"url": key, "status": None,
                          "error_type": exc.error_type or "other"})
            continue
        if status == 200:
            confirmed.append(key)
        else:
            other.append({"url": key, "status": status})
    return {
        "sampled": min(len(keys), LIVE_CONFIRM_SAMPLE),
        "not_sampled": max(0, len(keys) - LIVE_CONFIRM_SAMPLE),
        "confirmed_200": confirmed,
        "other": other,
    }


def analyze(
    pages: list[dict[str, Any]],
    snap: snapshots.Snapshot,
    cfg: config_module.Config,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> dict[str, Any]:
    graph = linkgraph.build_graph(pages)
    pages_by_key = linkgraph.index_pages(pages)
    root_key = urlnorm.canonical_key(cfg.site_url)
    root = urlnorm.resolve_alias(root_key, graph.alias_map)

    indexable_keys = {
        key for key, rec in pages_by_key.items()
        if pagerules.is_indexable_html(rec)
    }

    crawl_summary = snap.meta.get("crawl_summary") or {}
    crawl_info = {
        "producer_skill": snap.meta.get("producer_skill"),
        "finished_at": snap.meta.get("finished_at"),
        "pages_crawled": snap.pages_crawled,
        "truncated": snap.truncated,
        "robots_status": crawl_summary.get("robots_status"),
        "all_blocked": bool(crawl_summary.get("all_blocked")),
    }

    if root not in graph.nodes:
        return {
            "error": (
                f"The homepage ({cfg.site_url}) is not present in the crawl "
                "snapshot as a successfully-fetched page — cannot compute link "
                "depth or reachability. "
                + ("robots.txt blocked the crawl entirely "
                   f"(robots_status={crawl_info['robots_status']!r})."
                   if crawl_info["all_blocked"] else
                   "Check the crawl summary and re-run with --force-recrawl.")
            ),
            "crawl": crawl_info,
            "findings": [],
        }

    depths = _bfs_depths(graph, root)
    findings: list[dict[str, Any]] = []

    # ---- crawl-only signals: valid without any URL universe ----
    for key in sorted(indexable_keys):
        if key == root:
            continue
        rec = pages_by_key[key]
        url = _display_url(rec)
        depth = depths.get(key)
        inbound = graph.inbound.get(key, 0)

        if depth is None:
            findings.append({
                "type": "unreachable_page",
                "severity": "high",
                "url": url,
                "title": rec.get("title", ""),
                "depth_from_homepage": None,
                "inbound_links": inbound,
                "detail": (
                    f"{url} was crawled but is not reachable from the homepage "
                    "via any chain of <a href> links (after folding redirect/"
                    "www aliases) — it sits in a disconnected island. "
                    "Functionally as invisible to homepage-rooted crawl "
                    "discovery as a true orphan."
                ),
                "seo_playbook_ref": "seo-playbook.md §6 (Internal linking and topical authority)",
                "auto_fixable": False,
                "human_review_reason": (
                    "Requires tracing the disconnected cluster back to a page that IS "
                    "reachable from the homepage and adding a contextual link there, or "
                    "confirming the whole cluster is intentionally excluded."
                ),
            })
        elif depth > max_depth:
            findings.append({
                "type": "deep_page",
                "severity": "medium",
                "url": url,
                "title": rec.get("title", ""),
                "depth_from_homepage": depth,
                "inbound_links": inbound,
                "detail": (
                    f"{url} is {depth} clicks from the homepage "
                    f"(threshold: {max_depth}). Per seo-playbook.md §6, pages this deep "
                    "get crawled and refreshed less often."
                ),
                "seo_playbook_ref": "seo-playbook.md §6 (Internal linking and topical authority) -- \"Link depth matters\"",
                "auto_fixable": False,
                "human_review_reason": (
                    "Reducing depth means adding a contextual link from a shallower, "
                    "topically relevant page -- a judgment call about which existing page "
                    "and which existing sentence, not a mechanical link-block insertion. "
                    "See suggest_link_opportunities.py."
                ),
            })

        if depth is not None and inbound == 1:
            findings.append({
                "type": "single_inbound_link",
                "severity": "low",
                "url": url,
                "title": rec.get("title", ""),
                "depth_from_homepage": depth,
                "inbound_links": 1,
                "detail": (
                    f"{url} has exactly one distinct inbound internal link "
                    "(after alias folding). One navigation or template change "
                    "on the single linking page would sever it from the graph "
                    "entirely — fragile, not broken."
                ),
                "seo_playbook_ref": "seo-playbook.md §6 (Internal linking and topical authority)",
                "auto_fixable": False,
                "human_review_reason": (
                    "Adding a second inbound link must still be a genuine, "
                    "contextual editorial insertion — see "
                    "suggest_link_opportunities.py and red-flags.md §1."
                ),
            })

    # ---- orphan detection: needs a URL universe independent of the graph ----
    policy = robots.fetch(cfg.site_url)
    universe = linkgraph.known_url_universe(cfg, cfg.site_url, policy)
    orphan = linkgraph.orphan_analysis(
        universe, graph, root_key, pages_by_key, crawl_truncated=snap.truncated)

    if not orphan.get("checked"):
        orphans_out: dict[str, Any] = {
            "checked": False,
            "reason": orphan.get("reason", universe.get("reason", "")),
            "sources": universe.get("sources", {}),
        }
    else:
        for entry in orphan["orphan_pages"]:
            key = urlnorm.canonical_key(entry["url"])
            rec = pages_by_key.get(urlnorm.resolve_alias(key, graph.alias_map)) or {}
            findings.append({
                "type": "orphan_page",
                "severity": entry["severity"],  # high; low when crawl truncated
                "url": entry["url"],
                "title": rec.get("title", ""),
                "depth_from_homepage": None,
                "inbound_links": entry.get("inbound_links", 0),
                "in_sitemap": entry.get("in_sitemap", True),
                "detail": (
                    f"{entry['url']} exists in the site's independent URL "
                    "universe (sitemap/GSC), was crawled and is indexable, but "
                    "is unreachable from the homepage via <a href> links after "
                    "alias folding — a true orphan."
                    + (" NOTE: the crawl was truncated at its max_pages cap, so "
                       "coverage gaps can mimic orphanhood — severity reduced "
                       "to low; raise --max-pages to confirm."
                       if entry["severity"] == "low" else "")
                ),
                "seo_playbook_ref": "seo-playbook.md §6 (Internal linking and topical authority) -- \"No orphan pages\"",
                "auto_fixable": False,
                "human_review_reason": (
                    "Fixing an orphan requires inserting a genuine, contextual link from "
                    "an existing relevant page/paragraph -- see suggest_link_opportunities.py "
                    "for candidates, and red-flags.md's caution against non-editorially-"
                    "justified link insertion. Never auto-insert a link block."
                ),
            })

        live = _live_confirm_candidates(orphan["orphan_candidates_uncrawled"])
        for url in live["confirmed_200"]:
            findings.append({
                "type": "orphan_candidate",
                "severity": "medium",
                "url": url,
                "title": "",
                "depth_from_homepage": None,
                "inbound_links": 0,
                "in_sitemap": True,
                "detail": (
                    f"{url} appears in the site's independent URL universe "
                    "(sitemap/GSC), was never discovered by the link-following "
                    "crawl, and a live check confirms it currently returns "
                    "HTTP 200 — a strong orphan candidate. It was not crawled, "
                    "so its indexability (noindex/canonical) is unverified; "
                    "confirm before acting."
                ),
                "seo_playbook_ref": "seo-playbook.md §6 (Internal linking and topical authority) -- \"No orphan pages\"",
                "auto_fixable": False,
                "human_review_reason": (
                    "Confirm the page is indexable and genuinely wanted in the "
                    "link graph (not a deliberately unlinked landing page), then "
                    "add a contextual link — see suggest_link_opportunities.py."
                ),
            })

        orphans_out = {
            "checked": True,
            "sources": universe.get("sources", {}),
            "universe_count": orphan.get("universe_count"),
            "reachable_count": orphan.get("reachable_count"),
            "crawl_truncated": orphan.get("crawl_truncated", False),
            "orphan_page_count": len(orphan["orphan_pages"]),
            "orphan_candidates_uncrawled_count": len(orphan["orphan_candidates_uncrawled"]),
            "live_check": {
                "sampled": live["sampled"],
                "not_sampled": live["not_sampled"],
                "confirmed_200_count": len(live["confirmed_200"]),
                "other": live["other"],
            },
        }

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda f: (severity_order.get(f.get("severity", "low"), 9), f["url"]))

    depth_histogram: dict[str, int] = {}
    for key in indexable_keys:
        d = depths.get(key)
        if d is not None:
            depth_histogram[str(d)] = depth_histogram.get(str(d), 0) + 1

    severity_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    for f in findings:
        severity_counts[f["severity"]] = severity_counts.get(f["severity"], 0) + 1
        type_counts[f["type"]] = type_counts.get(f["type"], 0) + 1

    root_rec = pages_by_key.get(root, {})
    return {
        "homepage_url": _display_url(root_rec) or cfg.site_url,
        "max_depth_threshold": max_depth,
        "pages_analyzed": len(indexable_keys),
        "crawl": crawl_info,
        "orphans": orphans_out,
        "finding_counts_by_type": type_counts,
        "severity_counts": severity_counts,
        "depth_histogram": dict(sorted(depth_histogram.items(), key=lambda kv: int(kv[0]))),
        "link_graph_depths": {
            _display_url(pages_by_key[key]): depths.get(key)
            for key in sorted(indexable_keys)
        },
        "findings": findings,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="seo-internal-linking: build an alias-folded link graph from "
                    "the shared crawl-snapshot store, detect orphans against an "
                    "independent URL universe (sitemap/GSC), and compute link "
                    "depth from the homepage."
    )
    parser.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH,
                        help=f"flag indexable pages deeper than this many clicks from "
                             f"the homepage (default {DEFAULT_MAX_DEPTH}, per "
                             "seo-playbook.md §6's ~3-4-click guidance)")
    parser.add_argument("--max-pages", type=int, default=500,
                        help="cap for a fresh crawl (default 500)")
    parser.add_argument("--force-recrawl", action="store_true",
                        help="ignore any reusable snapshot and crawl fresh")
    args = parser.parse_args()

    cfg = config_module.load()

    snap = None
    if not args.force_recrawl:
        snap = snapshots.latest(cfg, max_age_hours=SNAPSHOT_MAX_AGE_HOURS)
    freshly_crawled = snap is None
    if snap is None:
        snap = snapshots.new_crawl(cfg, "seo-internal-linking", max_pages=args.max_pages)

    pages = list(snap.pages())
    result = analyze(pages, snap, cfg, max_depth=args.max_depth)
    result["site_url"] = cfg.site_url
    result["snapshot_path"] = str(snap.path)
    result["freshly_crawled"] = freshly_crawled
    result["note"] = (
        "This script only reads and reports. It never inserts links. When "
        "orphans.checked is false, orphan detection was NOT POSSIBLE (no "
        "independent URL source) — that is a not-checked state, never a "
        "clean bill of health. Use suggest_link_opportunities.py to find "
        "contextually relevant existing pages/paragraphs where a link to a "
        "flagged page could naturally be added, then have a human/agent "
        "review the suggestion before editing any source content. See SKILL.md."
    )

    # Persist state for seo-maintain's continuous-loop regression diff, and a
    # dated human-readable report copy.
    import time

    reports_dir = cfg.reports_dir
    dated_report_path = reports_dir / f"internal-linking-{time.strftime('%Y-%m-%d')}.json"
    dated_report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    result["report_file"] = str(dated_report_path)

    orphans = result.get("orphans", {})
    state_path = cfg.state_dir / "internal-linking-last-run.json"
    state_path.write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pages_analyzed": result.get("pages_analyzed"),
        "orphans_checked": orphans.get("checked", False),
        "orphan_page_count": orphans.get("orphan_page_count", 0),
        "orphan_candidate_count": (orphans.get("live_check") or {}).get("confirmed_200_count", 0),
        "finding_counts_by_type": result.get("finding_counts_by_type"),
        "severity_counts": result.get("severity_counts"),
        "snapshot_path": result.get("snapshot_path"),
    }, indent=2), encoding="utf-8")

    snapshots.prune(cfg)

    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
