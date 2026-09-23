"""Google Search Console API client.

Auth: OAuth2 via a service account added as a verified Owner/User on the
property (see skills/seo-references/api-reference.md). No API-key auth
exists for this API — the service-account-as-delegated-user pattern is what
makes unattended automation possible.

Property identifiers are NOT the site URL:
* URL-prefix properties are identified WITH a trailing slash
  (``https://example.com/`` — the slash-stripped form 403s), and
* domain properties are ``sc-domain:example.com`` — the most common modern
  setup, and never guessable from a URL string alone.

`resolve_property()` therefore discovers the right identifier from
`sites.list()` (the properties this service account can actually see),
persists it in .seo-engine/config.yml, and every API helper here resolves
through it — re-resolving once automatically if a cached identifier starts
403ing (property re-verified/migrated). This is the difference between the
"free GSC backbone" working and silently failing for every user.

Dates: GSC data is bucketed in America/Los_Angeles days — window math must
use `gsc_today()`, not the machine-local date.

Requires: google-api-python-client, google-auth (see requirements.txt).
Env: GOOGLE_APPLICATION_CREDENTIALS (path to service-account JSON) or
     GSC_SERVICE_ACCOUNT_JSON (inline JSON string).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from . import urlnorm
from .config import Config, MissingConfigError, save_site_config

SCOPES = ["https://www.googleapis.com/auth/webmasters"]
MAX_ROWS_PER_REQUEST = 25_000

_HINT = (
    "Create a Google Cloud service account, download its JSON key, then add "
    "the service account's client_email as a verified Owner/User on the "
    "property in Search Console (Settings > Users and permissions)."
)


class GscPropertyError(RuntimeError):
    """The configured site couldn't be matched to a visible GSC property."""


def gsc_today() -> date:
    """Today in GSC's reporting timezone (America/Los_Angeles). Using the
    machine-local date shifts window boundaries by up to a day."""
    return datetime.now(ZoneInfo("America/Los_Angeles")).date()


def _credentials(cfg: Config):
    try:
        from google.oauth2 import service_account
    except ImportError as exc:
        raise RuntimeError(
            "google-auth is required for GSC access — "
            "python3 -m pip install -r requirements.txt"
        ) from exc

    if cfg.has("GOOGLE_APPLICATION_CREDENTIALS"):
        path = cfg.require("GOOGLE_APPLICATION_CREDENTIALS", _HINT)
        if not Path(path).is_file():
            raise MissingConfigError(
                "GOOGLE_APPLICATION_CREDENTIALS",
                f"Points at {path!r}, which does not exist. Fix the path. {_HINT}",
            )
        return service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
    if cfg.has("GSC_SERVICE_ACCOUNT_JSON"):
        raw = cfg.require("GSC_SERVICE_ACCOUNT_JSON", _HINT)
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MissingConfigError(
                "GSC_SERVICE_ACCOUNT_JSON",
                f"Is set but is not valid JSON ({exc}). Paste the service-account "
                f"key file's full JSON content. {_HINT}",
            ) from None
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    raise MissingConfigError("GOOGLE_APPLICATION_CREDENTIALS", _HINT)


def _service(cfg: Config):
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "google-api-python-client is required for GSC access — "
            "python3 -m pip install -r requirements.txt"
        ) from exc
    return build("searchconsole", "v1", credentials=_credentials(cfg), cache_discovery=False)


def list_sites(cfg: Config) -> list[dict[str, Any]]:
    """Properties visible to the service account: [{siteUrl, permissionLevel}]."""
    service = _service(cfg)
    return (service.sites().list().execute() or {}).get("siteEntry", [])


def _match_property(site_url: str, entries: list[dict[str, Any]]) -> tuple[Optional[str], list[str]]:
    """Pure matching logic (unit-testable): pick the best property identifier
    for a configured site URL from sites.list() entries.

    Preference: exact URL-prefix (as configured, trailing slash enforced)
    > sc-domain (most-specific label first) > URL-prefix scheme/www variant.
    Unverified entries are excluded — they 403 on every data call.
    """
    verified = [
        e["siteUrl"] for e in entries
        if e.get("siteUrl") and e.get("permissionLevel") != "siteUnverifiedUser"
    ]
    available = set(verified)

    exact_prefix = site_url.rstrip("/") + "/"
    folded_host = urlnorm.host_key(site_url)
    raw_host = site_url.split("//", 1)[-1].split("/", 1)[0].lower()

    labels = raw_host.removeprefix("www.").split(".") if raw_host else []
    sc_candidates = [
        "sc-domain:" + ".".join(labels[i:]) for i in range(max(len(labels) - 1, 0))
    ]

    variant_prefixes: list[str] = []
    for scheme in ("https", "http"):
        for host in (raw_host, folded_host, f"www.{folded_host}"):
            candidate = f"{scheme}://{host}/"
            if candidate != exact_prefix and candidate not in variant_prefixes:
                variant_prefixes.append(candidate)

    ordered = [exact_prefix, *sc_candidates, *variant_prefixes]
    matches = [c for c in ordered if c in available]
    return (matches[0] if matches else None), matches


