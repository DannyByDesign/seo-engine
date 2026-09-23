"""Image generation through OpenRouter's dedicated Image API."""
from __future__ import annotations

import base64
from typing import Any, Optional

from . import openrouter
from .config import Config

IMAGE_TIMEOUT = 300.0
DEFAULT_IMAGE_MODEL = "google/gemini-2.5-flash-image"
ImageError = openrouter.OpenRouterError


def configured_image_providers(cfg: Config) -> list[str]:
    return ["openrouter"] if cfg.has("OPENROUTER_API_KEY") else []


def pick_image_provider(cfg: Config, prefer: Optional[str] = None) -> str:
    if prefer and prefer != "openrouter":
        raise ImageError("Use --provider openrouter and an IMAGE_MODEL vendor/model slug (or explicit svg).")
    if not configured_image_providers(cfg):
        raise ImageError("Set OPENROUTER_API_KEY for image generation (or explicitly select SVG).")
    return "openrouter"


def generate_image(cfg: Config, prompt: str, *, provider: Optional[str] = None, model: Optional[str] = None,
                   aspect_ratio: str = "16:9") -> dict[str, Any]:
    name = pick_image_provider(cfg, provider)
    model = model or (cfg.get("IMAGE_MODEL") or "").strip() or DEFAULT_IMAGE_MODEL
    data = openrouter.request(cfg, "/images", {"model": model, "prompt": prompt, "n": 1,
                              "aspect_ratio": aspect_ratio}, timeout=IMAGE_TIMEOUT)
    items = data.get("data") or []
    if not items or not items[0].get("b64_json"):
        raise ImageError("OpenRouter returned no image data")
    try:
        payload = base64.b64decode(items[0]["b64_json"], validate=True)
        if payload.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif payload.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
            mime = "image/webp"
        else:
            raise ValueError("unsupported raster format")
    except Exception:
        raise ImageError("OpenRouter returned invalid or unsupported raster image data") from None
    return {"bytes": payload, "mime": mime, "provider": name, "model": model,
            "usage": data.get("usage") or {}}
