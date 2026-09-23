"""Shared HTTP plumbing: retries with backoff, per-host rate limiting, an
optional on-disk response cache, and — critically — credential sanitization.

All seo-engine scripts route external requests through `request()` so that
rate limits and identification headers are consistent (being a polite crawler
is part of being a sustainable SEO tool) and so that **no API key can leak
into an exception message, log line, or report**. Every Response returned by
this module has its `url` (and `request.url`) rewritten with sensitive query
parameter values redacted, and every exception this module raises has been
passed through the same sanitizer.

Retry policy is idempotency-aware: POSTs to pay-per-call APIs are never
blindly re-sent after an ambiguous failure (a 500 or timeout may mean the
work was already billed). Callers assert safety explicitly via
``retry="idempotent"`` when a POST is a pure query (e.g. CrUX, IndexNow).

Testing seam: `_send()` is the module's single egress point; tests
monkeypatch it to fake the network without touching retry/cache/sanitize
logic.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

USER_AGENT = "seo-engine/1.0 (+https://github.com/seo-engine; site-owner audit tool)"

DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RETRY_AFTER_CAP = 120.0

#: Query-parameter names whose *values* are redacted from every surfaced URL.
SENSITIVE_PARAMS = {
    "key", "apikey", "api_key", "apiKey", "token", "access_token", "secret",
    "client_secret", "password", "signature", "auth",
}

_REDACTED = "REDACTED"

# Matches `key=...` fragments inside free text (exception strings, bodies).
_SENSITIVE_KV_RE = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in SENSITIVE_PARAMS) + r")=([^&\s\"'<>]+)",
    re.IGNORECASE,
)

_session = requests.Session()

_last_request_at: dict[str, float] = {}


class HttpError(RuntimeError):
    """A request failed. `url` is pre-sanitized; safe to log or report.

    `error_type` classifies transport failures so callers can key behavior
    on them (the crawler's redirect-loop detection relies on
    `too_many_redirects`). `response` carries the last response when the
    underlying exception had one (e.g. partial redirect history)."""

    def __init__(self, message: str, *, url: str = "", status: Optional[int] = None,
                 error_type: str = "", response: Optional[requests.Response] = None):
        super().__init__(message)
        self.url = url
        self.status = status
        self.error_type = error_type
        self.response = response


def _classify_exception(exc: requests.RequestException) -> str:
    if isinstance(exc, requests.TooManyRedirects):
        return "too_many_redirects"
    if isinstance(exc, requests.exceptions.SSLError):
        return "ssl"
    if isinstance(exc, requests.Timeout):
        return "timeout"
    if isinstance(exc, requests.ConnectionError):
        return "connection"
    return "other"


def sanitize_url(url: str) -> str:
    """Redact the values of sensitive query parameters in a URL.

    Non-sensitive params are preserved verbatim (order included) so crawl
    records keep full fidelity for ordinary site URLs.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return _SENSITIVE_KV_RE.sub(r"\1=" + _REDACTED, url)
    if not parsed.query:
        return url
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    lowered = {p.lower() for p in SENSITIVE_PARAMS}
    redacted = [
        (k, _REDACTED if k.lower() in lowered else v) for k, v in pairs
    ]
    return urlunparse(parsed._replace(query=urlencode(redacted)))


def sanitize_text(text: str) -> str:
    """Redact `key=value` credential fragments embedded in free text."""
    return _SENSITIVE_KV_RE.sub(r"\1=" + _REDACTED, text or "")


def raise_for_status(resp: requests.Response) -> None:
    """Like Response.raise_for_status(), but the error is sanitized and
    carries a short body excerpt for diagnosis."""
    if resp.status_code < 400:
        return
    safe_url = sanitize_url(resp.url or "")
    body = sanitize_text((resp.text or "")[:300])
    raise HttpError(
        f"HTTP {resp.status_code} for {safe_url}: {body}",
        url=safe_url,
        status=resp.status_code,
    )


def _respect_rate_limit(host: str, min_interval: float) -> None:
    now = time.monotonic()
    last = _last_request_at.get(host, 0.0)
    wait = min_interval - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_request_at[host] = time.monotonic()


def _send(method: str, url: str, **kwargs: Any) -> requests.Response:
    """The module's ONLY network egress point (tests monkeypatch this)."""
    return _session.request(method, url, **kwargs)


def _sanitize_response(resp: requests.Response) -> requests.Response:
    """Rewrite URLs on the response object so even callers that bypass our
    raise_for_status (or log resp.url directly) can't leak a credential."""
    resp.url = sanitize_url(resp.url or "")
    if resp.request is not None and getattr(resp.request, "url", None):
        resp.request.url = sanitize_url(resp.request.url)
    for hist in resp.history or []:
        hist.url = sanitize_url(hist.url or "")
    return resp


def _should_retry(method: str, retry: str, *, status: Optional[int] = None,
                  conn_error: bool = False) -> bool:
    if retry == "none":
        return False
    if retry == "idempotent":
        return conn_error or status in RETRYABLE_STATUS
    # retry == "auto": idempotency-aware default.
    if method in ("GET", "HEAD"):
        return conn_error or status in RETRYABLE_STATUS
    # Non-idempotent verb: only a 429 is provably not-executed (rejected at
    # the gate, not billed). 5xx/timeouts may have executed server-side.
    return status == 429


