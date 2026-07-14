"""Tests for scripts.lib.linkgraph: alias-folded graph building, reachability,
and honest orphan detection."""

from __future__ import annotations

from scripts.lib import linkgraph, urlnorm

SITE = "https://mysite.org"


def page(url, final_url=None, status=200, content_type="text/html",
         internal_links=None, meta_robots="", error=""):
    return {
        "url": url,
        "final_url": final_url or url,
        "status": status,
        "content_type": content_type,
        "internal_links": internal_links or [],
        "meta_robots": meta_robots,
        "error": error,
    }


def key(url: str) -> str:
    return urlnorm.canonical_key(url)


# ---------------------------------------------------------------------------
# build_graph
# ---------------------------------------------------------------------------

def test_build_graph_folds_aliases_so_redirect_target_is_not_orphaned():
    pages = [
        page(f"{SITE}/", internal_links=[f"{SITE}/old"]),
        page(f"{SITE}/old", final_url=f"{SITE}/new"),  # redirecting alias
    ]
    graph = linkgraph.build_graph(pages)
    root = key(f"{SITE}/")
    # /old's redirecting record contributes an alias, not a separate node.
    assert key(f"{SITE}/new") in graph.nodes
    assert key(f"{SITE}/old") not in graph.nodes
    # The root's link to /old is credited to /new via the alias map.
    assert graph.adjacency[root] == {key(f"{SITE}/new")}
    reachable = linkgraph.reachable(graph, root)
    assert key(f"{SITE}/new") in reachable  # not orphaned


def test_inbound_counts_distinct_sources_not_total_links():
    pages = [
        page(f"{SITE}/a", internal_links=[f"{SITE}/target"]),
        page(f"{SITE}/b", internal_links=[f"{SITE}/target", f"{SITE}/target"]),
        page(f"{SITE}/target"),
    ]
    graph = linkgraph.build_graph(pages)
    assert graph.inbound[key(f"{SITE}/target")] == 2  # /a and /b, not 3 links


def test_reachable_bfs_walks_multiple_hops():
    pages = [
        page(f"{SITE}/", internal_links=[f"{SITE}/a"]),
        page(f"{SITE}/a", internal_links=[f"{SITE}/b"]),
        page(f"{SITE}/b", internal_links=[]),
        page(f"{SITE}/isolated", internal_links=[]),
    ]
    graph = linkgraph.build_graph(pages)
    root = key(f"{SITE}/")
    reached = linkgraph.reachable(graph, root)
    assert reached == {key(f"{SITE}/"), key(f"{SITE}/a"), key(f"{SITE}/b")}
    assert key(f"{SITE}/isolated") not in reached


def test_build_graph_skips_error_records():
    pages = [
        page(f"{SITE}/", internal_links=[f"{SITE}/broken"]),
        {"url": f"{SITE}/broken", "final_url": "", "status": -1,
         "error": "timeout", "internal_links": []},
    ]
    graph = linkgraph.build_graph(pages)
    assert key(f"{SITE}/broken") not in graph.nodes


# ---------------------------------------------------------------------------
# orphan_analysis
# ---------------------------------------------------------------------------

def test_orphan_page_unreachable_crawled_200_indexable_is_high_severity():
    pages = [
        page(f"{SITE}/"),
        page(f"{SITE}/orphan"),
    ]
    graph = linkgraph.build_graph(pages)
    root = key(f"{SITE}/")
    universe = {"checked": True, "urls": {key(f"{SITE}/"), key(f"{SITE}/orphan")}}
    result = linkgraph.orphan_analysis(universe, graph, root, linkgraph.index_pages(pages))
    assert len(result["orphan_pages"]) == 1
    assert result["orphan_pages"][0]["url"] == f"{SITE}/orphan"
    assert result["orphan_pages"][0]["severity"] == "high"
    assert result["orphan_candidates_uncrawled"] == []


def test_orphan_page_severity_low_when_crawl_truncated():
    pages = [page(f"{SITE}/"), page(f"{SITE}/orphan")]
    graph = linkgraph.build_graph(pages)
    root = key(f"{SITE}/")
    universe = {"checked": True, "urls": {key(f"{SITE}/"), key(f"{SITE}/orphan")}}
    result = linkgraph.orphan_analysis(
        universe, graph, root, linkgraph.index_pages(pages), crawl_truncated=True)
    assert result["orphan_pages"][0]["severity"] == "low"
    assert result["crawl_truncated"] is True


