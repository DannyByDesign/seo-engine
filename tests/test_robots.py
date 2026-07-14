"""Tests for scripts.lib.robots: RFC 9309 parsing, group merge, evaluation,
and fetch semantics."""

from __future__ import annotations

import pytest
import requests

from scripts.lib import http_util, robots
from scripts.lib.robots import Group, RobotsPolicy

SITE = "https://mysite.org"


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------

def test_parse_consecutive_ua_lines_merge_into_one_group():
    policy = robots.parse("User-agent: GPTBot\nUser-agent: ClaudeBot\nDisallow: /x\n")
    assert len(policy.groups) == 1
    assert policy.groups[0].agents == ["gptbot", "claudebot"]
    assert policy.groups[0].rules == [("disallow", "/x")]


def test_parse_blank_line_does_not_terminate_group():
    policy = robots.parse("User-agent: GPTBot\n\n\nDisallow: /x\n")
    assert len(policy.groups) == 1
    assert policy.groups[0].rules == [("disallow", "/x")]


def test_parse_ua_line_after_rules_starts_new_group():
    policy = robots.parse(
        "User-agent: A\nDisallow: /a\nUser-agent: B\nDisallow: /b\n"
    )
    assert len(policy.groups) == 2
    assert policy.groups[0].agents == ["a"]
    assert policy.groups[0].rules == [("disallow", "/a")]
    assert policy.groups[1].agents == ["b"]
    assert policy.groups[1].rules == [("disallow", "/b")]


def test_parse_strips_comments():
    policy = robots.parse(
        "# full-line comment\nUser-agent: *  # bots\nDisallow: /x # keep out\n"
    )
    assert policy.groups[0].agents == ["*"]
    assert policy.groups[0].rules == [("disallow", "/x")]


def test_parse_collects_sitemap_lines():
    policy = robots.parse(
        "Sitemap: https://mysite.org/a.xml\nUser-agent: *\nDisallow:\n"
        "Sitemap: https://mysite.org/b.xml\n"
    )
    assert policy.sitemaps == ["https://mysite.org/a.xml", "https://mysite.org/b.xml"]


def test_parse_crawl_delay():
    policy = robots.parse("User-agent: SlowBot\nCrawl-delay: 2.5\n")
    assert policy.groups[0].crawl_delay == 2.5


def test_parse_ignores_rules_before_any_user_agent():
    policy = robots.parse("Disallow: /orphan\nUser-agent: *\nDisallow: /x\n")
    assert len(policy.groups) == 1
    assert policy.groups[0].rules == [("disallow", "/x")]


# ---------------------------------------------------------------------------
# rules_for — the RFC 9309 all-matching-groups merge
# ---------------------------------------------------------------------------

B14 = """
User-agent: PerplexityBot
Disallow: /private/

User-agent: Googlebot
Disallow: /google-only/

User-agent: PerplexityBot
Disallow: /internal/
"""


def test_rules_for_merges_separate_groups_for_same_agent():
    policy = robots.parse(B14)
    assert policy.rules_for("PerplexityBot") == [
        ("disallow", "/private/"),
        ("disallow", "/internal/"),
    ]
    # And both rules are live in evaluation:
    assert not policy.allowed("PerplexityBot", f"{SITE}/private/page")
    assert not policy.allowed("PerplexityBot", f"{SITE}/internal/page")
    assert policy.allowed("PerplexityBot", f"{SITE}/public/page")


def test_rules_for_token_match_is_case_insensitive():
    policy = robots.parse(B14)
    assert policy.rules_for("PERPLEXITYBOT") == policy.rules_for("perplexitybot")
    assert len(policy.rules_for("PERPLEXITYBOT")) == 2


def test_rules_for_unmatched_token_falls_back_to_merged_star_groups():
    policy = robots.parse(
        "User-agent: *\nDisallow: /a\n\nUser-agent: *\nDisallow: /b\n"
    )
    assert policy.rules_for("RandomBot") == [("disallow", "/a"), ("disallow", "/b")]


def test_rules_for_matched_token_does_not_inherit_star_rules():
    policy = robots.parse(
        "User-agent: *\nDisallow: /all\n\nUser-agent: SpecialBot\nDisallow: /special\n"
    )
    assert policy.rules_for("SpecialBot") == [("disallow", "/special")]
    assert policy.allowed("SpecialBot", f"{SITE}/all/page")
    assert not policy.allowed("OtherBot", f"{SITE}/all/page")


# ---------------------------------------------------------------------------
# _evaluate via allowed()
# ---------------------------------------------------------------------------

def test_longest_match_wins():
    policy = robots.parse("User-agent: *\nDisallow: /\nAllow: /public\n")
    assert policy.allowed("bot", f"{SITE}/public/x")
    assert not policy.allowed("bot", f"{SITE}/private/x")


def test_tie_goes_to_allow():
    policy = robots.parse("User-agent: *\nDisallow: /dir\nAllow: /dir\n")
    assert policy.allowed("bot", f"{SITE}/dir/page")


