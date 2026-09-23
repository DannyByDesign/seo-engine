"""Tests for scripts.lib.crawler: robots gating, BFS link discovery, record
extraction, and crawl_to_file's JSONL + summary output."""

from __future__ import annotations

import json

import pytest
import requests

from scripts.lib import crawler

SITE = "https://mysite.org"


def html(body: str, title: str = "Page") -> str:
    return f"<html><head><title>{title}</title></head><body>{body}</body></html>"


def page_resp(body: str, **kw):
    kw.setdefault("headers", {"Content-Type": "text/html; charset=utf-8"})
    return {"status": 200, "body": body, **kw}


def robots_allow_all():
    return {"status": 200, "body": "User-agent: *\nAllow: /\n"}


def test_robots_fetched_first_with_engine_user_agent_then_pages_crawled(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", robots_allow_all())
    fake_transport.route("GET", SITE, page_resp(html("<p>hi</p>")))
    stats: dict = {}
    records = list(crawler.crawl(SITE, stats=stats))
    assert len(records) == 1
    assert records[0].status == 200
    method, url, kwargs = fake_transport.calls[0]
    assert (method, url) == ("GET", f"{SITE}/robots.txt")
    from scripts.lib import http_util
    assert kwargs["headers"]["User-Agent"] == http_util.USER_AGENT
    assert stats["robots_status"] == "ok"


def test_robots_403_is_allow_all_and_pages_crawled(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", 403)
    fake_transport.route("GET", SITE, page_resp(html("hi")))
    stats: dict = {}
    records = list(crawler.crawl(SITE, stats=stats))
    assert len(records) == 1
    assert stats["robots_status"] == "unauthorized_allow_all"
    assert stats["all_blocked"] is False


def test_robots_500_blocks_everything(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", 500)
    stats: dict = {}
    records = list(crawler.crawl(SITE, stats=stats))
    assert records == []
    assert stats["all_blocked"] is True
    assert stats["robots_status"] == "server_error_blocked"
    assert all(url == f"{SITE}/robots.txt" for _, url, _ in fake_transport.calls)


def test_robots_disallow_all_body_blocks_start_url(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", {
        "status": 200, "body": "User-agent: *\nDisallow: /\n",
    })
    stats: dict = {}
    records = list(crawler.crawl(SITE, stats=stats))
    assert records == []
    assert stats["all_blocked"] is True
    assert stats["blocked_by_robots"] == 1


def test_bfs_enqueues_same_site_links_only(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", robots_allow_all())
    fake_transport.route("GET", f"{SITE}/about", page_resp(html("about page", title="About")))
    fake_transport.route("GET", SITE, page_resp(html(
        f'<a href="{SITE}/about">About</a>'
        f'<a href="https://other.example/x">Off-site</a>'
    )))
    stats: dict = {}
    records = list(crawler.crawl(SITE, stats=stats))
    urls = [r.url for r in records]
    assert urls == [SITE, f"{SITE}/about"]
    assert records[1].title == "About"
    fetched_urls = [u for _, u, _ in fake_transport.calls if not u.endswith("robots.txt")]
    assert "https://other.example/x" not in fetched_urls


def test_seen_set_folds_trailing_slash_variants_queues_once(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", robots_allow_all())
    fake_transport.route("GET", f"{SITE}/about", page_resp(html("about", title="About")))
    fake_transport.route("GET", SITE, page_resp(html(
        f'<a href="{SITE}/about">A</a><a href="{SITE}/about/">A slash</a>'
    )))
    stats: dict = {}
    records = list(crawler.crawl(SITE, stats=stats))
    fetched_urls = [r.url for r in records]
    assert fetched_urls.count(f"{SITE}/about") + fetched_urls.count(f"{SITE}/about/") == 1
    assert len(records) == 2
    assert records[1].title == "About"


def test_nofollow_links_land_in_nofollow_links_and_are_not_crawled(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", robots_allow_all())
    fake_transport.route("GET", SITE, page_resp(html(
        f'<a href="{SITE}/sponsored" rel="nofollow">Sponsored</a>'
    )))
    stats: dict = {}
    records = list(crawler.crawl(SITE, stats=stats))
    assert len(records) == 1
    assert records[0].nofollow_links == [f"{SITE}/sponsored"]
    assert records[0].internal_links == []
    fetched_urls = [u for _, u, _ in fake_transport.calls]
    assert f"{SITE}/sponsored" not in fetched_urls


def test_noindex_page_is_still_followed(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", robots_allow_all())
    fake_transport.route("GET", f"{SITE}/child", page_resp(html("child")))
    fake_transport.route("GET", SITE, page_resp(
        f'<html><head><title>T</title><meta name="robots" content="noindex">'
        f'</head><body><a href="{SITE}/child">Child</a></body></html>'
    ))
    stats: dict = {}
    records = list(crawler.crawl(SITE, stats=stats))
    assert [r.url for r in records] == [SITE, f"{SITE}/child"]
    assert records[0].meta_robots == "noindex"


def test_malformed_href_does_not_kill_the_crawl(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", robots_allow_all())
    fake_transport.route("GET", f"{SITE}/ok", page_resp(html("ok page", title="OK")))
    fake_transport.route("GET", SITE, page_resp(html(
        '<a href="http://[junk">bad</a>'
        f'<a href="{SITE}/ok">ok</a>'
    )))
    stats: dict = {}
    records = list(crawler.crawl(SITE, stats=stats))
    assert [r.url for r in records] == [SITE, f"{SITE}/ok"]
    assert records[1].title == "OK"


def test_discovered_from_set_to_referrer(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", robots_allow_all())
    fake_transport.route("GET", f"{SITE}/child", page_resp(html("child")))
    fake_transport.route("GET", SITE, page_resp(html(
        f'<a href="{SITE}/child">Child</a>'
    )))
    records = list(crawler.crawl(SITE))
    assert records[0].discovered_from == ""
    assert records[1].discovered_from == SITE


def test_404_page_yields_record_with_no_links_or_body(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", robots_allow_all())
    fake_transport.route("GET", SITE, {
        "status": 404,
        "body": html(f'<a href="{SITE}/should-not-be-followed">x</a>'),
        "headers": {"Content-Type": "text/html"},
    })
    stats: dict = {}
    records = list(crawler.crawl(SITE, stats=stats))
    assert len(records) == 1
    rec = records[0]
    assert rec.status == 404
    assert rec.internal_links == []
    assert rec.word_count == 0
    assert rec.title == ""


def test_content_length_over_2mb_skips_body_read(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", robots_allow_all())
    fake_transport.route("GET", SITE, {
        "status": 200,
        "body": html("<p>tiny actual body</p>"),
        "headers": {
            "Content-Type": "text/html",
            "Content-Length": str(3 * 1024 * 1024),
        },
    })
    records = list(crawler.crawl(SITE))
    assert len(records) == 1
    assert records[0].word_count == 0
    assert records[0].title == ""


def test_xhtml_content_type_is_extracted(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", robots_allow_all())
    fake_transport.route("GET", SITE, {
        "status": 200,
        "body": html("<p>xhtml body text</p>", title="XHTML Title"),
        "headers": {"Content-Type": "application/xhtml+xml; charset=utf-8"},
    })
    records = list(crawler.crawl(SITE))
    assert records[0].title == "XHTML Title"
    assert records[0].word_count > 0


def test_twitter_meta_tags_land_in_record_twitter(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", robots_allow_all())
    body = (
        '<html><head><title>T</title>'
        '<meta name="twitter:card" content="summary_large_image">'
        '<meta name="twitter:title" content="Twitter Title">'
        '</head><body>text</body></html>'
    )
    fake_transport.route("GET", SITE, page_resp(body))
    records = list(crawler.crawl(SITE))
    assert records[0].twitter == {
        "twitter:card": "summary_large_image",
        "twitter:title": "Twitter Title",
    }


def test_redirect_history_produces_chain_and_final_url(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", robots_allow_all())
    fake_transport.route("GET", SITE, {
        "status": 200,
        "url": f"{SITE}/new",
        "body": html("landed"),
        "headers": {"Content-Type": "text/html"},
        "history": [
            {"status": 301, "url": SITE, "headers": {"Location": f"{SITE}/mid"}},
            {"status": 302, "url": f"{SITE}/mid", "headers": {"Location": f"{SITE}/new"}},
        ],
    })
    records = list(crawler.crawl(SITE))
    rec = records[0]
    assert rec.final_url == f"{SITE}/new"
    assert rec.redirect_chain == [
        {"url": SITE, "status": 301, "location": f"{SITE}/mid"},
        {"url": f"{SITE}/mid", "status": 302, "location": f"{SITE}/new"},
    ]


def test_too_many_redirects_yields_error_record_with_partial_chain(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", robots_allow_all())

    hop1 = requests.Response()
    hop1.status_code = 301
    hop1.url = SITE
    hop1.headers["Location"] = f"{SITE}/loop2"
    hop2 = requests.Response()
    hop2.status_code = 302
    hop2.url = f"{SITE}/loop2"
    hop2.headers["Location"] = SITE
    final = requests.Response()
    final.status_code = 301
    final.url = SITE
    final.history = [hop1, hop2]

    exc = requests.TooManyRedirects("Exceeded redirects", response=final)
    fake_transport.route("GET", SITE, exc)

    records = list(crawler.crawl(SITE))
    assert len(records) == 1
    rec = records[0]
    assert rec.status == -1
    assert rec.error_type == "too_many_redirects"
    assert rec.redirect_chain == [
        {"url": SITE, "status": 301, "location": f"{SITE}/loop2"},
        {"url": f"{SITE}/loop2", "status": 302, "location": SITE},
    ]


def test_stats_truncated_when_max_pages_hit_with_queue_nonempty(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", robots_allow_all())
    fake_transport.route("GET", f"{SITE}/a", page_resp(html("a page")))
    fake_transport.route("GET", SITE, page_resp(html(
        f'<a href="{SITE}/a">a</a><a href="{SITE}/b">b</a>'
    )))
    stats: dict = {}
    records = list(crawler.crawl(SITE, max_pages=2, stats=stats))
    assert len(records) == 2
    assert stats["truncated"] is True


def test_stats_not_truncated_when_crawl_exhausts_queue(fake_transport):
    fake_transport.route("GET", f"{SITE}/robots.txt", robots_allow_all())
    fake_transport.route("GET", SITE, page_resp(html("no links here")))
    stats: dict = {}
    records = list(crawler.crawl(SITE, max_pages=50, stats=stats))
    assert len(records) == 1
    assert stats["truncated"] is False


def test_crawl_to_file_writes_jsonl_and_v2_summary(fake_transport, tmp_path):
    fake_transport.route("GET", f"{SITE}/robots.txt", robots_allow_all())
    fake_transport.route("GET", f"{SITE}/missing", 404)
    fake_transport.route("GET", SITE, page_resp(html(
        f'<a href="{SITE}/missing">missing</a>'
    )))

    out_path = tmp_path / "crawl" / "out.jsonl"
    summary = crawler.crawl_to_file(SITE, out_path)

    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["url"] == SITE
    assert parsed[1]["status"] == 404

    assert summary["pages"] == 2
    assert summary["errors"] == 0
    assert summary["non_200"] == 1
    assert summary["robots_status"] == "ok"
    assert summary["all_blocked"] is False
    assert summary["truncated"] is False
    assert summary["schema_version"] == crawler.SCHEMA_VERSION
