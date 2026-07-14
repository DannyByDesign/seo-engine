"""Alias-folded internal link graph + honest orphan detection.

A link-following crawl CANNOT discover an unlinked page — that is what makes
it an orphan. Orphan detection therefore requires a URL universe gathered
independently of the link graph (sitemap.xml, GSC page data); without one,
the honest answer is "cannot check", never an empty-but-authoritative list.
(The previous implementation derived orphans from the BFS itself, which is
provably always empty, while separately flagging redirect targets and www
variants — crawl-normalization artifacts — as fake orphans. Alias folding
fixes the latter; the universe fixes the former.)
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

from . import urlnorm
from .config import Config
from .pagerules import is_indexable_html


@dataclass
class LinkGraph:
    nodes: set[str] = field(default_factory=set)            # folded page identities
    adjacency: dict[str, set[str]] = field(default_factory=dict)
    inbound: dict[str, int] = field(default_factory=dict)   # distinct inbound sources
    alias_map: dict[str, str] = field(default_factory=dict)  # redirecting alias -> destination


def _node_key(rec: dict[str, Any]) -> str:
    """A record's graph identity: the folded FINAL destination, so a page
    linked only via its redirecting /old alias or www variant still counts
    as linked."""
    return urlnorm.canonical_key(rec.get("final_url") or rec.get("url", ""))


def build_graph(pages: list[dict[str, Any]]) -> LinkGraph:
    graph = LinkGraph(alias_map=urlnorm.build_alias_map(pages))

    for rec in pages:
        if rec.get("error"):
            continue
        node = _node_key(rec)
        if not node:
            continue
        graph.nodes.add(node)
        edges = graph.adjacency.setdefault(node, set())
        for link in rec.get("internal_links") or []:
            target = urlnorm.resolve_alias(urlnorm.canonical_key(link), graph.alias_map)
            if target and target != node:
                edges.add(target)

    inbound_sources: dict[str, set[str]] = {}
    for source, targets in graph.adjacency.items():
        for target in targets:
            inbound_sources.setdefault(target, set()).add(source)
    graph.inbound = {node: len(sources) for node, sources in inbound_sources.items()}
    return graph


def reachable(graph: LinkGraph, root_key: str) -> set[str]:
    root = urlnorm.resolve_alias(root_key, graph.alias_map)
    seen = {root}
    queue = deque([root])
    while queue:
        node = queue.popleft()
        for target in graph.adjacency.get(node, ()):
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def known_url_universe(
    cfg: Config,
    site_url: str,
    policy: Optional[Any] = None,
) -> dict[str, Any]:
    """URLs known to exist independently of the link graph.

    Sources, strongest first: sitemap.xml (+robots declarations), GSC page
    data (last 90 days) when configured. Returns folded keys plus source
    accounting; `checked: False` with a reason when NO independent source is
    available — the caller must then report orphan detection as not-checked
    rather than emitting an empty result.
    """
    from . import sitemaps

    urls: set[str] = set()
    sources: dict[str, Any] = {}

    sitemap_result = sitemaps.fetch_url_set(site_url, policy)
    if sitemap_result["found"]:
        folded = {urlnorm.canonical_key(u) for u in sitemap_result["page_urls"]}
        urls |= folded
        sources["sitemap"] = {
            "urls": len(folded),
            "sitemaps_read": sitemap_result["sitemaps_read"],
            "truncated": sitemap_result["truncated"],
        }
    else:
        sources["sitemap"] = {"error": "no sitemap found",
                              "details": sitemap_result["errors"][:3]}

    if cfg.integration_available("google_search_console"):
        try:
            from . import gsc
            from datetime import timedelta

            prop = gsc.resolve_property(cfg)
            end = gsc.gsc_today() - timedelta(days=3)
            start = end - timedelta(days=90)
            rows, hit_cap = gsc.search_analytics_query_all(
                cfg, start.isoformat(), end.isoformat(),
                dimensions=["page"], max_rows=100_000, property_id=prop,
            )
            gsc_keys = {urlnorm.canonical_key(r["keys"][0]) for r in rows if r.get("keys")}
            urls |= gsc_keys
            sources["gsc"] = {"urls": len(gsc_keys), "hit_row_cap": hit_cap}
        except Exception as exc:  # noqa: BLE001 — GSC is an enhancement source here
            sources["gsc"] = {"error": str(exc)[:200]}
    else:
        sources["gsc"] = {"skipped": "google_search_console not configured"}

    if not urls:
        return {
            "checked": False,
            "reason": (
                "orphan detection requires a URL source independent of the "
                "link graph (sitemap.xml or GSC); a link-following crawl "
                "cannot discover unlinked pages by construction"
            ),
            "urls": set(),
            "sources": sources,
        }
    return {"checked": True, "urls": urls, "sources": sources}


def orphan_analysis(
    universe: dict[str, Any],
    graph: LinkGraph,
    root_key: str,
    pages_by_key: dict[str, dict[str, Any]],
    *,
    crawl_truncated: bool = False,
) -> dict[str, Any]:
    """Orphans = universe minus link-reachable, after alias folding.

    Tiers:
      orphan_page                 crawled, 200, indexable, unreachable — high
                                  (low when the crawl was truncated: coverage
                                  gaps then mimic orphanhood)
      orphan_candidate_uncrawled  in the universe, never seen by the crawl —
                                  the caller should live-confirm a bounded
                                  sample before reporting (medium/low)
    noindex/non-200 pages are excluded — unlinked AND unindexable is usually
    deliberate retirement, not an SEO defect.
    """
    if not universe.get("checked"):
        return {"checked": False, "reason": universe.get("reason", ""),
                "orphan_pages": [], "orphan_candidates_uncrawled": []}

    reachable_set = reachable(graph, root_key)
    refusal = None
    if len(universe["urls"]) > 2 * max(len(graph.nodes), 1):
        refusal = (
            f"universe has {len(universe['urls'])} URLs vs {len(graph.nodes)} "
            "crawled pages — the crawl covers too little of the site for "
            "reachability to mean anything; raise --max-pages"
        )
        return {"checked": False, "reason": refusal,
                "orphan_pages": [], "orphan_candidates_uncrawled": []}

    orphan_pages: list[dict[str, Any]] = []
    uncrawled: list[str] = []
    for key in sorted(universe["urls"]):
        folded = urlnorm.resolve_alias(key, graph.alias_map)
        if folded in reachable_set:
            continue
        rec = pages_by_key.get(folded) or pages_by_key.get(key)
        if rec is None:
            uncrawled.append(key)
        elif is_indexable_html(rec):
            orphan_pages.append({
                "url": rec.get("final_url") or rec.get("url", ""),
                "severity": "low" if crawl_truncated else "high",
                "inbound_links": graph.inbound.get(folded, 0),
                "in_sitemap": True,
            })

    return {
        "checked": True,
        "crawl_truncated": crawl_truncated,
        "orphan_pages": orphan_pages,
        "orphan_candidates_uncrawled": uncrawled,
        "reachable_count": len(reachable_set),
        "universe_count": len(universe["urls"]),
    }


def index_pages(pages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """canonical_key(final destination) -> record, for orphan lookups."""
    return {_node_key(rec): rec for rec in pages if _node_key(rec)}