def test_in_universe_never_crawled_is_uncrawled_candidate():
    pages = [page(f"{SITE}/")]
    graph = linkgraph.build_graph(pages)
    root = key(f"{SITE}/")
    universe = {"checked": True, "urls": {key(f"{SITE}/"), key(f"{SITE}/never-seen")}}
    result = linkgraph.orphan_analysis(universe, graph, root, linkgraph.index_pages(pages))
    assert result["orphan_pages"] == []
    assert result["orphan_candidates_uncrawled"] == [key(f"{SITE}/never-seen")]


def test_noindex_page_excluded_from_orphan_pages():
    pages = [
        page(f"{SITE}/"),
        page(f"{SITE}/hidden", meta_robots="noindex"),
    ]
    graph = linkgraph.build_graph(pages)
    root = key(f"{SITE}/")
    universe = {"checked": True, "urls": {key(f"{SITE}/"), key(f"{SITE}/hidden")}}
    result = linkgraph.orphan_analysis(universe, graph, root, linkgraph.index_pages(pages))
    assert result["orphan_pages"] == []
    # Excluded entirely -- neither an orphan finding nor an uncrawled candidate
    # (it WAS crawled, just not indexable).
    assert result["orphan_candidates_uncrawled"] == []


def test_universe_checked_false_passes_through_reason():
    pages = [page(f"{SITE}/")]
    graph = linkgraph.build_graph(pages)
    root = key(f"{SITE}/")
    universe = {"checked": False, "reason": "no sitemap and no GSC"}
    result = linkgraph.orphan_analysis(universe, graph, root, linkgraph.index_pages(pages))
    assert result == {
        "checked": False, "reason": "no sitemap and no GSC",
        "orphan_pages": [], "orphan_candidates_uncrawled": [],
    }


def test_coverage_ratio_refusal_when_universe_more_than_double_nodes():
    pages = [page(f"{SITE}/")]  # 1 crawled node
    graph = linkgraph.build_graph(pages)
    root = key(f"{SITE}/")
    universe = {"checked": True, "urls": {f"{SITE}/p{i}" for i in range(5)}}  # 5 > 2*1
    result = linkgraph.orphan_analysis(universe, graph, root, linkgraph.index_pages(pages))
    assert result["checked"] is False
    assert "raise --max-pages" in result["reason"]
    assert result["orphan_pages"] == []


def test_index_pages_keys_by_final_destination():
    pages = [
        page(f"{SITE}/old", final_url=f"{SITE}/new"),
    ]
    indexed = linkgraph.index_pages(pages)
    assert key(f"{SITE}/new") in indexed
    assert key(f"{SITE}/old") not in indexed
    assert indexed[key(f"{SITE}/new")]["url"] == f"{SITE}/old"


# ---------------------------------------------------------------------------
# known_url_universe
# ---------------------------------------------------------------------------

def test_known_url_universe_sitemap_only_when_no_gsc(monkeypatch, tmp_repo):
    from scripts.lib import sitemaps

    def fake_fetch_url_set(site_url, policy=None, **kw):
        return {
            "found": True,
            "page_urls": [f"{SITE}/a", f"{SITE}/b"],
            "sitemaps_read": [f"{SITE}/sitemap.xml"],
            "truncated": False,
            "errors": [],
        }

    monkeypatch.setattr(sitemaps, "fetch_url_set", fake_fetch_url_set)
    cfg = tmp_repo.make_config(env={})  # no GSC creds configured
    result = linkgraph.known_url_universe(cfg, SITE)
    assert result["checked"] is True
    assert result["urls"] == {key(f"{SITE}/a"), key(f"{SITE}/b")}
    assert result["sources"]["sitemap"]["urls"] == 2
    assert result["sources"]["gsc"] == {"skipped": "google_search_console not configured"}


def test_known_url_universe_no_sitemap_no_gsc_is_not_checked(monkeypatch, tmp_repo):
    from scripts.lib import sitemaps

    def fake_fetch_url_set(site_url, policy=None, **kw):
        return {"found": False, "page_urls": [], "sitemaps_read": [],
                "truncated": False, "errors": ["no sitemap found"]}

    monkeypatch.setattr(sitemaps, "fetch_url_set", fake_fetch_url_set)
    cfg = tmp_repo.make_config(env={})
    result = linkgraph.known_url_universe(cfg, SITE)
    assert result["checked"] is False
    assert "cannot discover unlinked pages" in result["reason"]
    assert result["urls"] == set()
