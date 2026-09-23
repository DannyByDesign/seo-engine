"""Tests for scripts.lib.ai_visibility's pure helpers and probe_all's
provider fan-out (no transport — vendor probers are monkeypatched directly)."""

from __future__ import annotations

import pytest

from scripts.lib import ai_visibility as av
from scripts.lib import http_util
from scripts.lib.config import Config

TARGET = "mysite.org"


def test_citation_matches_url_host():
    citation = {"url": "https://mysite.org/some/page", "title": "irrelevant"}
    assert av.citation_matches(citation, TARGET) is True


def test_citation_matches_subdomain():
    citation = {"url": "https://blog.mysite.org/post", "title": ""}
    assert av.citation_matches(citation, TARGET) is True


def test_citation_matches_title_only_gemini_redirect_case():
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


def test_gateway_configuration(tmp_repo):
    cfg = tmp_repo.make_config(env={"OPENROUTER_API_KEY": "key", "AI_VISIBILITY_MODELS": "vendor/one,vendor/two,vendor/one"})
    names = av.probe_names(cfg)
    assert names == ["openrouter:vendor/one:search=exa", "openrouter:vendor/two:search=exa"]
    assert av._provider_configured(cfg, names[0])
    assert not av._provider_configured(cfg, "openai")
    cfg.env["OPENROUTER_API_KEY"] = "your-key-here"
    assert not av._provider_configured(cfg, names[0])


def test_probe_all_skips_without_key(tmp_repo, fake_transport):
    cfg = tmp_repo.make_config()
    assert all(p == {"configured": False} for p in av.probe_all(cfg, "q", TARGET)["providers"].values())
    assert not fake_transport.calls


def test_probe_citations_and_errors_are_separate(tmp_repo, fake_transport):
    import json
    cfg = tmp_repo.make_config(env={"OPENROUTER_API_KEY": "key", "AI_VISIBILITY_MODELS": "vendor/one,vendor/two"})
    fake_transport.route("POST", "https://openrouter.ai/api/v1/chat/completions",
        {"body": json.dumps({"choices": [{"message": {"content": "answer", "annotations": [
            {"type": "url_citation", "url_citation": {"url": "https://mysite.org/x", "title": "x"}}]}, "finish_reason": "stop"}]})},
        {"body": json.dumps({"error": {"message": "denied SECRET123"}})})
    result = av.probe_all(cfg, "q", TARGET)["providers"]
    first, second = av.probe_names(cfg)
    assert result[first]["cited"] and result[first]["citation_count"] == 1
    assert "cited" not in result[second] and "SECRET123" not in result[second]["error"]
    body = fake_transport.calls[0][2]["json"]
    assert body["tools"][0]["type"] == "openrouter:web_search"
    assert body["tools"][0]["parameters"]["engine"] == "exa"
    assert body["max_tool_calls"] == 3


@pytest.mark.parametrize("searches,has_error", [(0, True), (None, True), (1, False)])
def test_no_search_is_unknown_not_uncited(tmp_repo, fake_transport, searches, has_error):
    import json
    cfg = tmp_repo.make_config(env={"OPENROUTER_API_KEY": "key", "AI_VISIBILITY_MODELS": "vendor/one"})
    fake_transport.route("POST", "https://openrouter.ai/", {"body": json.dumps({
        "choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}],
        "usage": {"server_tool_use": {"web_search_requests": searches}}})})
    result = av.probe_all(cfg, "q", TARGET)["providers"][av.probe_names(cfg)[0]]
    assert ("error" in result) == has_error
    if not has_error:
        assert result["cited"] is False


def test_history_diff_uses_model_identity_and_keeps_legacy_series_separate():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / '06-learn/geo-monitor/scripts/track_ai_visibility.py'
    spec = importlib.util.spec_from_file_location('visibility_tracker', path)
    tracker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tracker)
    name = 'openrouter:vendor/one:search=exa'

    def record(state, identity=name):
        return {'providers': {identity: {'state': state, 'citation_urls': ['https://mysite.org/x']}}}

    current = record('not_cited')
    legacy = tracker._diff_against_prior(current, [record('cited', 'openai')], False)
    assert legacy['providers'][name]['change'] == 'provider_newly_configured'
    first_miss = tracker._diff_against_prior(current, [record('cited')], False)
    assert first_miss['providers'][name]['change'] == 'possible_citation_loss'
    second_miss = tracker._diff_against_prior(current, [record('not_cited'), record('cited')], False)
    assert second_miss['providers'][name]['change'] == 'confirmed_citation_loss'
    error = tracker._diff_against_prior(record('error'), [record('cited')], False)
    assert error['providers'][name]['change'] == 'indeterminate_provider_error'