def test_empty_allow_pattern_matches_nothing():
    # The empty-Allow-nullifies-Disallow bug: `Allow:` (no value) must be a
    # no-op, not a zero-length always-match that out-competes nothing and
    # definitely not a blanket allow.
    policy = robots.parse("User-agent: *\nDisallow: /\nAllow:\n")
    assert not policy.allowed("bot", f"{SITE}/anything")


def test_wildcard_mid_pattern():
    policy = robots.parse("User-agent: *\nDisallow: /private/*/secret\n")
    assert not policy.allowed("bot", f"{SITE}/private/a/secret")
    assert not policy.allowed("bot", f"{SITE}/private/a/b/secret")
    assert policy.allowed("bot", f"{SITE}/private/a/other")


def test_dollar_end_anchor():
    policy = robots.parse("User-agent: *\nDisallow: /*.pdf$\n")
    assert not policy.allowed("bot", f"{SITE}/a.pdf")
    assert policy.allowed("bot", f"{SITE}/a.pdfx")


def test_query_string_is_part_of_matched_path():
    policy = robots.parse("User-agent: *\nDisallow: /search?q=\n")
    assert not policy.allowed("bot", f"{SITE}/search?q=stuff")
    assert policy.allowed("bot", f"{SITE}/search")


# ---------------------------------------------------------------------------
# fetch semantics (through the fake transport)
# ---------------------------------------------------------------------------

def test_fetch_200_parses_body(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", {
        "status": 200,
        "body": "User-agent: *\nDisallow: /blocked/\nSitemap: https://mysite.org/s.xml\n",
    })
    policy = robots.fetch(SITE)
    assert policy.source_status == 200
    assert not policy.allow_all and not policy.disallow_all
    assert not policy.allowed("anybot", f"{SITE}/blocked/x")
    assert policy.allowed("anybot", f"{SITE}/open")
    assert policy.sitemaps == ["https://mysite.org/s.xml"]


def test_fetch_sends_engine_user_agent(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", {"status": 200, "body": ""})
    robots.fetch(SITE)
    method, url, kwargs = fake_transport.calls[0]
    assert (method, url) == ("GET", f"{SITE}/robots.txt")
    assert kwargs["headers"]["User-Agent"] == http_util.USER_AGENT


def test_fetch_honors_custom_user_agent(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", {"status": 200, "body": ""})
    robots.fetch(SITE, user_agent="TestBot/1.0")
    assert fake_transport.calls[0][2]["headers"]["User-Agent"] == "TestBot/1.0"


@pytest.mark.parametrize("status", [401, 403, 404])
def test_fetch_4xx_means_allow_all(fake_transport, status):
    fake_transport.route("GET", f"{SITE}/robots.txt", status)
    policy = robots.fetch(SITE)
    assert policy.allow_all is True
    assert policy.disallow_all is False
    assert policy.source_status == status
    assert policy.allowed("anybot", f"{SITE}/anything")


def test_fetch_5xx_means_disallow_all_with_fetch_error(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", 500)  # repeats across retries
    policy = robots.fetch(SITE)
    assert policy.disallow_all is True
    assert policy.allow_all is False
    assert policy.source_status == 500
    assert "500" in policy.fetch_error
    assert not policy.allowed("anybot", f"{SITE}/anything")


def test_fetch_network_failure_means_disallow_all_with_fetch_error(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt",
                         requests.ConnectionError("no route to host"))
    policy = robots.fetch(SITE)
    assert policy.disallow_all is True
    assert policy.source_status == -1
    assert policy.fetch_error  # carries the sanitized HttpError message
    assert not policy.allowed("anybot", f"{SITE}/anything")


# ---------------------------------------------------------------------------
# policy accessors
# ---------------------------------------------------------------------------

def test_allowed_short_circuits_on_allow_all_and_disallow_all():
    blocked_group = Group(agents=["*"], rules=[("disallow", "/")])
    assert RobotsPolicy(allow_all=True, groups=[blocked_group]) \
        .allowed("bot", f"{SITE}/x")
    open_group = Group(agents=["*"], rules=[("allow", "/")])
    assert not RobotsPolicy(disallow_all=True, groups=[open_group]) \
        .allowed("bot", f"{SITE}/x")


def test_crawl_delay_returns_max_across_matching_groups():
    policy = robots.parse(
        "User-agent: bot\nCrawl-delay: 1.5\n\nUser-agent: bot\nCrawl-delay: 3\n"
    )
    assert policy.crawl_delay("bot") == 3.0
    assert policy.crawl_delay("stranger") is None


def test_disallowed_paths_lists_only_nonempty_disallows():
    policy = robots.parse(
        "User-agent: bot\nDisallow: /a\nDisallow:\nAllow: /b\nDisallow: /c\n"
    )
    assert policy.disallowed_paths("bot") == ["/a", "/c"]
