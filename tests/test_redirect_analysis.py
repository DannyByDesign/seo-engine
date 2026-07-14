"""Tests for scripts.lib.redirect_analysis: honest redirect taxonomy over
crawl snapshots (plain dicts, no transport involved)."""

from __future__ import annotations

import pytest

from scripts.lib import redirect_analysis as ra

SITE = "https://mysite.org"


def hop(url: str, status: int = 301, location: str = "") -> dict:
    return {"url": url, "status": status, "location": location}


# ---------------------------------------------------------------------------
# classify_record
# ---------------------------------------------------------------------------

def test_too_many_redirects_error_is_critical_redirect_loop():
    record = {
        "url": f"{SITE}/loop",
        "error_type": "too_many_redirects",
        "redirect_chain": [hop(f"{SITE}/loop", location=f"{SITE}/loop2"),
                            hop(f"{SITE}/loop2", location=f"{SITE}/loop")],
        "final_url": "",
    }
    result = ra.classify_record(record)
    assert result["type"] == "redirect_loop"
    assert result["severity"] == "critical"
    assert result["auto_fixable"] is False


def test_verbatim_repeat_in_hop_sequence_is_loop():
    record = {
        "url": f"{SITE}/a",
        "redirect_chain": [hop(f"{SITE}/a", location=f"{SITE}/b"),
                            hop(f"{SITE}/b", location=f"{SITE}/a")],
        "final_url": f"{SITE}/a",
    }
    result = ra.classify_record(record)
    assert result["type"] == "redirect_loop"
    assert result["severity"] == "critical"
    assert result["hops"] == [f"{SITE}/a", f"{SITE}/b", f"{SITE}/a"]


def test_single_normalizing_hop_is_normalizing_redirect_info():
    record = {
        "url": f"{SITE}/foo",
        "redirect_chain": [hop(f"{SITE}/foo", location=f"{SITE}/foo/")],
        "final_url": f"{SITE}/foo/",
    }
    result = ra.classify_record(record)
    assert result["type"] == "normalizing_redirect"
    assert result["severity"] == "info"


def test_single_substantive_hop_is_not_a_finding():
    record = {
        "url": f"{SITE}/old-page",
        "redirect_chain": [hop(f"{SITE}/old-page", location=f"{SITE}/new-page")],
        "final_url": f"{SITE}/new-page",
    }
    assert ra.classify_record(record) is None


def test_two_hop_mixed_chain_is_medium_redirect_chain():
    record = {
        "url": f"{SITE}/a",
        "redirect_chain": [hop(f"{SITE}/a", location=f"{SITE}/b"),
                            hop(f"{SITE}/b", location=f"{SITE}/c")],
        "final_url": f"{SITE}/c",
    }
    result = ra.classify_record(record)
    assert result["type"] == "redirect_chain"
    assert result["severity"] == "medium"


def test_three_hop_chain_is_high_severity():
    record = {
        "url": f"{SITE}/a",
        "redirect_chain": [hop(f"{SITE}/a", location=f"{SITE}/b"),
                            hop(f"{SITE}/b", location=f"{SITE}/c"),
                            hop(f"{SITE}/c", location=f"{SITE}/d")],
        "final_url": f"{SITE}/d",
    }
    result = ra.classify_record(record)
    assert result["type"] == "redirect_chain"
    assert result["severity"] == "high"


def test_multi_hop_all_normalizing_is_canonicalization_chain_low():
    # http -> https -> www, same page identity throughout.
    record = {
        "url": "http://mysite.org/page",
        "redirect_chain": [
            hop("http://mysite.org/page", location="https://mysite.org/page"),
            hop("https://mysite.org/page", location="https://www.mysite.org/page"),
        ],
        "final_url": "https://www.mysite.org/page",
    }
    result = ra.classify_record(record)
    assert result["type"] == "canonicalization_chain"
    assert result["severity"] == "low"


def test_no_redirect_chain_returns_none():
    assert ra.classify_record({"url": f"{SITE}/plain", "redirect_chain": []}) is None
    assert ra.classify_record({"url": f"{SITE}/plain"}) is None


# ---------------------------------------------------------------------------
# classify_snapshot
# ---------------------------------------------------------------------------

def test_link_to_redirect_emitted_for_internal_links_to_substantive_redirect():
    # classify_record(target) must itself be a finding (not None, not
    # normalizing) for link_to_redirect to fire — a single substantive hop
    # classifies as None ("normal moved page"), so use a 2-hop chain here.
    pages = [
        {
            "url": f"{SITE}/",
            "status": 200,
            "internal_links": [f"{SITE}/old"],
        },
        {
            "url": f"{SITE}/old",
            "status": 301,
            "redirect_chain": [hop(f"{SITE}/old", location=f"{SITE}/mid"),
                                hop(f"{SITE}/mid", location=f"{SITE}/new")],
            "final_url": f"{SITE}/new",
        },
    ]
    result = ra.classify_snapshot(pages)
    link_findings = result["findings"]["link_to_redirect"]
    assert len(link_findings) == 1
    assert link_findings[0]["url"] == f"{SITE}/old"
    assert link_findings[0]["final_url"] == f"{SITE}/new"
    assert link_findings[0]["referrers"] == [f"{SITE}/"]
    assert result["counts"]["link_to_redirect"] == 1


