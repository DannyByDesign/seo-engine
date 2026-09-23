"""Single authenticated gateway for scripted text, image, and search-model calls."""
from __future__ import annotations

from typing import Any

from . import http_util
from .config import Config

BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterError(RuntimeError):
    """A sanitized transport error or unusable model response."""


def request(cfg: Config, endpoint: str, body: dict[str, Any], *, timeout: float = 300) -> dict[str, Any]:
    key = cfg.require("OPENROUTER_API_KEY", "Get one key at openrouter.ai/settings/keys; add credits there.")
    try:
        response = http_util.post(
            BASE_URL + endpoint, headers={"Authorization": f"Bearer {key}"},
            json_body=body, timeout=timeout, check=True,
        )
        data = response.json()
    except Exception as exc:
        raise OpenRouterError(http_util.sanitize_text(str(exc).replace(key, "[REDACTED]"))) from None
    if not isinstance(data, dict):
        raise OpenRouterError("OpenRouter returned a non-object response")
    if data.get("error"):
        # Upstream messages can echo prompts or credentials. Do not surface them.
        raise OpenRouterError("OpenRouter returned an API error; check model access, credits and account activity")
    return data


def message(data: dict[str, Any]) -> dict[str, Any]:
    choices = data.get("choices") or []
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise OpenRouterError("OpenRouter returned no completion")
    choice = choices[0]
    msg = choice.get("message") or {}
    if not isinstance(msg, dict):
        raise OpenRouterError("OpenRouter returned an invalid message")
    reason = choice.get("finish_reason")
    if choice.get("error") or msg.get("refusal") or reason in ("length", "content_filter", "error", "tool_calls"):
        raise OpenRouterError("OpenRouter completion was refused, incomplete, or failed")
    if not isinstance(msg.get("content"), str) or not msg["content"].strip():
        raise OpenRouterError("OpenRouter returned an empty text completion")
    return msg


def model_list(value: str) -> list[str]:
    """Keep configured model order, removing empty and duplicate entries."""
    return list(dict.fromkeys(m.strip() for m in value.split(",") if m.strip()))
