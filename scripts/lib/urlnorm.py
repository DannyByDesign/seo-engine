"""Canonical URL identity for diffing, grouping, and graph building.

Four scripts used to each carry a different partial normalizer, so the same
page had 2-4 identities depending on which script looked at it — producing
false "duplicate title" findings for `/about` vs `/about/`, false "critical
cross-domain canonical" findings for www vs apex, and false redirect
"loops" for ordinary slash-normalizing redirects. This module is the single
identity function they all share.

`canonical_key` is an *identity fold*, not a display form: report output
must always print URLs as observed; redirect-hop analysis must compare raw
URLs (a normalizing redirect is, by definition, a raw-vs-folded difference).

Folding rules (deliberate equivalences):
  scheme    http == https
  host      case-insensitive, trailing dot stripped, :80/:443 dropped,
            leading "www." folded
  path      case-preserved, %XX escapes uppercased, one trailing slash
            stripped on non-root paths
  query     tracking params (name-prefix match) dropped, remainder sorted
  fragment  dropped
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING_PARAMS = ("utm_", "fbclid", "gclid", "msclkid", "mc_eid", "igshid")

_PCT_RE = re.compile(r"%[0-9a-fA-F]{2}")


def _fold_host(netloc: str) -> str:
    host = netloc.lower()
    for port in (":80", ":443"):
        if host.endswith(port):
            host = host[: -len(port)]
            break
    host = host.rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def host_key(url: str) -> str:
    """Folded hostname of a URL (or of a bare hostname)."""
    try:
        parsed = urlparse(url if "//" in url else f"//{url}")
    except ValueError:
        return url.strip().lower()
    return _fold_host(parsed.netloc or "")


def canonical_key(url: str) -> str:
    """Identity fold. Never raises — unparseable input folds to itself."""
    if not url:
        return ""
    url = url.strip()
    try:
        parsed = urlparse(url)
    except ValueError:
        return url

    scheme = parsed.scheme.lower()
    if scheme == "http":
        scheme = "https"
    host = _fold_host(parsed.netloc)

    path = _PCT_RE.sub(lambda m: m.group(0).upper(), parsed.path)
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]

    try:
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
    except ValueError:
        pairs = []
    kept = sorted(
        (k, v) for k, v in pairs
        if not any(k.lower().startswith(p) for p in TRACKING_PARAMS)
    )
    query = urlencode(kept)

    return urlunparse((scheme, host, path, parsed.params, query, ""))


def same_page(a: str, b: str) -> bool:
    return canonical_key(a) == canonical_key(b)


def same_site(url: str, site_host: str, *, include_subdomains: bool = False) -> bool:
    """Is `url` on the site identified by `site_host` (a URL or bare host)?"""
    url_host = host_key(url)
    site = host_key(site_host)
    if not url_host or not site:
        return False
    if url_host == site:
        return True
    return include_subdomains and url_host.endswith("." + site)


def is_cross_host_canonical(canonical: str, page_url: str) -> bool:
    """The ONE cross-domain canonical test. www/apex/scheme variants are the
    same host; anything else is genuinely cross-host (security-relevant)."""
    if not canonical:
        return False
    return host_key(canonical) != host_key(page_url)


def build_alias_map(pages: list[dict]) -> dict[str, str]:
    """canonical_key(url) -> canonical_key(final_url) for records that were
    fetched through a redirect. Lets graph/orphan logic credit a link to a
    redirecting alias (/old, www variant) to the destination page."""
    aliases: dict[str, str] = {}
    for rec in pages:
        if rec.get("error") or (rec.get("status") or 0) < 0:
            continue
        url, final = rec.get("url", ""), rec.get("final_url", "")
        if not url or not final:
            continue
        src, dst = canonical_key(url), canonical_key(final)
        if src and dst and src != dst:
            aliases[src] = dst
    return aliases


def resolve_alias(key: str, aliases: dict[str, str], *, max_hops: int = 5) -> str:
    """Follow an alias chain to its terminal key (bounded, cycle-safe)."""
    seen = {key}
    for _ in range(max_hops):
        nxt: Optional[str] = aliases.get(key)
        if nxt is None or nxt in seen:
            return key
        seen.add(nxt)
        key = nxt
    return key
