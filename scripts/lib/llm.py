"""Scripted text generation through one OpenRouter account.

Host-agent writing still works without an API key. Model slugs are configurable;
no direct-vendor credentials or automatic cross-model fallback are used.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from . import openrouter
from .config import Config

LLM_TIMEOUT = 300.0
DEFAULT_MODELS = {"quality": "anthropic/claude-sonnet-4.6", "cheap": "google/gemini-2.5-flash"}
LlmError = openrouter.OpenRouterError


def configured_providers(cfg: Config) -> list[str]:
    return ["openrouter"] if cfg.has("OPENROUTER_API_KEY") else []


def pick_provider(cfg: Config, prefer: Optional[str] = None) -> str:
    if prefer and prefer != "openrouter":
        raise LlmError("Scripted models now use OpenRouter. Choose a vendor/model slug with LLM_MODEL.")
    if not configured_providers(cfg):
        raise LlmError("Set OPENROUTER_API_KEY in the website's .env; see .env.example.")
    return "openrouter"


def model_for(cfg: Config, provider: str = "openrouter", tier: str = "quality") -> str:
    if provider != "openrouter":
        raise LlmError("Use OpenRouter model slugs in LLM_MODEL / LLM_CHEAP_MODEL.")
    env_key = "LLM_MODEL" if tier == "quality" else "LLM_CHEAP_MODEL"
    return (cfg.get(env_key) or "").strip() or DEFAULT_MODELS[tier]


def complete(cfg: Config, system: str, user: str, *, provider: Optional[str] = None,
             model: Optional[str] = None, tier: str = "quality", max_tokens: int = 16000,
             json_mode: bool = False, effort: Optional[str] = None) -> dict[str, Any]:
    name = pick_provider(cfg, provider)
    selected = model or model_for(cfg, name, tier)
    messages = ([{"role": "system", "content": system}] if system else [])
    messages.append({"role": "user", "content": user})
    body: dict[str, Any] = {"model": selected, "messages": messages, "max_tokens": max_tokens,
                            "provider": {"require_parameters": True}}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    effort = effort or (cfg.get("LLM_EFFORT") or "").strip()
    if effort:
        body["reasoning"] = {"effort": effort}
    data = openrouter.request(cfg, "/chat/completions", body, timeout=LLM_TIMEOUT)
    msg = openrouter.message(data)
    usage = data.get("usage") or {}
    return {"text": msg["content"], "provider": name, "model": data.get("model") or selected,
            "usage": {"input_tokens": usage.get("prompt_tokens", 0),
                      "output_tokens": usage.get("completion_tokens", 0), "cost": usage.get("cost")},
            "stop_reason": data["choices"][0].get("finish_reason")}


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
