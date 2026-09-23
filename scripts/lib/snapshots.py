"""The crawl-snapshot store: one shared, provenance-tagged home for crawls.

Layout (under the target repo):
    .seo-engine/state/crawls/crawl-<UTC yyyymmddTHHMMSSZ>.jsonl   # immutable pages
    .seo-engine/state/crawls/crawl-<...>.meta.json                # provenance sidecar

The sidecar records who produced a crawl and under what parameters
(producer skill, max_pages, pages_crawled, truncated, robots_status,
schema_version). That provenance is what makes cross-skill reuse safe:
`find_baseline` refuses to diff snapshots that aren't comparable (different
site, different max_pages, or truncated coverage) instead of poisoning a
regression report with coverage artifacts — a refusal is machine-readable
and belongs in the caller's `not_checked` section, never silently ignored.

Skills MUST use this module for every crawl read/write. Ad-hoc snapshot
filenames (`crawl-snapshot.jsonl` et al.) are how one skill's 2000-page
crawl became another skill's 500-page "1500 pages disappeared" baseline.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from .config import Config

SCHEMA_VERSION = 2
CRAWL_PREFIX = "crawl-"


FRAGMENT_SWEEP_AFTER_HOURS = 6


@dataclass
class Snapshot:
    path: Path
    meta: dict[str, Any]

    @property
    def finished_at(self) -> datetime:
        raw = self.meta.get("finished_at", "")
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return datetime.fromtimestamp(self.path.stat().st_mtime, tz=timezone.utc)

    @property
    def truncated(self) -> bool:
        return bool(self.meta.get("truncated"))

    @property
    def pages_crawled(self) -> int:
        return int(self.meta.get("pages_crawled") or 0)

    def pages(self) -> Iterator[dict[str, Any]]:
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)


@dataclass
class BaselineResult:
    snapshot: Optional[Snapshot]
    refusal_reason: Optional[str] = None


def crawl_dir(cfg: Config) -> Path:
    d = cfg.state_dir / "crawls"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_snapshot(jsonl_path: Path) -> Optional[Snapshot]:
    meta_path = jsonl_path.with_name(jsonl_path.stem + ".meta.json")
    if not jsonl_path.is_file():
        return None
    if not meta_path.is_file():
        return None
    meta: dict[str, Any] = {}
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        meta = {}
    return Snapshot(path=jsonl_path, meta=meta)


def all_snapshots(cfg: Config, *, site_url: Optional[str] = None) -> list[Snapshot]:
    """All stored snapshots, newest first (optionally filtered to a site)."""
    snaps = []
    for jsonl_path in crawl_dir(cfg).glob(f"{CRAWL_PREFIX}*.jsonl"):
        snap = _load_snapshot(jsonl_path)
        if snap is None:
            continue
        if site_url and snap.meta.get("site_url") not in (None, site_url):
            continue
        snaps.append(snap)
    snaps.sort(key=lambda s: s.finished_at, reverse=True)
    return snaps


def new_crawl(
    cfg: Config,
    producer: str,
    *,
    max_pages: int,
    delay: Optional[float] = None,
    ignore_robots: bool = False,
    start_url: Optional[str] = None,
    include_subdomains: bool = False,
) -> Snapshot:
    """Run a fresh crawl into the store and return its Snapshot."""
    from . import crawler

    site_url = cfg.site_url
    start = start_url or site_url
    started_at = datetime.now(timezone.utc)
    stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    jsonl_path = crawl_dir(cfg) / f"{CRAWL_PREFIX}{stamp}.jsonl"

    kwargs: dict[str, Any] = {
        "max_pages": max_pages,
        "ignore_robots": ignore_robots,
        "include_subdomains": include_subdomains,
    }
    if delay is not None:
        kwargs["delay"] = delay
    summary = crawler.crawl_to_file(start, jsonl_path, **kwargs)

    pages_crawled = int(summary.get("pages") or 0)
    meta = {
        "schema_version": SCHEMA_VERSION,
        "site_url": site_url,
        "start_url": start,
        "producer_skill": producer,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "max_pages": max_pages,
        "pages_crawled": pages_crawled,
        "truncated": bool(summary.get("truncated", pages_crawled >= max_pages)),
        "include_subdomains": include_subdomains,
        "ignore_robots": ignore_robots,
        "crawl_summary": summary,
    }
    meta_path = jsonl_path.with_name(jsonl_path.stem + ".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return Snapshot(path=jsonl_path, meta=meta)


def latest(
    cfg: Config,
    *,
    max_age_hours: float = 24,
    min_pages: Optional[int] = None,
) -> Optional[Snapshot]:
    """The newest reusable snapshot for the configured site, or None if the
    newest one is too old/small (caller then crawls fresh via new_crawl)."""
    site_url = cfg.site_url
    for snap in all_snapshots(cfg, site_url=site_url):
        age = datetime.now(timezone.utc) - snap.finished_at
        if age > timedelta(hours=max_age_hours):
            return None
        if min_pages is not None and snap.pages_crawled < min_pages:
            continue
        return snap
    return None


def find_baseline(
    cfg: Config,
    current: Snapshot,
    *,
    require_comparable: bool = True,
    min_age_days: int = 0,
) -> BaselineResult:
    """The most recent prior snapshot it is *honest* to diff `current`
    against. Refusals are explicit so callers put them in `not_checked`."""
    site_url = current.meta.get("site_url") or cfg.site_url
    cutoff = datetime.now(timezone.utc) - timedelta(days=min_age_days)
    candidates = [
        s for s in all_snapshots(cfg, site_url=site_url)
        if s.path != current.path and s.finished_at < current.finished_at
        and (min_age_days == 0 or s.finished_at <= cutoff)
    ]
    if not candidates:
        return BaselineResult(None, refusal_reason=(
            "no prior snapshot"
            + (f" at least {min_age_days} days old" if min_age_days else "")
            + " exists for this site — nothing to diff against yet"
        ))
    if not require_comparable:
        return BaselineResult(candidates[0])

    for snap in candidates:
        if snap.truncated or current.truncated:
            continue
        if snap.meta.get("max_pages") != current.meta.get("max_pages"):
            continue
        return BaselineResult(snap)

    if current.truncated:
        reason = ("current crawl hit its max_pages cap — diff-based checks are "
                  "indistinguishable from truncation artifacts; raise --max-pages")
    else:
        reason = ("no prior snapshot is comparable (same max_pages, not truncated) — "
                  "diffing incomparable crawls reports coverage changes as regressions")
    return BaselineResult(None, refusal_reason=reason)


def prune(
    cfg: Config,
    *,
    keep_crawls: int = 10,
    keep_days: int = 90,
    keep_reports: int = 30,
    report_days: int = 180,
) -> dict[str, int]:
    """Retention: keep at most `keep_crawls` snapshots and nothing older than
    `keep_days`; per report family, keep `keep_reports` newest and nothing
    older than `report_days`. Called by every skill main — state must not
    grow without bound."""
    import re

    removed = {"crawls": 0, "reports": 0}

    frag_cutoff = time.time() - FRAGMENT_SWEEP_AFTER_HOURS * 3600
    for jsonl_path in crawl_dir(cfg).glob(f"{CRAWL_PREFIX}*.jsonl"):
        meta_path = jsonl_path.with_name(jsonl_path.stem + ".meta.json")
        try:
            if not meta_path.is_file() and jsonl_path.stat().st_mtime < frag_cutoff:
                jsonl_path.unlink()
                removed["crawls"] += 1
        except OSError:
            pass

    snaps = all_snapshots(cfg)
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    for i, snap in enumerate(snaps):
        if i >= keep_crawls or snap.finished_at < cutoff:
            for path in (snap.path, snap.path.with_name(snap.path.stem + ".meta.json")):
                try:
                    path.unlink()
                    removed["crawls"] += 1
                except OSError:
                    pass

    reports_dir = cfg.repo_root / ".seo-engine" / "reports"
    if reports_dir.is_dir():
        families: dict[str, list[Path]] = {}
        stamp_re = re.compile(r"[-_]\d[\d\-T:]*$")
        for entry in reports_dir.iterdir():
            if not entry.is_file():
                continue
            family = stamp_re.sub("", entry.stem)
            families.setdefault(family, []).append(entry)
        report_cutoff = (datetime.now(timezone.utc) - timedelta(days=report_days)).timestamp()
        for paths in families.values():
            paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for i, path in enumerate(paths):
                if i >= keep_reports or path.stat().st_mtime < report_cutoff:
                    try:
                        path.unlink()
                        removed["reports"] += 1
                    except OSError:
                        pass

    return removed
