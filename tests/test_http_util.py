"""Tests for scripts.lib.http_util: sanitization, retry policy, disk cache."""

from __future__ import annotations

import json
import os
import time

import pytest
import requests

from scripts.lib import http_util
from scripts.lib.http_util import HttpError

URL = "https://api.test/v1/data"


@pytest.mark.parametrize("param", sorted(http_util.SENSITIVE_PARAMS))
def test_sanitize_url_redacts_each_sensitive_param(param):
    url = f"https://api.test/p?{param}=hunter2"
    assert http_util.sanitize_url(url) == f"https://api.test/p?{param}=REDACTED"


def test_sanitize_url_preserves_other_params_and_order():
    url = "https://api.test/p?z=26&key=SECRET&a=1&ref=nav"
    assert http_util.sanitize_url(url) == "https://api.test/p?z=26&key=REDACTED&a=1&ref=nav"


def test_sanitize_url_param_name_match_is_case_insensitive():
    assert http_util.sanitize_url("https://api.test/p?KEY=x&ApiKey=y") == (
        "https://api.test/p?KEY=REDACTED&ApiKey=REDACTED"
    )


def test_sanitize_url_without_query_is_untouched():
    assert http_util.sanitize_url("https://api.test/p") == "https://api.test/p"


def test_sanitize_url_unparseable_still_redacts_by_regex():
    out = http_util.sanitize_url("http://[bad?key=SECRET")
    assert "SECRET" not in out
    assert "key=REDACTED" in out


def test_sanitize_text_redacts_kv_fragments_in_free_text():
    text = 'call failed: https://x/?token=abc123 and "password=hunter2" (key=zzz)'
    out = http_util.sanitize_text(text)
    assert "abc123" not in out and "hunter2" not in out and "zzz" not in out
    assert "token=REDACTED" in out and "password=REDACTED" in out and "key=REDACTED" in out
    assert out.startswith("call failed: ")


def test_sanitize_text_handles_none():
    assert http_util.sanitize_text(None) == ""


def test_raise_for_status_noop_below_400(make_response):
    assert http_util.raise_for_status(make_response(status=200)) is None
    assert http_util.raise_for_status(make_response(status=301)) is None


def test_raise_for_status_sanitizes_url_and_body(make_response):
    resp = make_response(
        status=403,
        body="denied key=SECRET",
        url="https://api.test/p?token=TSECRET",
    )
    with pytest.raises(HttpError) as ei:
        http_util.raise_for_status(resp)
    err = ei.value
    assert err.status == 403
    assert err.url == "https://api.test/p?token=REDACTED"
    msg = str(err)
    assert "TSECRET" not in msg and "SECRET" not in msg
    assert "key=REDACTED" in msg
    assert "HTTP 403" in msg


def test_raise_for_status_body_excerpt_capped_at_300_chars(make_response):
    resp = make_response(status=500, body="B" * 400, url="https://api.test/p")
    with pytest.raises(HttpError) as ei:
        http_util.raise_for_status(resp)
    msg = str(ei.value)
    assert "B" * 300 in msg
    assert "B" * 301 not in msg


def test_get_500_retried_then_final_response_returned(fake_transport, sleep_calls):
    fake_transport.queue(500, 500, 500, 500)
    resp = http_util.get(URL, min_interval=0)
    assert resp.status_code == 500
    assert len(fake_transport.calls) == 4
    assert sleep_calls == [2, 4, 8]


def test_post_500_not_retried_in_auto(fake_transport, sleep_calls):
    fake_transport.queue(500)
    resp = http_util.post(URL, min_interval=0)
    assert resp.status_code == 500
    assert len(fake_transport.calls) == 1
    assert sleep_calls == []


def test_post_429_retried_in_auto(fake_transport):
    fake_transport.queue(429, 200)
    resp = http_util.post(URL, min_interval=0)
    assert resp.status_code == 200
    assert len(fake_transport.calls) == 2