def resolve_property(cfg: Config, site_url: Optional[str] = None, *, force: bool = False) -> str:
    """The GSC property identifier for the configured site — cached in
    .seo-engine/config.yml, discovered from sites.list() when absent/forced.

    Raises GscPropertyError with the full visible-property list when nothing
    matches, so remediation is one read away instead of a mystery 403.
    """
    site_url = site_url or cfg.site_url
    if not force:
        cached = str(cfg.site.get("gsc_property") or "").strip()
        if cached:
            return cached

    entries = list_sites(cfg)
    best, matches = _match_property(site_url, entries)
    if best is None:
        visible = [e.get("siteUrl", "?") for e in entries] or ["<none>"]
        raise GscPropertyError(
            f"No GSC property matches {site_url!r}. Properties visible to this "
            f"service account: {', '.join(visible)}. "
            + ("The service account isn't added to ANY property — add its "
               "client_email as a verified Owner/User on the property "
               "(Search Console > Settings > Users and permissions)."
               if not entries else
               "Add the service account to the right property, or fix site_url "
               "in .seo-engine/config.yml.")
        )
    try:
        save_site_config(cfg, {"gsc_property": best, "gsc_property_candidates": matches})
    except Exception:
        pass
    return best


def _is_permission_error(exc: Exception) -> bool:
    status = getattr(getattr(exc, "resp", None), "status", None) or getattr(exc, "status_code", None)
    return status == 403


def _call(cfg: Config, property_id: Optional[str], fn: Callable[[str], Any]) -> Any:
    """Run an API call against a resolved property, re-resolving once if a
    cached identifier has gone stale (403). Explicitly-passed property ids
    are the caller's responsibility and are never second-guessed."""
    explicit = property_id is not None
    prop = property_id or resolve_property(cfg)
    try:
        return fn(prop)
    except Exception as exc:
        if explicit or not _is_permission_error(exc):
            raise
        refreshed = resolve_property(cfg, force=True)
        if refreshed == prop:
            raise
        return fn(refreshed)


def search_analytics_query(
    cfg: Config,
    start_date: str,
    end_date: str,
    *,
    dimensions: Optional[list[str]] = None,
    row_limit: int = 1000,
    start_row: int = 0,
    search_type: str = "web",
    property_id: Optional[str] = None,
) -> dict[str, Any]:
    """One page of clicks/impressions/CTR/position, grouped by the given
    dimensions (any of: query, page, date, device, country)."""
    service = _service(cfg)
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": dimensions or ["query"],
        "rowLimit": min(row_limit, MAX_ROWS_PER_REQUEST),
        "startRow": start_row,
        "type": search_type,
    }
    return _call(cfg, property_id, lambda prop:
                 service.searchanalytics().query(siteUrl=prop, body=body).execute())


def search_analytics_query_all(
    cfg: Config,
    start_date: str,
    end_date: str,
    *,
    dimensions: Optional[list[str]] = None,
    max_rows: int = 100_000,
    search_type: str = "web",
    property_id: Optional[str] = None,
) -> tuple[list[dict[str, Any]], bool]:
    """ALL rows via startRow pagination, up to max_rows.

    Returns (rows, hit_cap). hit_cap=True means the result was truncated at
    max_rows — consumers doing window-vs-window diffs must then compare only
    the intersection (absence from a truncated window is NOT zero traffic).
    """
    rows: list[dict[str, Any]] = []
    start_row = 0
    while start_row < max_rows:
        page_size = min(MAX_ROWS_PER_REQUEST, max_rows - start_row)
        result = search_analytics_query(
            cfg, start_date, end_date, dimensions=dimensions,
            row_limit=page_size, start_row=start_row,
            search_type=search_type, property_id=property_id,
        )
        page = result.get("rows", [])
        rows.extend(page)
        if len(page) < page_size:
            return rows, False
        start_row += len(page)
    return rows, True


def inspect_url(cfg: Config, inspection_url: str, *,
                property_id: Optional[str] = None) -> dict[str, Any]:
    """Index status, selected canonical, mobile usability, and rich-results
    verdict for a single URL. Quota: 600/min and 2,000/day per property —
    loop over a bounded sample, never a whole sitemap."""
    service = _service(cfg)
    return _call(cfg, property_id, lambda prop:
                 service.urlInspection().index().inspect(
                     body={"inspectionUrl": inspection_url, "siteUrl": prop}).execute())


def list_sitemaps(cfg: Config, *, property_id: Optional[str] = None) -> dict[str, Any]:
    service = _service(cfg)
    return _call(cfg, property_id, lambda prop:
                 service.sitemaps().list(siteUrl=prop).execute())


def submit_sitemap(cfg: Config, feedpath: str, *, property_id: Optional[str] = None) -> None:
    service = _service(cfg)
    _call(cfg, property_id, lambda prop:
          service.sitemaps().submit(siteUrl=prop, feedpath=feedpath).execute())


def get_sitemap(cfg: Config, feedpath: str, *, property_id: Optional[str] = None) -> dict[str, Any]:
    service = _service(cfg)
    return _call(cfg, property_id, lambda prop:
                 service.sitemaps().get(siteUrl=prop, feedpath=feedpath).execute())
