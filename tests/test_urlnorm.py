"""Tests for scripts.lib.urlnorm: the single URL-identity fold."""

from __future__ import annotations

import pytest

from scripts.lib import urlnorm


# ---------------------------------------------------------------------------
# canonical_key
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    # scheme fold
    ("http://mysite.org/a", "https://mysite.org/a"),
    # host case + www fold
    ("https://WWW.MySite.ORG/a", "https://mysite.org/a"),
    # trailing dot on host
    ("https://mysite.org./x", "https://mysite.org/x"),
    # default ports dropped, non-default kept
    ("https://mysite.org:443/x", "https://mysite.org/x"),
    ("http://mysite.org:80/x", "https://mysite.org/x"),
    ("https://mysite.org:8080/x", "https://mysite.org:8080/x"),
    # trailing slash folded on non-root paths only
    ("https://mysite.org/about/", "https://mysite.org/about"),
    ("https://mysite.org/", "https://mysite.org/"),
    # %XX escapes uppercased (path case otherwise preserved)
    ("https://mysite.org/a%2fb", "https://mysite.org/a%2Fb"),
    # tracking params dropped ...
    ("https://mysite.org/x?utm_source=tw&utm_medium=s&fbclid=1&gclid=2", "https://mysite.org/x"),
    # ... but functional params that merely resemble them are KEPT
    ("https://mysite.org/x?ref=nav", "https://mysite.org/x?ref=nav"),
    ("https://mysite.org/x?refresh=1", "https://mysite.org/x?refresh=1"),
    # query pairs sorted
    ("https://mysite.org/x?b=2&a=1", "https://mysite.org/x?a=1&b=2"),
    # fragment dropped
    ("https://mysite.org/x#section", "https://mysite.org/x"),
    # degenerate input never raises
    ("", ""),
    ("http://[junk", "http://[junk"),
])
def test_canonical_key_matrix(url, expected):
    assert urlnorm.canonical_key(url) == expected


def test_canonical_key_slash_variant_and_www_variant_are_same_page():
    assert urlnorm.same_page("http://www.mysite.org/about/", "https://mysite.org/about")


def test_canonical_key_pct_escape_case_variants_fold_together():
    assert urlnorm.canonical_key("https://mysite.org/a%2fb") == \
        urlnorm.canonical_key("https://mysite.org/a%2Fb")


def test_canonical_key_trailing_dot_with_explicit_port():
    assert urlnorm.canonical_key("https://WWW.MySite.ORG.:443/a") == "https://mysite.org/a"


# ---------------------------------------------------------------------------
# host_key / same_site / is_cross_host_canonical
# ---------------------------------------------------------------------------

def test_host_key_on_bare_hostname():
    assert urlnorm.host_key("WWW.MySite.ORG.") == "mysite.org"


def test_host_key_on_full_url():
    assert urlnorm.host_key("https://www.MySite.org:443/path?q=1") == "mysite.org"


def test_same_site_www_variant_true():
    assert urlnorm.same_site("https://www.mysite.org/x", "mysite.org")


def test_same_site_subdomain_false_by_default_true_when_included():
    assert not urlnorm.same_site("https://blog.mysite.org/x", "mysite.org")
    assert urlnorm.same_site("https://blog.mysite.org/x", "mysite.org",
                             include_subdomains=True)


def test_same_site_unrelated_host_false():
    assert not urlnorm.same_site("https://other.org/x", "mysite.org")
    assert not urlnorm.same_site("https://notmysite.org/x", "mysite.org",
                                 include_subdomains=True)


@pytest.mark.parametrize("canonical,page,expected", [
    ("https://www.mysite.org/", "https://mysite.org/page", False),  # www vs apex
    ("http://mysite.org/x", "https://mysite.org/x", False),         # scheme variant
    ("https://evil.org/x", "https://mysite.org/x", True),           # real cross-domain
    ("", "https://mysite.org/x", False),                            # empty canonical
])
def test_is_cross_host_canonical(canonical, page, expected):
    assert urlnorm.is_cross_host_canonical(canonical, page) is expected


# ---------------------------------------------------------------------------
# build_alias_map / resolve_alias
# ---------------------------------------------------------------------------

def test_build_alias_map_maps_redirects_and_skips_error_records():
    pages = [
        {"url": "https://a.org/old", "final_url": "https://a.org/new", "status": 200},
        {"url": "https://a.org/err", "final_url": "https://a.org/x",
         "status": 200, "error": "timeout"},
        {"url": "https://a.org/neg", "final_url": "https://a.org/y", "status": -1},
        # www -> apex folds to the same identity: no self-alias
        {"url": "http://www.a.org/", "final_url": "https://a.org/", "status": 200},
        {"url": "https://a.org/nofinal", "final_url": "", "status": 200},
    ]
    assert urlnorm.build_alias_map(pages) == {
        urlnorm.canonical_key("https://a.org/old"):
            urlnorm.canonical_key("https://a.org/new"),
    }


def test_resolve_alias_follows_chain_to_terminal():
    aliases = {"a": "b", "b": "c"}
    assert urlnorm.resolve_alias("a", aliases) == "c"
    assert urlnorm.resolve_alias("c", aliases) == "c"


def test_resolve_alias_stops_on_cycle():
    aliases = {"a": "b", "b": "a"}
    assert urlnorm.resolve_alias("a", aliases) == "b"


def test_resolve_alias_is_bounded_by_max_hops():
    aliases = {f"k{i}": f"k{i + 1}" for i in range(10)}
    assert urlnorm.resolve_alias("k0", aliases, max_hops=5) == "k5"