def test_post_500_retried_when_caller_asserts_idempotent(fake_transport):
    fake_transport.queue(500, 200)
    resp = http_util.post(URL, min_interval=0, retry="idempotent")
    assert resp.status_code == 200
    assert len(fake_transport.calls) == 2


def test_retry_none_never_retries_status(fake_transport, sleep_calls):
    fake_transport.queue(500)
    resp = http_util.get(URL, min_interval=0, retry="none")
    assert resp.status_code == 500
    assert len(fake_transport.calls) == 1
    assert sleep_calls == []


def test_retry_none_never_retries_connection_error(fake_transport):
    fake_transport.queue(requests.ConnectionError("boom"))
    with pytest.raises(HttpError):
        http_util.get(URL, min_interval=0, retry="none")
    assert len(fake_transport.calls) == 1


def test_get_connection_error_retried_then_sanitized_httperror(fake_transport, sleep_calls):
    fake_transport.route(
        "GET", "https://api.test/",
        requests.ConnectionError("conn reset for key=SECRET"),
    )
    with pytest.raises(HttpError) as ei:
        http_util.get(URL + "?token=TVALUE", min_interval=0)
    assert len(fake_transport.calls) == 4
    assert sleep_calls == [1, 2, 4]
    err = ei.value
    assert err.__cause__ is None
    msg = str(err)
    assert "SECRET" not in msg and "TVALUE" not in msg
    assert "key=REDACTED" in msg and "token=REDACTED" in msg
    assert err.url == URL + "?token=REDACTED"


def test_post_connection_error_not_retried_in_auto(fake_transport, sleep_calls):
    fake_transport.queue(requests.ConnectionError("boom"))
    with pytest.raises(HttpError):
        http_util.post(URL, min_interval=0)
    assert len(fake_transport.calls) == 1
    assert sleep_calls == []


@pytest.mark.parametrize("retry_after,expected_delay", [("7", 7.0), ("300", 120.0)])
def test_retry_after_honored_but_capped_at_120(fake_transport, sleep_calls,
                                               retry_after, expected_delay):
    fake_transport.queue({"status": 429, "headers": {"Retry-After": retry_after}}, 200)
    resp = http_util.get(URL, min_interval=0)
    assert resp.status_code == 200
    assert sleep_calls == [expected_delay]


def test_retry_after_unparseable_falls_back_to_capped_exponential(fake_transport, sleep_calls):
    fake_transport.queue({"status": 503, "headers": {"Retry-After": "tomorrow"}}, 200)
    resp = http_util.get(URL, min_interval=0)
    assert resp.status_code == 200
    assert sleep_calls == [2]


def test_returned_response_urls_sanitized(fake_transport):
    url = URL + "?key=SECRET&foo=1"
    fake_transport.queue({
        "status": 200,
        "url": url,
        "history": [{"status": 301, "url": "https://api.test/old?token=T2"}],
    })
    resp = http_util.get(url, min_interval=0)
    assert resp.url == URL + "?key=REDACTED&foo=1"
    assert resp.request.url == URL + "?key=REDACTED&foo=1"
    assert resp.history[0].url == "https://api.test/old?token=REDACTED"


def test_check_true_raises_on_4xx(fake_transport):
    fake_transport.queue({"status": 404, "body": "nope"})
    with pytest.raises(HttpError) as ei:
        http_util.get(URL, min_interval=0, check=True)
    assert ei.value.status == 404
    assert len(fake_transport.calls) == 1


def test_invalid_retry_mode_raises_value_error(fake_transport):
    with pytest.raises(ValueError):
        http_util.get(URL, retry="sometimes")
    assert fake_transport.calls == []


