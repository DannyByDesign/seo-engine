"""BYOK text-generation client — Anthropic, OpenAI, Gemini behind one call.

Why raw HTTP instead of the vendor SDKs: every byte this engine sends
leaves through `http_util` (credential sanitization on every surfaced URL
and error, idempotency-aware retries) and every test fakes the network at
`http_util._send`. Three vendor SDKs would mean three egress paths and
three mocking strategies; one thin adapter per provider keeps the repo's
"only one egress" invariant and lets the whole content pipeline run
offline in pytest.

Provider-specific adapters:
* Anthropic: `claude-opus-5` for quality work, `claude-haiku-4-5` for
  cheap classification. Thinking is adaptive by default on Opus 5 — the
  `thinking` parameter is deliberately omitted. Sampling parameters
  (temperature/top_p) are rejected by 4.6+ models and are never sent.
  `output_config.effort` is sent only to models that accept it (not Haiku).
  A `stop_reason == "refusal"` is surfaced as LlmError, never as empty text.
* OpenAI: Responses API (`/v1/responses`), `instructions` for the system
  prompt, `text.format = json_object` in JSON mode.
* Gemini: `generateContent` with `systemInstruction`; JSON mode via
  `responseMimeType`.

Model ids are env-overridable (`LLM_MODEL_<PROVIDER>`,
`LLM_CHEAP_MODEL_<PROVIDER>`) because model availability changes; `scripts/dev/smoke.py` is the place to confirm them.

Every call returns {text, provider, model, usage{input_tokens,
output_tokens}} so scripts can log spend per stage.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from . import http_util
from .config import INTEGRATION_ENV_VARS, Config

LLM_TIMEOUT = 300.0
PROVIDER_ORDER = ("anthropic", "openai", "gemini")

DEFAULT_MODELS: dict[str, dict[str, str]] = {
    "anthropic": {"quality": "claude-opus-5", "cheap": "claude-haiku-4-5"},
    "openai": {"quality": "gpt-5", "cheap": "gpt-5-mini"},
    "gemini": {"quality": "gemini-2.5-pro", "cheap": "gemini-2.5-flash"},
}

_NO_EFFORT_PREFIXES = ("claude-haiku", "claude-sonnet-4-5", "claude-3")


class LlmError(RuntimeError):
    """A provider call failed or returned something unusable. Message is
    pre-sanitized (no credentials)."""


def configured_providers(cfg: Config) -> list[str]:
    out = []
    for name in PROVIDER_ORDER:
        spec = INTEGRATION_ENV_VARS[name]
        env_vars = spec.get("all") or spec.get("any") or []
        if all(cfg.has(v) for v in env_vars):
            out.append(name)
    return out


def pick_provider(cfg: Config, prefer: Optional[str] = None) -> str:
    """Use the explicitly selected provider, or the only configured provider.
    Multiple credentials do not imply a preference for a model vendor."""
    available = configured_providers(cfg)
    wanted = (prefer or cfg.get("LLM_PROVIDER") or "").strip().lower()
    if wanted:
        if wanted not in DEFAULT_MODELS:
            raise LlmError(f"Unknown LLM provider {wanted!r}; choose one of {list(DEFAULT_MODELS)}")
        if wanted in available:
            return wanted
        needed = INTEGRATION_ENV_VARS[wanted]["all"]
        raise LlmError(f"LLM provider {wanted!r} requested but {needed} is not set.")
    if len(available) == 1:
        return available[0]
    if available:
        raise LlmError('Multiple LLM providers are configured. Set LLM_PROVIDER or select a provider explicitly.')
    raise LlmError(
        "No LLM provider configured. Set one of ANTHROPIC_API_KEY, OPENAI_API_KEY, "
        "GOOGLE_GEMINI_API_KEY in .env (see .env.example)."
    )


def model_for(cfg: Config, provider: str, tier: str = "quality") -> str:
    env_key = ("LLM_MODEL_" if tier == "quality" else "LLM_CHEAP_MODEL_") + provider.upper()
    return (cfg.get(env_key) or "").strip() or DEFAULT_MODELS[provider][tier]


def _anthropic(cfg: Config, model: str, system: str, user: str, max_tokens: int,
               json_mode: bool, effort: Optional[str]) -> dict[str, Any]:
    key = cfg.require("ANTHROPIC_API_KEY", "Get a key at console.anthropic.com.")
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user}],
    }
    if system:
        body["system"] = system
    if effort and not model.startswith(_NO_EFFORT_PREFIXES):
        body["output_config"] = {"effort": effort}
    resp = http_util.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json_body=body, timeout=LLM_TIMEOUT, check=True,
    )
    data = resp.json()
    if data.get("stop_reason") == "refusal":
        details = data.get("stop_details") or {}
        raise LlmError(f"Anthropic refused the request (category={details.get('category')}).")
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    usage = data.get("usage") or {}
    return {
        "text": text, "provider": "anthropic", "model": model,
        "usage": {"input_tokens": usage.get("input_tokens", 0),
                  "output_tokens": usage.get("output_tokens", 0)},
        "stop_reason": data.get("stop_reason"),
    }


def _openai(cfg: Config, model: str, system: str, user: str, max_tokens: int,
            json_mode: bool, effort: Optional[str]) -> dict[str, Any]:
    key = cfg.require("OPENAI_API_KEY", "Get a key at platform.openai.com/api-keys.")
    body: dict[str, Any] = {
        "model": model,
        "input": [{"role": "user", "content": user}],
        "max_output_tokens": max_tokens,
    }
    if system:
        body["instructions"] = system
    if json_mode:
        body["text"] = {"format": {"type": "json_object"}}
    resp = http_util.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json_body=body, timeout=LLM_TIMEOUT, check=True,
    )
    data = resp.json()
    text = ""
    for item in data.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content", []) or []:
            if part.get("type") == "output_text":
                text += part.get("text", "")
    usage = data.get("usage") or {}
    return {
        "text": text, "provider": "openai", "model": model,
        "usage": {"input_tokens": usage.get("input_tokens", 0),
                  "output_tokens": usage.get("output_tokens", 0)},
        "stop_reason": data.get("status"),
    }


def _gemini(cfg: Config, model: str, system: str, user: str, max_tokens: int,
            json_mode: bool, effort: Optional[str]) -> dict[str, Any]:
    key = cfg.require("GOOGLE_GEMINI_API_KEY", "Get a key at aistudio.google.com/apikey.")
    generation: dict[str, Any] = {"maxOutputTokens": max_tokens}
    if json_mode:
        generation["responseMimeType"] = "application/json"
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": generation,
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    resp = http_util.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key},
        json_body=body, timeout=LLM_TIMEOUT, check=True,
    )
    data = resp.json()
    candidates = data.get("candidates") or [{}]
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts)
    usage = data.get("usageMetadata") or {}
    return {
        "text": text, "provider": "gemini", "model": model,
        "usage": {"input_tokens": usage.get("promptTokenCount", 0),
                  "output_tokens": usage.get("candidatesTokenCount", 0)},
        "stop_reason": candidates[0].get("finishReason"),
    }


_ADAPTERS = {"anthropic": _anthropic, "openai": _openai, "gemini": _gemini}


def complete(
    cfg: Config,
    system: str,
    user: str,
    *,
    provider: Optional[str] = None,
    tier: str = "quality",
    max_tokens: int = 16000,
    json_mode: bool = False,
    effort: Optional[str] = None,
) -> dict[str, Any]:
    """One prompt in, one completion out. `tier` is "quality" or "cheap".
    `effort` (low|medium|high|xhigh|max) is honored where the model accepts
    it; default is the provider's own default. Raises LlmError on refusal,
    empty output, or transport failure (message sanitized)."""
    name = pick_provider(cfg, provider)
    model = model_for(cfg, name, tier)
    effort = effort or (cfg.get("LLM_EFFORT") or "").strip() or None
    try:
        result = _ADAPTERS[name](cfg, model, system or "", user, max_tokens, json_mode, effort)
    except LlmError:
        raise
    except Exception as exc:
        raise LlmError(f"{name}/{model}: {http_util.sanitize_text(str(exc))}") from None
    if not (result.get("text") or "").strip():
        raise LlmError(f"{name}/{model} returned an empty completion (stop_reason={result.get('stop_reason')}).")
    return result


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json(text: str) -> Any:
    """Parse JSON out of a model reply: tolerates code fences and prose
    around the outermost object/array. Raises LlmError when nothing parses."""
    candidates = [text.strip()]
    fenced = _FENCE_RE.findall(text or "")
    candidates = [f.strip() for f in fenced] + candidates
    for cand in candidates:
        try:
            return json.loads(cand)
        except (json.JSONDecodeError, TypeError):
            pass
        first = min([i for i in (cand.find("{"), cand.find("[")) if i != -1], default=-1)
        if first == -1:
            continue
        closer = "}" if cand[first] == "{" else "]"
        last = cand.rfind(closer)
        if last > first:
            try:
                return json.loads(cand[first:last + 1])
            except json.JSONDecodeError:
                continue
    raise LlmError(f"Model reply was not JSON: {(text or '')[:200]!r}")


def complete_json(cfg: Config, system: str, user: str, **kwargs: Any) -> Any:
    """complete() in JSON mode, parsed. One retry with an explicit
    'JSON only' nudge before giving up."""
    kwargs.setdefault("json_mode", True)
    first = complete(cfg, system, user, **kwargs)
    try:
        return extract_json(first["text"])
    except LlmError:
        second = complete(cfg, system, user + "\n\nReturn ONLY valid JSON. No prose, no code fences.", **kwargs)
        return extract_json(second["text"])
