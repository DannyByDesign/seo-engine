import json

import pytest

from scripts.lib import llm, sociavault
from scripts.lib.config import Config


def _cfg(tmp_path, **env):
    return Config(repo_root=tmp_path, env=env, site={})


def test_single_gateway_and_model_configuration(tmp_path):
    with pytest.raises(llm.LlmError, match="OPENROUTER_API_KEY"):
        llm.pick_provider(_cfg(tmp_path, OPENAI_API_KEY="old-key"))
    cfg = _cfg(tmp_path, OPENROUTER_API_KEY="sk-x", LLM_MODEL="vendor/writer", LLM_CHEAP_MODEL="vendor/cheap")
    assert llm.pick_provider(cfg) == "openrouter"
    assert llm.configured_providers(cfg) == ["openrouter"]
    assert llm.model_for(cfg) == "vendor/writer"
    assert llm.model_for(cfg, tier="cheap") == "vendor/cheap"
    with pytest.raises(llm.LlmError, match="OpenRouter"):
        llm.pick_provider(cfg, "openai")


def test_openrouter_request_and_response(tmp_path, fake_transport):
    cfg = _cfg(tmp_path, OPENROUTER_API_KEY="sk-test", LLM_MODEL="vendor/writer")
    fake_transport.route("POST", "https://openrouter.ai/api/v1/chat/completions", {
        "body": json.dumps({"model": "vendor/writer", "choices": [{"message": {"content": '{"a": 1}'},
                            "finish_reason": "stop"}], "usage": {"prompt_tokens": 3, "completion_tokens": 4, "cost": 0.001}})})
    result = llm.complete(cfg, "sys", "user", json_mode=True, effort="medium")
    assert result["provider"] == "openrouter" and result["model"] == "vendor/writer"
    assert result["usage"] == {"input_tokens": 3, "output_tokens": 4, "cost": 0.001}
    kwargs = fake_transport.calls[-1][2]
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test"
    body = kwargs["json"]
    assert body["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "user"}]
    assert body["response_format"] == {"type": "json_object"}
    assert body["reasoning"] == {"effort": "medium"}
    assert body["provider"] == {"require_parameters": True}
    assert llm.complete_json(cfg, "s", "u", model="other/model") == {"a": 1}
    assert fake_transport.calls[-1][2]["json"]["model"] == "other/model"


@pytest.mark.parametrize("response", [
    {"error": {"message": "SECRET rejected"}},
    {"choices": []},
    {"choices": [{"message": {"content": ""}}]},
    {"choices": [{"message": {"content": "partial"}, "finish_reason": "length"}]},
    {"choices": [{"message": {"content": "no", "refusal": "reason"}}]},
    {"choices": [{"message": {"content": "no"}, "finish_reason": "content_filter"}]},
])
def test_gateway_rejects_unusable_answers(tmp_path, fake_transport, response):
    cfg = _cfg(tmp_path, OPENROUTER_API_KEY="SECRET")
    fake_transport.route("POST", "https://openrouter.ai/", {"body": json.dumps(response)})
    with pytest.raises(llm.LlmError) as error:
        llm.complete(cfg, "", "x")
    assert "SECRET" not in str(error.value)


def test_json_retry_uses_same_model(tmp_path, fake_transport):
    cfg = _cfg(tmp_path, OPENROUTER_API_KEY="key")
    fake_transport.route("POST", "https://openrouter.ai/", *[
        {"body": json.dumps({"choices": [{"message": {"content": reply}, "finish_reason": "stop"}]})}
        for reply in ["not json", '{"ok": true}']])
    assert llm.complete_json(cfg, "", "x", model="vendor/rewrite") == {"ok": True}
    assert [c[2]["json"]["model"] for c in fake_transport.calls] == ["vendor/rewrite"] * 2


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


def test_gateway_redacts_credentials_from_transport_errors(tmp_path, fake_transport):
    import requests
    cfg = _cfg(tmp_path, OPENROUTER_API_KEY='sensitive-value')
    fake_transport.route('POST', 'https://openrouter.ai/', requests.ConnectionError('failed: sensitive-value'))
    with pytest.raises(llm.LlmError) as error:
        llm.complete(cfg, '', 'x')
    assert 'sensitive-value' not in str(error.value)
