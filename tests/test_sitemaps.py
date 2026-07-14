"""Tests for scripts.lib.sitemaps: discovery order and URL-set fetching."""

from __future__ import annotations

import requests

from scripts.lib import sitemaps
from scripts.lib.robots import RobotsPolicy

SITE = "https://mysite.org"


def urlset(*urls: str) -> str:
    locs = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"{locs}</urlset>")


def sitemapindex(*urls: str) -> str:
    locs = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in urls)
    return ('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"{locs}</sitemapindex>")


# ---------------------------------------------------------------------------
# discover
# ---------------------------------------------------------------------------

def test_discover_defaults_without_policy():
    assert sitemaps.discover(SITE) == [
        f"{SITE}/sitemap.xml",
        f"{SITE}/sitemap_index.xml",
        f"{SITE}/wp-sitemap.xml",
    ]


def test_discover_puts_robots_sitemaps_first_and_dedupes():
    policy = RobotsPolicy(sitemaps=[f"{SITE}/custom.xml", "/sitemap.xml"])
    assert sitemaps.discover(SITE, policy) == [
        f"{SITE}/custom.xml",
        f"{SITE}/sitemap.xml",       # relative robots entry, resolved + deduped
        f"{SITE}/sitemap_index.xml",
        f"{SITE}/wp-sitemap.xml",
    ]


# ---------------------------------------------------------------------------
# fetch_url_set
# ---------------------------------------------------------------------------

def test_plain_urlset_found(fake_transport):
    fake_transport.route("GET", f"{SITE}/sitemap.xml",
                         {"body": urlset(f"{SITE}/a", f"{SITE}/b")})
    result = sitemaps.fetch_url_set(SITE)
    assert result["found"] is True
    assert result["page_urls"] == [f"{SITE}/a", f"{SITE}/b"]
    assert result["sitemaps_read"] == [f"{SITE}/sitemap.xml"]
    assert result["truncated"] is False
    assert result["errors"] == []
    # first candidate won: nothing else was fetched
    assert fake_transport.urls == [f"{SITE}/sitemap.xml"]


def test_sitemapindex_followed_one_level(fake_transport):
    fake_transport.route("GET", f"{SITE}/sitemap.xml",
                         {"body": sitemapindex(f"{SITE}/pages.xml", f"{SITE}/posts.xml")})
    fake_transport.route("GET", f"{SITE}/pages.xml", {"body": urlset(f"{SITE}/p1")})
    fake_transport.route("GET", f"{SITE}/posts.xml",
                         {"body": urlset(f"{SITE}/q1", f"{SITE}/q2")})
    result = sitemaps.fetch_url_set(SITE)
    assert result["found"] is True
    assert result["page_urls"] == [f"{SITE}/p1", f"{SITE}/q1", f"{SITE}/q2"]
    assert result["sitemaps_read"] == [
        f"{SITE}/sitemap.xml", f"{SITE}/pages.xml", f"{SITE}/posts.xml",
    ]
    assert result["truncated"] is False


def test_404_first_candidate_falls_through_to_next(fake_transport):
    fake_transport.route("GET", f"{SITE}/sitemap.xml", 404)
    fake_transport.route("GET", f"{SITE}/sitemap_index.xml",
                         {"body": urlset(f"{SITE}/a")})
    result = sitemaps.fetch_url_set(SITE)
    assert result["found"] is True
    assert result["sitemaps_read"] == [f"{SITE}/sitemap_index.xml"]
    assert result["page_urls"] == [f"{SITE}/a"]


def test_non_xml_body_is_unknown_kind_and_falls_through(fake_transport):
    fake_transport.route("GET", f"{SITE}/sitemap.xml",
                         {"body": "this is not xml at all"})
    fake_transport.route("GET", f"{SITE}/sitemap_index.xml",
                         {"body": urlset(f"{SITE}/a")})
    result = sitemaps.fetch_url_set(SITE)
    assert result["found"] is True
    assert result["sitemaps_read"] == [f"{SITE}/sitemap_index.xml"]


def test_fetch_error_recorded_and_next_candidate_tried(fake_transport):
    fake_transport.route("GET", f"{SITE}/sitemap.xml",
                         requests.ConnectionError("nope"))  # retried, then HttpError
    fake_transport.route("GET", f"{SITE}/sitemap_index.xml",
                         {"body": urlset(f"{SITE}/a")})
    result = sitemaps.fetch_url_set(SITE)
    assert result["found"] is True
    assert result["page_urls"] == [f"{SITE}/a"]
    assert len(result["errors"]) == 1


def test_max_urls_truncation(fake_transport):
    fake_transport.route("GET", f"{SITE}/sitemap.xml",
                         {"body": urlset(*(f"{SITE}/p{i}" for i in range(5)))})
    result = sitemaps.fetch_url_set(SITE, max_urls=3)
    assert result["truncated"] is True
    assert result["page_urls"] == [f"{SITE}/p0", f"{SITE}/p1", f"{SITE}/p2"]


def test_child_sitemap_cap_notes_error(fake_transport, monkeypatch):
    monkeypatch.setattr(sitemaps, "MAX_CHILD_SITEMAPS", 2)
    children = [f"{SITE}/c{i}.xml" for i in range(3)]
    fake_transport.route("GET", f"{SITE}/sitemap.xml", {"body": sitemapindex(*children)})
    fake_transport.route("GET", f"{SITE}/c0.xml", {"body": urlset(f"{SITE}/a")})
    fake_transport.route("GET", f"{SITE}/c1.xml", {"body": urlset(f"{SITE}/b")})
    result = sitemaps.fetch_url_set(SITE)
    assert result["found"] is True
    assert result["truncated"] is True
    assert result["page_urls"] == [f"{SITE}/a", f"{SITE}/b"]
    assert f"{SITE}/c2.xml" not in fake_transport.urls  # capped child never fetched
    assert any("child sitemaps" in e for e in result["errors"])


def test_all_candidates_fail(fake_transport):
    for path in sitemaps.DEFAULT_SITEMAP_PATHS:
        fake_transport.route("GET", f"{SITE}{path}", 404)
    result = sitemaps.fetch_url_set(SITE)
    assert result["found"] is False
    assert result["page_urls"] == []
    assert result["sitemaps_read"] == []
