"""Tests for scripts.lib.snapshots: the provenance-tagged crawl store."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import pytest

import scripts.lib.crawler as crawler
from scripts.lib import snapshots

SITE = "https://mysite.org"
NOW = datetime.now(timezone.utc)


def write_snap(cfg, stamp, *, finished_at=None, site_url=SITE, max_pages=100,
               pages=5, truncated=False):
    """Materialize a fake stored snapshot (jsonl + sidecar) directly."""
    d = snapshots.crawl_dir(cfg)
    jsonl = d / f"crawl-{stamp}.jsonl"
    jsonl.write_text(
        "".join(json.dumps({"url": f"{site_url}/{i}"}) + "\n" for i in range(pages)),
        encoding="utf-8",
    )
    meta = {
        "schema_version": snapshots.SCHEMA_VERSION,
        "site_url": site_url,
        "finished_at": (finished_at or NOW).isoformat(),
        "max_pages": max_pages,
        "pages_crawled": pages,
        "truncated": truncated,
    }
    jsonl.with_name(jsonl.stem + ".meta.json").write_text(json.dumps(meta))
    return snapshots._load_snapshot(jsonl)


def site_cfg(tmp_repo):
    return tmp_repo.make_config(env={"SEO_SITE_URL": SITE})


def fake_crawler(monkeypatch, pages: int):
    def crawl_to_file(start_url, out_path, **kwargs):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as fh:
            for i in range(pages):
                fh.write(json.dumps({"url": f"{start_url}/p{i}", "status": 200}) + "\n")
        return {"pages": pages}
    monkeypatch.setattr(crawler, "crawl_to_file", crawl_to_file)


# ---------------------------------------------------------------------------
# new_crawl
# ---------------------------------------------------------------------------

def test_new_crawl_writes_jsonl_and_provenance_sidecar(tmp_repo, monkeypatch):
    fake_crawler(monkeypatch, pages=3)
    cfg = site_cfg(tmp_repo)
    snap = snapshots.new_crawl(cfg, "seo-audit", max_pages=10)

    assert re.fullmatch(r"crawl-\d{8}T\d{6}Z\.jsonl", snap.path.name)
    meta_path = snap.path.with_name(snap.path.stem + ".meta.json")
    assert meta_path.is_file()
    meta = json.loads(meta_path.read_text())
    assert meta["schema_version"] == snapshots.SCHEMA_VERSION
    assert meta["site_url"] == SITE
    assert meta["producer_skill"] == "seo-audit"
    assert meta["max_pages"] == 10
    assert meta["pages_crawled"] == 3
    assert meta["truncated"] is False  # 3 < max_pages

    assert list(snap.pages()) == [
        {"url": f"{SITE}/p{i}", "status": 200} for i in range(3)
    ]


def test_new_crawl_truncated_when_pages_hit_max(tmp_repo, monkeypatch):
    fake_crawler(monkeypatch, pages=10)
    cfg = site_cfg(tmp_repo)
    snap = snapshots.new_crawl(cfg, "seo-audit", max_pages=10)
    assert snap.truncated is True
    assert snap.pages_crawled == 10


# ---------------------------------------------------------------------------
# all_snapshots / latest
# ---------------------------------------------------------------------------

def test_all_snapshots_newest_first(tmp_repo):
    cfg = site_cfg(tmp_repo)
    old = write_snap(cfg, "s-old", finished_at=NOW - timedelta(hours=3))
    new = write_snap(cfg, "s-new", finished_at=NOW - timedelta(hours=1))
    mid = write_snap(cfg, "s-mid", finished_at=NOW - timedelta(hours=2))
    assert [s.path for s in snapshots.all_snapshots(cfg)] == [
        new.path, mid.path, old.path,
    ]


def test_all_snapshots_site_url_filter(tmp_repo):
    cfg = site_cfg(tmp_repo)
    mine = write_snap(cfg, "s-mine", finished_at=NOW - timedelta(hours=1))
    write_snap(cfg, "s-other", finished_at=NOW - timedelta(hours=2),
               site_url="https://other.org")
    got = snapshots.all_snapshots(cfg, site_url=SITE)
    assert [s.path for s in got] == [mine.path]


def test_latest_honors_max_age_hours(tmp_repo):
    cfg = site_cfg(tmp_repo)
    write_snap(cfg, "s-stale", finished_at=NOW - timedelta(hours=48))
    assert snapshots.latest(cfg, max_age_hours=24) is None

    fresh = write_snap(cfg, "s-fresh", finished_at=NOW - timedelta(hours=2))
    got = snapshots.latest(cfg, max_age_hours=24)
    assert got is not None and got.path == fresh.path


def test_latest_min_pages_skips_small_snapshot(tmp_repo):
    cfg = site_cfg(tmp_repo)
    small = write_snap(cfg, "s-small", finished_at=NOW - timedelta(hours=1), pages=5)
    big = write_snap(cfg, "s-big", finished_at=NOW - timedelta(hours=2), pages=50)
    assert snapshots.latest(cfg, max_age_hours=24).path == small.path
    assert snapshots.latest(cfg, max_age_hours=24, min_pages=10).path == big.path


# ---------------------------------------------------------------------------
# find_baseline
# ---------------------------------------------------------------------------

def test_find_baseline_returns_most_recent_comparable(tmp_repo):
    cfg = site_cfg(tmp_repo)
    older = write_snap(cfg, "s0", finished_at=NOW - timedelta(days=10))
    newer = write_snap(cfg, "s1", finished_at=NOW - timedelta(days=5))
    current = write_snap(cfg, "s2", finished_at=NOW)
    result = snapshots.find_baseline(cfg, current)
    assert result.refusal_reason is None
    assert result.snapshot.path == newer.path
    assert older.path != newer.path


def test_find_baseline_skips_truncated_prior(tmp_repo):
    cfg = site_cfg(tmp_repo)
    good = write_snap(cfg, "s0", finished_at=NOW - timedelta(days=10))
    write_snap(cfg, "s1", finished_at=NOW - timedelta(days=5), truncated=True)
    current = write_snap(cfg, "s2", finished_at=NOW)
    result = snapshots.find_baseline(cfg, current)
    assert result.snapshot.path == good.path


def test_find_baseline_refuses_when_only_different_max_pages(tmp_repo):
    cfg = site_cfg(tmp_repo)
    write_snap(cfg, "s0", finished_at=NOW - timedelta(days=5), max_pages=500)
    current = write_snap(cfg, "s1", finished_at=NOW, max_pages=100)
    result = snapshots.find_baseline(cfg, current)
    assert result.snapshot is None
    assert "no prior snapshot is comparable" in result.refusal_reason


def test_find_baseline_refuses_when_current_truncated(tmp_repo):
    cfg = site_cfg(tmp_repo)
    write_snap(cfg, "s0", finished_at=NOW - timedelta(days=5))
    current = write_snap(cfg, "s1", finished_at=NOW, truncated=True)
    result = snapshots.find_baseline(cfg, current)
    assert result.snapshot is None
    assert "hit its max_pages cap" in result.refusal_reason


def test_find_baseline_min_age_days_filter(tmp_repo):
    cfg = site_cfg(tmp_repo)
    write_snap(cfg, "s-young", finished_at=NOW - timedelta(hours=1))
    current = write_snap(cfg, "s-cur", finished_at=NOW)
    result = snapshots.find_baseline(cfg, current, min_age_days=7)
    assert result.snapshot is None
    assert "at least 7 days old" in result.refusal_reason

    aged = write_snap(cfg, "s-aged", finished_at=NOW - timedelta(days=8))
    result = snapshots.find_baseline(cfg, current, min_age_days=7)
    assert result.snapshot.path == aged.path


def test_find_baseline_refuses_when_no_prior_exists(tmp_repo):
    cfg = site_cfg(tmp_repo)
    current = write_snap(cfg, "s-only", finished_at=NOW)
    result = snapshots.find_baseline(cfg, current)
    assert result.snapshot is None
    assert "no prior snapshot" in result.refusal_reason


def test_find_baseline_not_comparable_ok_when_not_required(tmp_repo):
    cfg = site_cfg(tmp_repo)
    prior = write_snap(cfg, "s0", finished_at=NOW - timedelta(days=5), truncated=True)
    current = write_snap(cfg, "s1", finished_at=NOW)
    result = snapshots.find_baseline(cfg, current, require_comparable=False)
    assert result.snapshot.path == prior.path


# ---------------------------------------------------------------------------
# prune
# ---------------------------------------------------------------------------

def test_prune_keeps_only_newest_keep_crawls(tmp_repo):
    cfg = site_cfg(tmp_repo)
    snaps = [
        write_snap(cfg, f"s{i:02d}", finished_at=NOW - timedelta(hours=i))
        for i in range(12)
    ]
    removed = snapshots.prune(cfg, keep_crawls=10, keep_days=90)
    assert removed["crawls"] == 4  # 2 snapshots x (jsonl + sidecar)
    remaining = sorted(p.name for p in snapshots.crawl_dir(cfg).glob("*.jsonl"))
    assert len(remaining) == 10
    for oldest in snaps[10:]:
        assert not oldest.path.exists()
        assert not oldest.path.with_name(oldest.path.stem + ".meta.json").exists()


def test_prune_removes_old_by_days_even_under_count(tmp_repo):
    cfg = site_cfg(tmp_repo)
    keeper = write_snap(cfg, "s-new", finished_at=NOW - timedelta(days=1))
    goner = write_snap(cfg, "s-ancient", finished_at=NOW - timedelta(days=200))
    removed = snapshots.prune(cfg, keep_crawls=10, keep_days=90)
    assert removed["crawls"] == 2
    assert keeper.path.exists()
    assert not goner.path.exists()


def test_prune_reports_per_family(tmp_repo):
    cfg = site_cfg(tmp_repo)
    rdir = cfg.repo_root / ".seo-engine" / "reports"
    rdir.mkdir(parents=True, exist_ok=True)
    now = time.time()

    # 35-file family "maintenance": keeps the 30 newest.
    for i in range(35):
        p = rdir / f"maintenance-2026-01-{i:02d}.json"
        p.write_text("{}")
        os.utime(p, (now - i * 3600, now - i * 3600))
    # Two files with full timestamps group into one family "foo".
    for i in (1, 2):
        p = rdir / f"foo-2026010{i}-120000.json"
        p.write_text("{}")
        os.utime(p, (now - i, now - i))
    # A lone file older than report_days is removed despite the count.
    old = rdir / "bar-2026-01-01.json"
    old.write_text("{}")
    os.utime(old, (now - 200 * 86400, now - 200 * 86400))

    removed = snapshots.prune(cfg, keep_reports=30, report_days=180)
    assert removed["reports"] == 6  # 5 maintenance overflow + 1 stale bar
    remaining = {p.name for p in rdir.iterdir()}
    maintenance = {n for n in remaining if n.startswith("maintenance-")}
    assert len(maintenance) == 30
    # The 5 oldest (highest i) maintenance files are the ones gone.
    for i in range(30, 35):
        assert f"maintenance-2026-01-{i:02d}.json" not in remaining
    assert {"foo-20260101-120000.json", "foo-20260102-120000.json"} <= remaining
    assert "bar-2026-01-01.json" not in remaining
