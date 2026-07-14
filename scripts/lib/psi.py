"""PageSpeed Insights v5 + Chrome UX Report (CrUX) API client.

Both share one API key (GOOGLE_PSI_API_KEY), sent as an `X-Goog-Api-Key`
header — never a query parameter, so it cannot appear in any surfaced URL.
PSI gives lab (Lighthouse) + field (CrUX) data for a single URL; the CrUX
APIs give dedicated, historical real-user data at URL or origin granularity.

PSI runs a live Lighthouse pass server-side (routinely 10-60s) — its
timeout is set accordingly. CrUX queries are pure lookups and safe to
retry (`retry="idempotent"`).
"""

from __future__ import annotations

from typing import Any, Optional

from . import http_util
from .config import Config

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
CRUX_RECORD_ENDPOINT = "https://chromeuxreport.googleapis.com/v1/records:queryRecord"
CRUX_HISTORY_ENDPOINT = "https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord"

_HINT = "Get a key at https://developers.google.com/speed/docs/insights/v5/get-started (same key works for CrUX)."


def _key_header(cfg: Config) -> dict[str, str]:
    if cfg.has("GOOGLE_PSI_API_KEY"):
        return {"X-Goog-Api-Key": cfg.get("GOOGLE_PSI_API_KEY")}
    return {}


def run_pagespeed(
    cfg: Config,
    url: str,
    strategy: str = "mobile",
    categories: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Full PSI report: Lighthouse lab scores + CrUX field data
    (loadingExperience). Works keyless at a tighter shared quota — the key
    header is only added when configured."""
    params: dict[str, Any] = {
        "url": url, "strategy": strategy,
        "category": categories or ["performance"],
    }
    resp = http_util.get(
        PSI_ENDPOINT, params=params, headers=_key_header(cfg),
        timeout=120.0,
        cache_dir=cfg.state_dir / "http-cache", cache_ttl=3600,
        check=True,
    )
    return resp.json()


def core_web_vitals(psi_report: dict[str, Any]) -> dict[str, Optional[float]]:
    """Extract LCP/INP/CLS field-data values (ms, ms, unitless) from a PSI response."""
    experience = psi_report.get("loadingExperience", {}).get("metrics", {})

    def _metric(key: str) -> Optional[float]:
        entry = experience.get(key)
        return entry.get("percentile") if entry else None

    return {
        "lcp_ms": _metric("LARGEST_CONTENTFUL_PAINT_MS"),
        "inp_ms": _metric("INTERACTION_TO_NEXT_PAINT"),
        "cls": (_metric("CUMULATIVE_LAYOUT_SHIFT_SCORE") or 0) / 100
        if _metric("CUMULATIVE_LAYOUT_SHIFT_SCORE") is not None else None,
        "overall_category": psi_report.get("loadingExperience", {}).get("overall_category"),
    }


def crux_record(
    cfg: Config,
    origin: Optional[str] = None,
    url: Optional[str] = None,
    form_factor: Optional[str] = None,
) -> dict[str, Any]:
    """Current 28-day CrUX record for an origin or a specific URL."""
    cfg.require("GOOGLE_PSI_API_KEY", _HINT)
    body: dict[str, Any] = {}
    if url:
        body["url"] = url
    elif origin:
        body["origin"] = origin
    else:
        raise ValueError("Provide either origin= or url=")
    if form_factor:
        body["formFactor"] = form_factor

    resp = http_util.post(
        CRUX_RECORD_ENDPOINT, headers=_key_header(cfg), json_body=body,
        timeout=60.0, retry="idempotent", check=True,
    )
    return resp.json()


def crux_history(
    cfg: Config,
    origin: Optional[str] = None,
    url: Optional[str] = None,
    collection_period_count: int = 4,
) -> dict[str, Any]:
    """Historical CrUX trend (weekly-refreshed 28-day windows)."""
    cfg.require("GOOGLE_PSI_API_KEY", _HINT)
    body: dict[str, Any] = {"collectionPeriodCount": collection_period_count}
    if url:
        body["url"] = url
    elif origin:
        body["origin"] = origin
    else:
        raise ValueError("Provide either origin= or url=")

    resp = http_util.post(
        CRUX_HISTORY_ENDPOINT, headers=_key_header(cfg), json_body=body,
        timeout=60.0, retry="idempotent", check=True,
    )
    return resp.json()
