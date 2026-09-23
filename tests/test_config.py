"""Tests for scripts.lib.config: placeholders, site_url, repo-root discovery,
env layering, integration availability, and site-config persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts.lib import config
from scripts.lib.config import Config, MissingConfigError

UNUSED_ROOT = Path("/unused")


def _cfg(env=None, site=None, root=UNUSED_ROOT):
    return Config(repo_root=root, env=dict(env or {}), site=dict(site or {}))


@pytest.mark.parametrize("value,ok", [
    ("your-key", False),
    ("<KEY>", False),
    ("/path/to/creds.json", False),
    ("changeme", False),
    ("CHANGEME-NOW", False),
    ("https://your-site.example.com", False),
    ("", False),
    ("   ", False),
    ("sk-live-abc123", True),
    ("/Users/me/creds.json", True),
    ("hunter2", True),
])
def test_placeholder_matrix_via_has(value, ok):
    assert _cfg(env={"K": value}).has("K") is ok


def test_require_returns_stripped_real_value():
    assert _cfg(env={"K": "  real-value  "}).require("K", "hint") == "real-value"


def test_require_raises_missing_config_error_naming_the_key():
    with pytest.raises(MissingConfigError) as ei:
        _cfg(env={}).require("SOME_API_KEY", "Get one at example dot org.")
    assert ei.value.key == "SOME_API_KEY"
    assert "SOME_API_KEY" in str(ei.value)
    assert "Get one at example dot org." in str(ei.value)


def test_require_rejects_placeholder_value():
    with pytest.raises(MissingConfigError):
        _cfg(env={"K": "your-key-here"}).require("K", "hint")


def test_site_url_valid_https_and_trailing_slash_rstripped():
    assert _cfg(env={"SEO_SITE_URL": "https://mysite.org/"}).site_url == "https://mysite.org"


def test_site_url_missing_raises():
    with pytest.raises(MissingConfigError) as ei:
        _ = _cfg().site_url
    assert ei.value.key == "SEO_SITE_URL"


def test_site_url_placeholder_domain_raises():
    with pytest.raises(MissingConfigError):
        _ = _cfg(env={"SEO_SITE_URL": "https://www.example.com"}).site_url


def test_site_url_without_scheme_raises():
    with pytest.raises(MissingConfigError):
        _ = _cfg(env={"SEO_SITE_URL": "not-a-url"}).site_url


def test_site_config_value_takes_precedence_over_env():
    cfg = _cfg(env={"SEO_SITE_URL": "https://from-env.org"},
               site={"site_url": "https://from-site.org"})
    assert cfg.site_url == "https://from-site.org"


@pytest.mark.parametrize("marker,is_dir", [
    (".git", True),
    (".seo-engine", True),
    ("package.json", False),
])
def test_find_repo_root_walks_up_to_marker(tmp_path, monkeypatch, marker, is_dir):
    monkeypatch.delenv("SEO_REPO_ROOT", raising=False)
    root = tmp_path / "proj"
    nested = root / "a" / "b"
    nested.mkdir(parents=True)
    if is_dir:
        (root / marker).mkdir()
    else:
        (root / marker).write_text("{}")
    assert config.find_repo_root(nested) == root.resolve()


def test_find_repo_root_returns_start_when_no_marker(tmp_path, monkeypatch):
    monkeypatch.delenv("SEO_REPO_ROOT", raising=False)
    start = tmp_path / "plain" / "x" / "y"
    start.mkdir(parents=True)
    assert config.find_repo_root(start) == start.resolve()


def test_seo_repo_root_env_override_wins(tmp_path, monkeypatch):
    pinned = tmp_path / "pinned"
    pinned.mkdir()
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / ".git").mkdir(parents=True)
    monkeypatch.setenv("SEO_REPO_ROOT", str(pinned))
    assert config.find_repo_root(elsewhere) == pinned.resolve()


def test_seo_repo_root_pointing_at_nonexistent_dir_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("SEO_REPO_ROOT", str(tmp_path / "gone"))
    with pytest.raises(MissingConfigError) as ei:
        config.find_repo_root(tmp_path)
    assert ei.value.key == "SEO_REPO_ROOT"


def test_load_env_precedence(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    engine.mkdir()
    repo = tmp_path / "repo"
    (repo / ".seo-engine").mkdir(parents=True)

    (engine / ".env").write_text(
        'export SEOTEST_A="engine-a"\nSEOTEST_B=engine-b\nSEOTEST_C=engine-c\n'
    )
    (repo / ".env").write_text("SEOTEST_B=repo-b\nSEOTEST_C=repo-c\n")

    monkeypatch.delenv("SEO_REPO_ROOT", raising=False)
    monkeypatch.delenv("SEOTEST_A", raising=False)
    monkeypatch.delenv("SEOTEST_B", raising=False)
    monkeypatch.setenv("SEOTEST_C", "process-c")
    monkeypatch.setattr(config, "_engine_root", lambda: engine)

    cfg = Config.load(repo)
    assert cfg.repo_root == repo.resolve()
    assert cfg.env["SEOTEST_A"] == "engine-a"
    assert cfg.env["SEOTEST_B"] == "repo-b"
    assert cfg.env["SEOTEST_C"] == "process-c"


def test_load_reads_site_yaml(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / ".seo-engine").mkdir(parents=True)
    (repo / ".seo-engine" / "config.yml").write_text("site_url: https://loaded.org\n")
    monkeypatch.delenv("SEO_REPO_ROOT", raising=False)
    monkeypatch.setattr(config, "_engine_root", lambda: tmp_path / "no-engine")

    cfg = Config.load(repo)
    assert cfg.site == {"site_url": "https://loaded.org"}
    assert cfg.site_url == "https://loaded.org"


def test_gsc_available_with_either_var():
    assert _cfg(env={"GOOGLE_APPLICATION_CREDENTIALS": "/Users/me/creds.json"}) \
        .integration_available("google_search_console")
    assert _cfg(env={"GSC_SERVICE_ACCOUNT_JSON": '{"type": "service_account"}'}) \
        .integration_available("google_search_console")
    assert not _cfg(env={}).integration_available("google_search_console")


def test_dataforseo_requires_both_vars():
    assert not _cfg(env={"DATAFORSEO_LOGIN": "me@x.org"}).integration_available("dataforseo")
    assert not _cfg(env={"DATAFORSEO_PASSWORD": "pw123"}).integration_available("dataforseo")
    assert _cfg(env={"DATAFORSEO_LOGIN": "me@x.org", "DATAFORSEO_PASSWORD": "pw123"}) \
        .integration_available("dataforseo")


def test_profound_and_otterly_are_independent():
    cfg = _cfg(env={"PROFOUND_API_KEY": "pk-123"})
    avail = cfg.available_integrations()
    assert avail["profound"] is True
    assert avail["otterly"] is False


def test_placeholder_value_does_not_unlock_integration():
    assert not _cfg(env={"GOOGLE_PSI_API_KEY": "your-key"}) \
        .integration_available("pagespeed_insights")


def test_available_integrations_covers_every_entry():
    assert set(_cfg().available_integrations()) == set(config.INTEGRATION_ENV_VARS)


def test_save_site_config_merges_into_existing_yaml(tmp_repo):
    cfg = tmp_repo.make_config(site={"site_url": "https://old.org", "keep": 1})
    path = cfg.repo_root / ".seo-engine" / "config.yml"
    path.write_text(yaml.safe_dump({"site_url": "https://old.org", "keep": 1}))

    out = config.save_site_config(cfg, {"site_url": "https://new.org", "extra": "x"})
    assert out == path
    data = yaml.safe_load(path.read_text())
    assert data == {"site_url": "https://new.org", "keep": 1, "extra": "x"}
    assert cfg.site == data
    assert list(path.parent.glob("*.tmp")) == []


def test_save_site_config_creates_dirs_when_absent(tmp_path):
    root = tmp_path / "brand-new"
    cfg = Config(repo_root=root, env={}, site={})
    out = config.save_site_config(cfg, {"site_url": "https://fresh.org"})
    assert out.is_file()
    assert yaml.safe_load(out.read_text()) == {"site_url": "https://fresh.org"}
    assert cfg.site == {"site_url": "https://fresh.org"}
