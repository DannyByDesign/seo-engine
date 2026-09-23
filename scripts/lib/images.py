"""BYOK image generation for article covers — OpenAI Images and Google Gemini
image models behind one call, through the shared HTTP layer (see llm.py for
why raw HTTP). Returns bytes + mime; callers decide the file name.

Provider pick: `IMAGE_PROVIDER` env (openai | gemini) when its key is set,
else OpenAI, else Gemini. Model ids are env-overridable
(`IMAGE_MODEL_OPENAI`, `IMAGE_MODEL_GEMINI`) because image model ids drift;
`scripts/dev/smoke.py` is where to confirm them.
"""

from __future__ import annotations

import base64
from typing import Any, Optional

from . import http_util
from .config import Config

IMAGE_TIMEOUT = 240.0
DEFAULT_IMAGE_MODELS = {"openai": "gpt-image-1", "gemini": "gemini-2.5-flash-image"}


class ImageError(RuntimeError):
    """Image generation failed or no provider is configured (message sanitized)."""


def configured_image_providers(cfg: Config) -> list[str]:
    out = []
    if cfg.has("OPENAI_API_KEY"):
        out.append("openai")
    if cfg.has("GOOGLE_GEMINI_API_KEY"):
        out.append("gemini")
    return out


def pick_image_provider(cfg: Config, prefer: Optional[str] = None) -> str:
    available = configured_image_providers(cfg)
    wanted = (prefer or cfg.get("IMAGE_PROVIDER") or "").strip().lower()
    if wanted and wanted in available:
        return wanted
    if wanted and wanted not in ("openai", "gemini"):
        raise ImageError(f"Unknown image provider {wanted!r}; choose openai or gemini")
    if available:
        return available[0]
    raise ImageError("No image provider configured — set OPENAI_API_KEY or GOOGLE_GEMINI_API_KEY (or use the SVG fallback).")


def _openai(cfg: Config, prompt: str, model: str, size: str) -> tuple[bytes, str]:
    key = cfg.require("OPENAI_API_KEY", "Get a key at platform.openai.com/api-keys.")
    resp = http_util.post(
        "https://api.openai.com/v1/images/generations",
        headers={"Authorization": f"Bearer {key}"},
        json_body={"model": model, "prompt": prompt, "n": 1, "size": size, "output_format": "jpeg", "quality": "medium"},
        timeout=IMAGE_TIMEOUT, check=True,
    )
    data = resp.json()
    items = data.get("data") or []
    if not items or not items[0].get("b64_json"):
        raise ImageError("OpenAI returned no image data")
    return base64.b64decode(items[0]["b64_json"]), "image/jpeg"


def _gemini(cfg: Config, prompt: str, model: str, size: str) -> tuple[bytes, str]:
    key = cfg.require("GOOGLE_GEMINI_API_KEY", "Get a key at aistudio.google.com/apikey.")
    resp = http_util.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key},
        json_body={"contents": [{"parts": [{"text": prompt + " Aspect ratio 16:9."}]}],
                   "generationConfig": {"responseModalities": ["IMAGE"]}},
        timeout=IMAGE_TIMEOUT, check=True,
    )
    data = resp.json()
    for cand in data.get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"]), str(inline.get("mimeType") or inline.get("mime_type") or "image/png")
    raise ImageError("Gemini returned no inline image data")


def generate_image(cfg: Config, prompt: str, *, provider: Optional[str] = None, model: Optional[str] = None,
                   size: str = "1536x1024") -> dict[str, Any]:
    """{bytes, mime, provider, model}. Raises ImageError (sanitized)."""
    name = pick_image_provider(cfg, provider)
    model = model or (cfg.get(f"IMAGE_MODEL_{name.upper()}") or "").strip() or DEFAULT_IMAGE_MODELS[name]
    try:
        payload, mime = (_openai if name == "openai" else _gemini)(cfg, prompt, model, size)
    except ImageError:
        raise
    except Exception as exc:
        raise ImageError(f"{name}/{model}: {http_util.sanitize_text(str(exc))}") from None
    return {"bytes": payload, "mime": mime, "provider": name, "model": model}
