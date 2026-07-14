"""Semrush API client. Optional — degrades to "not configured" if unset.

Requires a Business-plan (SEO Toolkit) subscription plus a separately
purchased API-unit balance. Core reports use ?key= query auth (the key value
is scrubbed from any surfaced error by http_util's sanitizer).

Two failure modes this client makes loud instead of silent:
* HTTP-level errors raise via http_util (sanitized).
* Semrush also returns HTTP 200 with a body like ``ERROR 50 :: NOTHING
  FOUND`` — raised here as SemrushApiError instead of flowing into reports
  as garbage CSV.

The deprecated backlinks report family is deliberately NOT implemented:
Semrush marked it deprecated, and Ahrefs/DataForSEO cover backlinks in this
system. Domain reports only.
"""

from __future__ import annotations

from typing import Any

from . import http_util
from .config import Config

BASE_URL = "https://api.semrush.com/"
_HINT = "Requires a Semrush Business plan plus a purchased API-unit balance (developer.semrush.com)."


class SemrushApiError(RuntimeError):
    """Semrush returned an application-level ERROR body (HTTP 200)."""


def _report(cfg: Config, report_type: str, params: dict[str, Any]) -> str:
    """Core reports return CSV (semicolon-delimited), not JSON."""
    key = cfg.require("SEMRUSH_API_KEY", _HINT)
    query = {"key": key, "type": report_type, **params}
    resp = http_util.get(BASE_URL, params=query, min_interval=0.5, check=True)
    text = resp.text or ""
    if text.lstrip().startswith("ERROR"):
        raise SemrushApiError(
            f"Semrush report {report_type!r} failed: {text.strip().splitlines()[0][:200]}"
        )
    return text


def domain_overview(cfg: Config, domain: str, database: str = "us") -> str:
    return _report(cfg, "domain_ranks", {
        "domain": domain, "database": database,
        "export_columns": "Db,Dn,Rk,Or,Ot,Oc,Ad,At,Ac,Sh,Sv",
    })


def domain_organic_keywords(cfg: Config, domain: str, database: str = "us", limit: int = 100) -> str:
    return _report(cfg, "domain_organic", {
        "domain": domain, "database": database, "display_limit": limit,
        "export_columns": "Ph,Po,Pp,Nq,Cp,Ur,Tr",
    })
