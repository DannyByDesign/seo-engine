import json

import pytest

from scripts.lib import llm, sociavault
from scripts.lib.config import Config


def _cfg(tmp_path, **env):
    return Config(repo_root=tmp_path, env=env, site={})


def test_pick_provider_orders_and_errors(tmp_path):
    with pytest.raises(llm.LlmError):
        llm.pick_provider(_cfg(tmp_path))
    cfg = _cfg(tmp_path, OPENAI_API_KEY="sk-x", GOOGLE_GEMINI_API_KEY="g")
    assert llm.pick_provider(cfg) == "openai"
    assert llm.pick_provider(cfg, "gemini") == "gemini"
    with pytest.raises(llm.LlmError):
        llm.pick_provider(cfg, "anthropic")
    assert llm.model_for(_cfg(tmp_path, LLM_MODEL_OPENAI="gpt-next"), "openai") == "gpt-next"
    assert llm.model_for(cfg, "anthropic", "cheap") == "claude-haiku-4-5"


def test_anthropic_adapter_shapes_request_and_parses(tmp_path, fake_transport):
    cfg = _cfg(tmp_path, ANTHROPIC_API_KEY="sk-ant-test")
    fake_transport.route(
        "POST", "https://api.anthropic.com/v1/messages",
        {"body": json.dumps({"content": [{"type": "text", "text": "hello"}], "stop_reason": "end_turn",
                             "usage": {"input_tokens": 3, "output_tokens": 1}})},
        {"body": json.dumps({"content": [], "stop_reason": "refusal", "stop_details": {"category": "cyber"}})},
    )
    out = llm.complete(cfg, "sys", "user", effort="medium")
    assert out["text"] == "hello" and out["model"] == "claude-opus-5"
    _, _, kwargs = fake_transport.calls[-1]
    body = kwargs["json"]
    assert body["system"] == "sys" and body["output_config"] == {"effort": "medium"}
    assert "thinking" not in body and "temperature" not in body
    assert kwargs["headers"]["x-api-key"] == "sk-ant-test"

    with pytest.raises(llm.LlmError):
        llm.complete(cfg, "", "x", tier="cheap", effort="high")
    assert "output_config" not in fake_transport.calls[-1][2]["json"]


def test_openai_and_gemini_adapters(tmp_path, fake_transport):
    cfg = _cfg(tmp_path, OPENAI_API_KEY="sk-o", GOOGLE_GEMINI_API_KEY="g-key")
    fake_transport.route("POST", "https://api.openai.com/v1/responses", {
        "body": json.dumps({"output": [{"type": "message", "content": [
            {"type": "output_text", "text": "```json\n{\"a\": 1}\n```"}]}],
            "usage": {"input_tokens": 5, "output_tokens": 4}})})
    assert llm.complete_json(cfg, "s", "u", provider="openai") == {"a": 1}
    body = fake_transport.calls[-1][2]["json"]
    assert body["instructions"] == "s" and body["text"]["format"]["type"] == "json_object"

    fake_transport.route("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent", {
        "body": json.dumps({"candidates": [{"content": {"parts": [{"text": "prose [1, 2] tail"}]},
                                            "finishReason": "STOP"}],
                            "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 2}})})
    assert llm.complete_json(cfg, "s", "u", provider="gemini") == [1, 2]
    assert fake_transport.calls[-1][2]["headers"]["x-goog-api-key"] == "g-key"


def test_extract_json_edge_cases():
    assert llm.extract_json('Sure: {"k": [1, {"n": "}"}]} done') == {"k": [1, {"n": "}"}]}
    with pytest.raises(llm.LlmError):
        llm.extract_json("no json here")


def test_sociavault_normalizes_index_keyed_objects(tmp_path, fake_transport):
    cfg = _cfg(tmp_path, SOCIAVAULT_API_KEY="sk_live_1")
    reddit = {"success": True, "credits_used": 1, "data": {"success": True, "posts": {
        "1": {"title": "second", "permalink": "/r/x/2", "ups": 5, "num_comments": 1, "created_utc": 1700000000,
              "subreddit": "x", "author": "b"},
        "0": {"title": "first", "permalink": "/r/x/1", "score": 10, "num_comments": 2, "created_utc": 1700000001,
              "subreddit": "x", "author": "a", "selftext": "body"},
    }}}
    fake_transport.route("GET", "https://api.sociavault.com/v1/scrape/reddit/search", {"body": json.dumps(reddit)})
    fake_transport.route("GET", "https://api.sociavault.com/v1/scrape/tiktok/search/keyword", 500)
    out = sociavault.search_conversations(cfg, "ai ads", platforms=("reddit", "tiktok"))
    assert [p["title"] for p in out["posts"]] == ["first", "second"]
    assert out["posts"][0]["url"] == "https://www.reddit.com/r/x/1"
    assert out["posts"][0]["community"] == "r/x" and out["posts"][0]["score"] == 10
    assert "tiktok" in out["errors"] and out["credits_used"] == 1
    method, url, kwargs = fake_transport.calls[0]
    assert kwargs["headers"]["X-API-Key"] == "sk_live_1" and kwargs["params"]["timeframe"] == "week"


def test_sociavault_success_false_raises(tmp_path, fake_transport):
    cfg = _cfg(tmp_path, SOCIAVAULT_API_KEY="sk_live_1")
    fake_transport.route("GET", "https://api.sociavault.com/v1/credits",
                         {"body": json.dumps({"success": False, "error": "bad key"})})
    with pytest.raises(sociavault.SociaVaultError):
        sociavault.credits(cfg)
    item = {"aweme_info": {"aweme_id": "7", "desc": "d", "statistics": {"digg_count": 3, "play_count": 9},
                           "author": {"unique_id": "u", "nickname": "N"}, "create_time": 1700000000}}
    n = sociavault.normalize("tiktok", item)
    assert n["url"] == "https://www.tiktok.com/@u/video/7" and n["views"] == 9 and n["author"] == "N"
