"""Tests for scripts.lib.gsc pure logic: property matching, the reporting
date, pagination, and property resolution/caching (no real Google API calls —
list_sites/search_analytics_query/save_site_config are monkeypatched)."""

from __future__ import annotations

import datetime

import pytest

from scripts.lib import gsc

SITE = "https://mysite.org"


def entry(site_url: str, permission: str = "siteOwner") -> dict:
    return {"siteUrl": site_url, "permissionLevel": permission}


def test_match_property_prefers_exact_url_prefix_over_sc_domain():
    entries = [entry(f"{SITE}/"), entry("sc-domain:mysite.org")]
    best, matches = gsc._match_property(SITE, entries)
    assert best == f"{SITE}/"
    assert matches[0] == f"{SITE}/"


def test_match_property_sc_domain_fallback_when_no_prefix_property():
    entries = [entry("sc-domain:mysite.org")]
    best, matches = gsc._match_property(SITE, entries)
    assert best == "sc-domain:mysite.org"


def test_match_property_sc_domain_parent_label_candidate_for_subdomain():
    entries = [entry("sc-domain:mysite.org")]
    best, matches = gsc._match_property("https://blog.mysite.org", entries)
    assert best == "sc-domain:mysite.org"


def test_match_property_scheme_variant_matches():
    entries = [entry(f"http://mysite.org/")]
    best, matches = gsc._match_property(SITE, entries)
    assert best == "http://mysite.org/"


def test_match_property_www_variant_matches():
    entries = [entry("https://www.mysite.org/")]
    best, matches = gsc._match_property(SITE, entries)
    assert best == "https://www.mysite.org/"


def test_match_property_excludes_unverified_entries():
    entries = [entry(f"{SITE}/", permission="siteUnverifiedUser")]
    best, matches = gsc._match_property(SITE, entries)
    assert best is None
    assert matches == []


def test_match_property_no_entries_returns_none_and_empty_list():
    assert gsc._match_property(SITE, []) == (None, [])


def test_match_property_no_overlapping_entries_returns_none():
    entries = [entry("https://totally-different.example/")]
    best, matches = gsc._match_property(SITE, entries)
    assert best is None
    assert matches == []


def test_gsc_today_returns_a_date():
    today = gsc.gsc_today()
    assert isinstance(today, datetime.date)


def test_pagination_concatenates_rows_across_full_pages_then_short_page(monkeypatch):
    calls = []

    def fake_query(cfg, start_date, end_date, *, dimensions=None, row_limit=1000,
                   start_row=0, search_type="web", property_id=None):
        calls.append(start_row)
        if start_row == 0:
            return {"rows": [{"keys": ["a"]}] * gsc.MAX_ROWS_PER_REQUEST}
        return {"rows": [{"keys": ["b"]}] * 100}

    monkeypatch.setattr(gsc, "search_analytics_query", fake_query)
    rows, hit_cap = gsc.search_analytics_query_all(
        None, "2024-01-01", "2024-01-31", max_rows=200_000)
    assert len(rows) == gsc.MAX_ROWS_PER_REQUEST + 100
    assert hit_cap is False
    assert calls == [0, gsc.MAX_ROWS_PER_REQUEST]


def test_pagination_hit_cap_true_when_pages_always_full(monkeypatch):
    def fake_query(cfg, start_date, end_date, *, dimensions=None, row_limit=1000,
                   start_row=0, search_type="web", property_id=None):
        return {"rows": [{"keys": ["x"]}] * row_limit}

    monkeypatch.setattr(gsc, "search_analytics_query", fake_query)
    rows, hit_cap = gsc.search_analytics_query_all(
        None, "2024-01-01", "2024-01-31", max_rows=60_000)
    assert len(rows) == 60_000
    assert hit_cap is True


def test_pagination_empty_first_page_returns_no_rows_not_hit_cap(monkeypatch):
    def fake_query(cfg, start_date, end_date, *, dimensions=None, row_limit=1000,
                   start_row=0, search_type="web", property_id=None):
        return {"rows": []}

    monkeypatch.setattr(gsc, "search_analytics_query", fake_query)
    rows, hit_cap = gsc.search_analytics_query_all(None, "2024-01-01", "2024-01-31")
    assert rows == []
    assert hit_cap is False


def test_resolve_property_cached_value_skips_list_sites(monkeypatch, tmp_repo):
    cfg = tmp_repo.make_config(site={"site_url": SITE, "gsc_property": f"{SITE}/"})

    def boom(cfg):
        raise AssertionError("list_sites should not be called when cached")

    monkeypatch.setattr(gsc, "list_sites", boom)
    assert gsc.resolve_property(cfg) == f"{SITE}/"


def test_resolve_property_discovers_and_persists_when_uncached(monkeypatch, tmp_repo):
    cfg = tmp_repo.make_config(site={"site_url": SITE})
    saved = {}

    monkeypatch.setattr(gsc, "list_sites", lambda cfg: [entry(f"{SITE}/")])
    def fake_save(cfg, updates):
        saved.update(updates)
        cfg.site.update(updates)
    monkeypatch.setattr(gsc, "save_site_config", fake_save)

    prop = gsc.resolve_property(cfg)
    assert prop == f"{SITE}/"
    assert saved["gsc_property"] == f"{SITE}/"


def test_resolve_property_force_re_resolves_even_when_cached(monkeypatch, tmp_repo):
    cfg = tmp_repo.make_config(site={"site_url": SITE, "gsc_property": "sc-domain:stale.org"})
    monkeypatch.setattr(gsc, "list_sites", lambda cfg: [entry(f"{SITE}/")])
    monkeypatch.setattr(gsc, "save_site_config", lambda cfg, updates: cfg.site.update(updates))

    prop = gsc.resolve_property(cfg, force=True)
    assert prop == f"{SITE}/"


def test_resolve_property_no_match_raises_with_visible_properties_listed(monkeypatch, tmp_repo):
    cfg = tmp_repo.make_config(site={"site_url": SITE})
    monkeypatch.setattr(gsc, "list_sites", lambda cfg: [entry("https://unrelated.example/")])

    with pytest.raises(gsc.GscPropertyError) as ei:
        gsc.resolve_property(cfg)
    msg = str(ei.value)
    assert "https://unrelated.example/" in msg
    assert SITE in msg
