"""Tests for scripts.lib.pagerules: shared page-level predicates."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.lib import pagerules


# ---------------------------------------------------------------------------
# is_noindex
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rec,expected", [
    ({"meta_robots": "noindex, follow"}, True),                 # meta only
    ({"x_robots_tag": "noindex"}, True),                        # header only
    ({"x_robots_tag": "googlebot: noindex, nofollow"}, True),   # noindex inside header
    ({"meta_robots": "none"}, True),                            # none == noindex,nofollow
    ({"meta_robots": "NOINDEX"}, True),                         # case-insensitive
    ({"x_robots_tag": "NONE"}, True),
    ({"meta_robots": "nofollow"}, False),                       # nofollow alone is NOT noindex
    ({"meta_robots": "index, follow"}, False),
    ({}, False),
    ({"meta_robots": None, "x_robots_tag": None}, False),
])
def test_is_noindex_dicts(rec, expected):
    assert pagerules.is_noindex(rec) is expected


def test_is_noindex_works_on_objects_with_attributes():
    assert pagerules.is_noindex(SimpleNamespace(meta_robots="noindex"))
    assert pagerules.is_noindex(SimpleNamespace(x_robots_tag="noindex"))
    assert not pagerules.is_noindex(SimpleNamespace(meta_robots="index"))
    assert not pagerules.is_noindex(SimpleNamespace())  # missing attrs default clean


# ---------------------------------------------------------------------------
# is_nofollow_page
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rec,expected", [
    ({"meta_robots": "noindex, nofollow"}, True),
    ({"x_robots_tag": "nofollow"}, True),
    ({"meta_robots": "none"}, True),
    ({"meta_robots": "noindex"}, False),
    ({}, False),
])
def test_is_nofollow_page(rec, expected):
    assert pagerules.is_nofollow_page(rec) is expected


# ---------------------------------------------------------------------------
# is_html
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("content_type,expected", [
    ("text/html", True),
    ("text/html; charset=utf-8", True),
    ("application/xhtml+xml", True),
    ("Application/XHTML+XML", True),
    ("application/json", False),
    ("text/plain", False),
    ("", False),
    (None, False),
])
def test_is_html(content_type, expected):
    assert pagerules.is_html({"content_type": content_type}) is expected


# ---------------------------------------------------------------------------
# is_indexable_html
# ---------------------------------------------------------------------------

CLEAN = {"status": 200, "content_type": "text/html; charset=utf-8"}


@pytest.mark.parametrize("rec,expected", [
    (dict(CLEAN), True),                                        # 200 + html + clean
    (dict(CLEAN, error="connection reset"), False),             # error set
    (dict(CLEAN, status=404), False),                           # non-200
    (dict(CLEAN, status=301), False),
    (dict(CLEAN, meta_robots="noindex"), False),                # noindex meta
    (dict(CLEAN, x_robots_tag="noindex"), False),               # noindex header
    (dict(CLEAN, content_type="application/json"), False),      # not html
    ({"status": None, "content_type": "text/html"}, False),     # status missing
])
def test_is_indexable_html_matrix(rec, expected):
    assert pagerules.is_indexable_html(rec) is expected


def test_is_indexable_html_on_object_record():
    rec = SimpleNamespace(status=200, content_type="text/html",
                          meta_robots="", x_robots_tag="", error="")
    assert pagerules.is_indexable_html(rec)
    rec.meta_robots = "noindex"
    assert not pagerules.is_indexable_html(rec)
