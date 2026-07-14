"""Shared fixtures for the seo-engine foundation-module test suite.

- `fake_transport`: monkeypatches scripts.lib.http_util._send (the module's
  single network egress) with a programmable FakeSender.
- `sleep_calls` (autouse): monkeypatches http_util's time.sleep to
  record-and-noop, so no test ever actually sleeps; the recorded values back
  the backoff assertions. Also resets the per-host rate-limit table.
- `tmp_repo`: a temp directory with a `.seo-engine/` marker plus a helper to
  build `scripts.lib.config.Config` objects pointing at it.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib import config, http_util  # noqa: E402


def _make_response(
    status: int = 200,
    body: bytes | str = b"",
    headers: dict | None = None,
    url: str = "https://fake.test/",
    method: str = "GET",
    history: list | None = None,
) -> requests.Response:
    """Build a real requests.Response the way http_util will meet one."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    resp = requests.Response()
    resp.status_code = status
    resp._content = body
    resp._content_consumed = True  # so resp.close() never touches resp.raw (None)
    if headers:
        resp.headers.update(headers)
    # Mimic HTTPAdapter.build_response: derive encoding from the headers.
    resp.encoding = requests.utils.get_encoding_from_headers(resp.headers)
    resp.url = url
    req = requests.PreparedRequest()
    req.method = method
    req.url = url
    resp.request = req
    for item in history or []:
        resp.history.append(_make_response(**item) if isinstance(item, dict) else item)
    return resp


class FakeSender:
    """Programmable stand-in for http_util._send.

    Responses are queued sequentially via .queue(...) or registered per
    (METHOD, url-prefix) via .route(...). Route responses are consumed in
    order and the last one repeats, so retry loops stay served. Items may be:

      - a dict of _make_response kwargs (url defaults to the requested url)
      - a bare int (status code)
      - a prebuilt requests.Response
      - an Exception instance (raised as-is, e.g. requests.ConnectionError)

    Every call is recorded as (METHOD, url, kwargs) in .calls.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self._queue: list = []
        self._routes: list[dict] = []

    # -- programming --------------------------------------------------------

    def queue(self, *items) -> None:
        self._queue.extend(items)

    def route(self, method: str, prefix: str, *items) -> None:
        self._routes.append(
            {"method": method.upper(), "prefix": prefix, "items": list(items), "i": 0}
        )

    # -- inspection ----------------------------------------------------------

    @property
    def urls(self) -> list[str]:
        return [url for _, url, _ in self.calls]

    # -- the transport -------------------------------------------------------

    def __call__(self, method: str, url: str, **kwargs) -> requests.Response:
        self.calls.append((method.upper(), url, kwargs))
        for route in self._routes:
            if route["method"] == method.upper() and url.startswith(route["prefix"]):
                item = route["items"][min(route["i"], len(route["items"]) - 1)]
                route["i"] += 1
                return self._emit(item, method, url)
        if self._queue:
            return self._emit(self._queue.pop(0), method, url)
        raise AssertionError(f"FakeSender: unexpected request {method} {url}")

    def _emit(self, item, method: str, url: str) -> requests.Response:
        if isinstance(item, Exception):
            raise item
        if isinstance(item, requests.Response):
            return item
        if isinstance(item, int):
            item = {"status": item}
        spec = dict(item)
        spec.setdefault("url", url)
        spec.setdefault("method", method)
        return _make_response(**spec)


@pytest.fixture
def make_response():
    """The response factory, for tests that need a Response sans transport."""
    return _make_response


@pytest.fixture
def fake_transport(monkeypatch):
    sender = FakeSender()
    monkeypatch.setattr(http_util, "_send", sender)
    return sender


@pytest.fixture(autouse=True)
def sleep_calls(monkeypatch):
    """No test ever really sleeps. Recorded values back backoff assertions."""
    calls: list[float] = []
    monkeypatch.setattr(http_util.time, "sleep", lambda seconds: calls.append(seconds))
    # Fresh per-host politeness table so tests don't leak rate-limit state.
    monkeypatch.setattr(http_util, "_last_request_at", {})
    return calls


@pytest.fixture
def tmp_repo(tmp_path):
    root = tmp_path / "repo"
    (root / ".seo-engine").mkdir(parents=True)

    def make_config(env=None, site=None) -> config.Config:
        return config.Config(repo_root=root, env=dict(env or {}), site=dict(site or {}))

    return types.SimpleNamespace(root=root, make_config=make_config)
