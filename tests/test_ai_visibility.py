"""Tests for scripts.lib.ai_visibility's pure helpers and probe_all's
provider fan-out (no transport — vendor probers are monkeypatched directly)."""

from __future__ import annotations

import pytest

from scripts.lib import ai_visibility as av
from scripts.lib import http_util
from scripts.lib.config import Config

TARGET = "mysite.org"


# ---------------------------------------------------------------------------
# citation_matches
# ---------------------------------------------------------------------------

def test_citation_matches_url_host():
    citation = {"url": "https://mysite.org/some/page", "title": "irrelevant"}
    assert av.citation_matches(citation, TARGET) is True


def test_citation_matches_subdomain():
    citation = {"url": "https://blog.mysite.org/post", "title": ""}
    assert av.citation_matches(citation, TARGET) is True


def test_citation_matches_title_only_gemini_redirect_case():
    # Gemini's groundingChunks[].web.uri is an opaque vertexaisearch redirect;
    # the real source domain arrives in web.title.
    citation = {
        "url": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc123",
        "title": "mysite.org",
    }
    assert av.citation_matches(citation, TARGET) is True


def test_citation_matches_title_subdomain_also_matches():
    citation = {"url": "https://vertexaisearch.cloud.google.com/x", "title": "blog.mysite.org"}
    assert av.citation_matches(citation, TARGET) is True


def test_citation_no_match_different_domain():
    citation = {"url": "https://otherdomain.example/page", "title": "otherdomain.example"}
    assert av.citation_matches(citation, TARGET) is False


def test_citation_no_match_empty_citation():
    assert av.citation_matches({}, TARGET) is False


# ---------------------------------------------------------------------------
# _dedupe
# ---------------------------------------------------------------------------

def test_dedupe_by_url():
    citations = [
        {"url": "https://a.example/1", "title": "First"},
        {"url": "https://a.example/1", "title": "Duplicate"},
        {"url": "https://a.example/2", "title": "Different"},
    ]
    result = av._dedupe(citations)
    assert len(result) == 2
    assert result[0]["title"] == "First"


def test_dedupe_by_title_when_no_url():
    citations = [{"title": "Same Title"}, {"title": "Same Title"}, {"title": "Other"}]
    result = av._dedupe(citations)
    assert len(result) == 2


def test_dedupe_keeps_entries_with_no_url_or_title():
    citations = [{}, {}]
    assert av._dedupe(citations) == [{}, {}]


# ---------------------------------------------------------------------------
# _provider_configured
# ---------------------------------------------------------------------------

def test_provider_configured_true_when_key_present(tmp_repo):
    cfg = tmp_repo.make_config(env={"OPENAI_API_KEY": "sk-real-key"})
    assert av._provider_configured(cfg, "openai") is True


def test_provider_configured_false_when_key_absent(tmp_repo):
    cfg = tmp_repo.make_config(env={})
    assert av._provider_configured(cfg, "anthropic") is False


def test_provider_configured_false_for_placeholder_value(tmp_repo):
    cfg = tmp_repo.make_config(env={"PERPLEXITY_API_KEY": "your-key-here"})
    assert av._provider_configured(cfg, "perplexity") is False


# ---------------------------------------------------------------------------
# probe_all
# ---------------------------------------------------------------------------

def test_probe_all_skips_unconfigured_providers(tmp_repo, monkeypatch):
    cfg = tmp_repo.make_config(env={})

    def boom(cfg, prompt, **kw):
        raise AssertionError("should never be called: provider not configured")

    monkeypatch.setattr(av, "PROBERS", {"openai": boom})
    result = av.probe_all(cfg, "prompt", TARGET)
    assert result["providers"]["openai"] == {"configured": False}


def test_probe_all_one_cited_one_errors_with_error_type(tmp_repo, monkeypatch):
    cfg = tmp_repo.make_config(env={"OPENAI_API_KEY": "k1", "ANTHROPIC_API_KEY": "k2"})

    def fake_openai(cfg, prompt, **kw):
        return {"provider": "openai", "prompt": prompt,
                "citations": [{"url": "https://mysite.org/x", "title": "x"}]}

    def fake_anthropic(cfg, prompt, **kw):
        raise http_util.HttpError("request timed out for key=SECRET123", error_type="timeout")

    monkeypatch.setattr(av, "PROBERS", {"openai": fake_openai, "anthropic": fake_anthropic})
    result = av.probe_all(cfg, "prompt", TARGET)

    openai_result = result["providers"]["openai"]
    assert openai_result["configured"] is True
    assert openai_result["cited"] is True
    assert openai_result["citation_count"] == 1
    assert "error" not in openai_result

    anthropic_result = result["providers"]["anthropic"]
    assert anthropic_result["configured"] is True
    assert anthropic_result["error_type"] == "timeout"
    assert "cited" not in anthropic_result
    # Error text is sanitized (no leaked credential fragment).
    assert "SECRET123" not in anthropic_result["error"]
    assert "key=REDACTED" in anthropic_result["error"]


def test_probe_all_not_cited_when_no_citation_matches(tmp_repo, monkeypatch):
    cfg = tmp_repo.make_config(env={"OPENAI_API_KEY": "k1"})

    def fake_openai(cfg, prompt, **kw):
        return {"provider": "openai", "prompt": prompt,
                "citations": [{"url": "https://unrelated.example/x", "title": "unrelated"}]}

    monkeypatch.setattr(av, "PROBERS", {"openai": fake_openai})
    result = av.probe_all(cfg, "prompt", TARGET)
    assert result["providers"]["openai"]["cited"] is False


def test_probe_all_error_type_falls_back_to_exception_class_name(tmp_repo, monkeypatch):
    cfg = tmp_repo.make_config(env={"OPENAI_API_KEY": "k1"})

    def fake_openai(cfg, prompt, **kw):
        raise ValueError("something unexpected broke")

    monkeypatch.setattr(av, "PROBERS", {"openai": fake_openai})
    result = av.probe_all(cfg, "prompt", TARGET)
    assert result["providers"]["openai"]["error_type"] == "ValueError"
