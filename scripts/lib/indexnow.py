"""IndexNow client — Bing, Yandex, Naver, Seznam.cz, Yep, Amazon (NOT Google
or Baidu). Submitting a URL does not guarantee indexing — it only signals a
change and may earn a prioritized crawl visit, and submitted URLs count
toward the site's normal crawl quota. Use for genuinely changed URLs, not
blanket resubmission.

GEO note (see skills/seo-references/geo-playbook.md §10): Bing's index is
what ChatGPT search retrieves against, so getting changed URLs into Bing
promptly is an AI-visibility action, not just classic-SEO housekeeping.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Optional

from . import http_util, urlnorm
from .config import Config

ENDPOINT = "https://api.indexnow.org/IndexNow"
_HINT = "Generate one with generate_key(), host it at the site root, then set INDEXNOW_API_KEY."


def generate_key() -> str:
    """A fresh 32-character hex key suitable for the verification file."""
    return secrets.token_hex(16)


def write_key_file(public_dir: Path, key: str) -> Path:
    """Writes {key}.txt into the site's static-source dir — the file-host
    verification IndexNow requires. Caller decides the right dir for the
    detected framework via detect_stack's `static_source_dir` (NEVER the
    build output dir, which is wiped on every build)."""
    path = public_dir / f"{key}.txt"
    path.write_text(key, encoding="utf-8")
    return path


def submit(cfg: Config, urls: list[str], key_location: Optional[str] = None) -> int:
    """Batch-submits up to 10,000 URLs (all must share the configured site's
    host — IndexNow rejects mixed-host lists, and a silent mismatch would
    submit under the wrong host verification).

    Returns the HTTP status (200/202 = accepted; no per-URL confirmation).
    Raises http_util.HttpError on 4xx (bad key/host/format) instead of
    handing callers an error code that looks like data.
    """
    key = cfg.require("INDEXNOW_API_KEY", _HINT)
    if not urls:
        return 200

    site_host = urlnorm.host_key(cfg.site_url)
    bad = [u for u in urls if urlnorm.host_key(u) != site_host]
    if bad:
        raise ValueError(
            f"IndexNow submission rejected: {len(bad)} URL(s) are not on the "
            f"configured site host {site_host!r} (first: {bad[0]!r}). Submit "
            "only URLs belonging to the verified site."
        )

    host = urlnorm.host_key(urls[0])
    body = {"host": host, "key": key, "urlList": urls[:10000]}
    if key_location:
        body["keyLocation"] = key_location

    # A pure signal with no server-side state to double-charge: safe to retry.
    resp = http_util.post(ENDPOINT, json_body=body, min_interval=0.5,
                          retry="idempotent", check=True)
    return resp.status_code