def _retry_delay(resp: Optional[requests.Response], attempt: int) -> float:
    default = min(2 ** attempt * 2, 30)
    if resp is None:
        return min(2 ** attempt, 15)
    retry_after = resp.headers.get("Retry-After")
    if not retry_after:
        return default
    try:
        return min(float(retry_after), RETRY_AFTER_CAP)
    except ValueError:
        return default


def _cache_read(cache_path: Path, cache_ttl: int, url: str) -> Optional[requests.Response]:
    if not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if time.time() - payload["fetched_at"] >= cache_ttl:
            return None
        resp = requests.Response()
        resp.status_code = payload["status"]
        resp._content = base64.b64decode(payload["body_b64"])
        resp.headers.update(payload["headers"])
        resp.encoding = requests.utils.get_encoding_from_headers(resp.headers)
        resp.url = sanitize_url(url)
        return resp
    except Exception:
        # A corrupt cache entry must never brick an endpoint: drop and miss.
        try:
            cache_path.unlink()
        except OSError:
            pass
        return None


def _cache_write(cache_path: Path, resp: requests.Response) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({
        "fetched_at": time.time(),
        "status": resp.status_code,
        "headers": dict(resp.headers),
        "body_b64": base64.b64encode(resp.content).decode("ascii"),
    })
    tmp = cache_path.with_suffix(f".tmp-{os.getpid()}")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, cache_path)


def prune_cache(cache_dir: Path, max_age_seconds: int) -> int:
    """Delete cache entries older than max_age_seconds. Returns count removed."""
    removed = 0
    if not cache_dir.is_dir():
        return removed
    cutoff = time.time() - max_age_seconds
    for entry in cache_dir.glob("*.json"):
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def request(
    method: str,
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    params: Optional[dict[str, Any]] = None,
    json_body: Optional[Any] = None,
    data: Optional[Any] = None,
    auth: Optional[tuple[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    min_interval: float = 0.5,
    cache_dir: Optional[Path] = None,
    cache_ttl: int = 0,
    retry: str = "auto",
    stream: bool = False,
    check: bool = False,
    allow_redirects: bool = True,
) -> requests.Response:
    """requests wrapper with UA, per-host politeness delay, idempotency-aware
    retry/backoff (honoring a capped Retry-After), credential sanitization,
    and an optional GET disk cache.

    retry: "auto" (GET/HEAD full retry; other verbs 429-only), "idempotent"
    (caller asserts the call is safe to repeat), or "none".
    check: raise `HttpError` (sanitized) on 4xx/5xx before returning.
    """
    if retry not in ("auto", "idempotent", "none"):
        raise ValueError(f"invalid retry mode: {retry!r}")
    method = method.upper()
    merged_headers = {"User-Agent": USER_AGENT}
    if headers:
        merged_headers.update(headers)

    cache_path: Optional[Path] = None
    if cache_dir is not None and cache_ttl > 0 and method == "GET" and not stream:
        key = hashlib.sha256(
            json.dumps([url, params, merged_headers.get("Authorization", "")],
                       sort_keys=True, default=str).encode()
        ).hexdigest()
        cache_path = cache_dir / f"{key}.json"
        cached = _cache_read(cache_path, cache_ttl, url)
        if cached is not None:
            if check:
                raise_for_status(cached)
            return cached

    host = urlparse(url).netloc
    last_error = ""
    last_error_type = ""
    last_response: Optional[requests.Response] = None
    for attempt in range(MAX_RETRIES + 1):
        _respect_rate_limit(host, min_interval)
        try:
            resp = _send(
                method, url,
                headers=merged_headers, params=params, json=json_body,
                data=data, auth=auth, timeout=timeout, stream=stream, allow_redirects=allow_redirects,
            )
        except requests.RequestException as exc:
            last_error = sanitize_text(str(exc))
            last_error_type = _classify_exception(exc)
            last_response = getattr(exc, "response", None)
            if last_response is not None:
                last_response = _sanitize_response(last_response)
            # A redirect loop is deterministic — retrying cannot help.
            retryable = last_error_type != "too_many_redirects"
            if (retryable and attempt < MAX_RETRIES
                    and _should_retry(method, retry, conn_error=True)):
                time.sleep(_retry_delay(None, attempt))
                continue
            break

        if (resp.status_code in RETRYABLE_STATUS and attempt < MAX_RETRIES
                and _should_retry(method, retry, status=resp.status_code)):
            delay = _retry_delay(resp, attempt)
            resp.close()
            time.sleep(delay)
            continue

        resp = _sanitize_response(resp)
        if cache_path is not None and resp.ok:
            _cache_write(cache_path, resp)
        if check:
            raise_for_status(resp)
        return resp

    safe_url = sanitize_url(url)
    raise HttpError(
        f"{method} {safe_url} failed: {last_error}",
        url=safe_url,
        error_type=last_error_type,
        response=last_response,
    ) from None


def get(url: str, **kwargs: Any) -> requests.Response:
    return request("GET", url, **kwargs)


def post(url: str, **kwargs: Any) -> requests.Response:
    return request("POST", url, **kwargs)