def test_cache_writes_atomically_and_serves_within_ttl(fake_transport, tmp_path):
    cdir = tmp_path / "cache"
    fake_transport.queue({"status": 200, "body": b"payload", "headers": {"X-Custom": "1"}})
    r1 = http_util.get(URL, cache_dir=cdir, cache_ttl=600, min_interval=0)
    assert r1.content == b"payload"
    assert len(list(cdir.glob("*.json"))) == 1
    assert list(cdir.glob("*.tmp-*")) == []

    r2 = http_util.get(URL, cache_dir=cdir, cache_ttl=600, min_interval=0)
    assert len(fake_transport.calls) == 1
    assert r2.status_code == 200
    assert r2.content == b"payload"
    assert r2.headers["X-Custom"] == "1"


def test_cache_expired_ttl_refetches(fake_transport, tmp_path):
    cdir = tmp_path / "cache"
    fake_transport.queue({"body": b"old"}, {"body": b"new"})
    http_util.get(URL, cache_dir=cdir, cache_ttl=600, min_interval=0)

    entry = next(cdir.glob("*.json"))
    payload = json.loads(entry.read_text())
    payload["fetched_at"] -= 601
    entry.write_text(json.dumps(payload))

    resp = http_util.get(URL, cache_dir=cdir, cache_ttl=600, min_interval=0)
    assert resp.content == b"new"
    assert len(fake_transport.calls) == 2


def test_corrupt_cache_entry_is_deleted_and_treated_as_miss(fake_transport, tmp_path):
    cdir = tmp_path / "cache"
    fake_transport.queue({"body": b"first"}, {"body": b"second"})
    http_util.get(URL, cache_dir=cdir, cache_ttl=600, min_interval=0)

    entry = next(cdir.glob("*.json"))
    entry.write_bytes(b"\x00 this is not json {")

    resp = http_util.get(URL, cache_dir=cdir, cache_ttl=600, min_interval=0)
    assert resp.content == b"second"
    assert len(fake_transport.calls) == 2
    json.loads(entry.read_text())


def test_cache_round_trips_body_bytes_exactly(fake_transport, tmp_path):
    cdir = tmp_path / "cache"
    body = "café".encode("iso-8859-1")
    fake_transport.queue({
        "body": body,
        "headers": {"Content-Type": "text/html; charset=ISO-8859-1"},
    })
    r1 = http_util.get(URL, cache_dir=cdir, cache_ttl=600, min_interval=0)
    assert r1.text == "café"

    r2 = http_util.get(URL, cache_dir=cdir, cache_ttl=600, min_interval=0)
    assert len(fake_transport.calls) == 1
    assert r2.content == body
    assert r2.headers["Content-Type"] == "text/html; charset=ISO-8859-1"


def test_cache_replay_decodes_declared_charset(fake_transport, tmp_path):
    cdir = tmp_path / "cache"
    fake_transport.queue({
        "body": "café".encode("iso-8859-1"),
        "headers": {"Content-Type": "text/html; charset=ISO-8859-1"},
    })
    http_util.get(URL, cache_dir=cdir, cache_ttl=600, min_interval=0)
    replayed = http_util.get(URL, cache_dir=cdir, cache_ttl=600, min_interval=0)
    assert replayed.text == "café"


def test_stream_bypasses_cache(fake_transport, tmp_path):
    cdir = tmp_path / "cache"
    fake_transport.queue({"body": b"a"}, {"body": b"b"})
    http_util.get(URL, cache_dir=cdir, cache_ttl=600, stream=True, min_interval=0)
    http_util.get(URL, cache_dir=cdir, cache_ttl=600, stream=True, min_interval=0)
    assert len(fake_transport.calls) == 2
    assert not cdir.exists()


def test_prune_cache_removes_only_stale_entries(tmp_path):
    cdir = tmp_path / "cache"
    cdir.mkdir()
    fresh = cdir / "fresh.json"
    stale = cdir / "stale.json"
    fresh.write_text("{}")
    stale.write_text("{}")
    old = time.time() - 7200
    os.utime(stale, (old, old))

    assert http_util.prune_cache(cdir, 3600) == 1
    assert fresh.exists()
    assert not stale.exists()


def test_prune_cache_missing_dir_is_zero(tmp_path):
    assert http_util.prune_cache(tmp_path / "nope", 3600) == 0