def test_link_to_redirect_emitted_for_single_hop_substantive_redirect():
    pages = [
        {
            "url": f"{SITE}/",
            "status": 200,
            "internal_links": [f"{SITE}/old-page"],
        },
        {
            "url": f"{SITE}/old-page",
            "status": 301,
            "redirect_chain": [hop(f"{SITE}/old-page", location=f"{SITE}/new-page")],
            "final_url": f"{SITE}/new-page",
        },
    ]
    result = ra.classify_snapshot(pages)
    link_findings = result["findings"]["link_to_redirect"]
    assert len(link_findings) == 1
    assert link_findings[0]["url"] == f"{SITE}/old-page"
    assert link_findings[0]["final_url"] == f"{SITE}/new-page"


def test_link_to_redirect_not_emitted_for_normalizing_redirect_targets():
    pages = [
        {
            "url": f"{SITE}/",
            "status": 200,
            "internal_links": [f"{SITE}/foo"],
        },
        {
            "url": f"{SITE}/foo",
            "status": 301,
            "redirect_chain": [hop(f"{SITE}/foo", location=f"{SITE}/foo/")],
            "final_url": f"{SITE}/foo/",
        },
    ]
    result = ra.classify_snapshot(pages)
    assert result["findings"]["link_to_redirect"] == []
    assert result["counts"]["link_to_redirect"] == 0


def test_classify_snapshot_counts_dict_tallies_all_types():
    pages = [
        {  # redirect_loop
            "url": f"{SITE}/loop",
            "error_type": "too_many_redirects",
            "redirect_chain": [hop(f"{SITE}/loop")],
        },
        {  # redirect_chain (2 hops, medium)
            "url": f"{SITE}/a",
            "redirect_chain": [hop(f"{SITE}/a", location=f"{SITE}/b"),
                                hop(f"{SITE}/b", location=f"{SITE}/c")],
            "final_url": f"{SITE}/c",
        },
        {  # not a redirect at all
            "url": f"{SITE}/plain",
            "status": 200,
        },
    ]
    result = ra.classify_snapshot(pages)
    assert result["counts"]["redirect_loop"] == 1
    assert result["counts"]["redirect_chain"] == 1
    assert result["counts"]["canonicalization_chain"] == 0
    assert result["counts"]["normalizing_redirect"] == 0


# ---------------------------------------------------------------------------
# new_redirect_regressions
# ---------------------------------------------------------------------------

def test_new_redirect_regression_cross_host_is_high():
    prev = {f"{SITE}/page": {"status": 200, "redirect_chain": []}}
    cur = {
        f"{SITE}/page": {
            "url": f"{SITE}/page",
            "status": 301,
            "redirect_chain": [hop(f"{SITE}/page", location="https://evil.example/page")],
            "final_url": "https://evil.example/page",
        }
    }
    findings = ra.new_redirect_regressions(prev, cur)
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"
    assert findings[0]["human_review_required"] is True


def test_new_redirect_regression_same_host_is_medium():
    prev = {f"{SITE}/page": {"status": 200, "redirect_chain": []}}
    cur = {
        f"{SITE}/page": {
            "url": f"{SITE}/page",
            "status": 301,
            "redirect_chain": [hop(f"{SITE}/page", location=f"{SITE}/moved")],
            "final_url": f"{SITE}/moved",
        }
    }
    findings = ra.new_redirect_regressions(prev, cur)
    assert len(findings) == 1
    assert findings[0]["severity"] == "medium"


def test_new_redirect_regression_prev_already_redirecting_is_no_finding():
    prev = {
        f"{SITE}/page": {
            "status": 301,
            "redirect_chain": [hop(f"{SITE}/page", location=f"{SITE}/other")],
        }
    }
    cur = {
        f"{SITE}/page": {
            "url": f"{SITE}/page",
            "status": 301,
            "redirect_chain": [hop(f"{SITE}/page", location=f"{SITE}/moved")],
            "final_url": f"{SITE}/moved",
        }
    }
    assert ra.new_redirect_regressions(prev, cur) == []


def test_new_redirect_regression_prev_missing_is_no_finding():
    prev: dict = {}
    cur = {
        f"{SITE}/page": {
            "url": f"{SITE}/page",
            "status": 301,
            "redirect_chain": [hop(f"{SITE}/page", location=f"{SITE}/moved")],
            "final_url": f"{SITE}/moved",
        }
    }
    assert ra.new_redirect_regressions(prev, cur) == []


def test_new_redirect_regression_current_with_no_chain_is_skipped():
    prev = {f"{SITE}/page": {"status": 200, "redirect_chain": []}}
    cur = {f"{SITE}/page": {"url": f"{SITE}/page", "status": 200, "redirect_chain": []}}
    assert ra.new_redirect_regressions(prev, cur) == []
