"""OpenRouter search-model samples, never consumer-app visibility measurements.

Each model/search configuration has its own history identity. Errors or missing
search evidence are unknown, never an uncited answer. Commercial trackers remain
separate data services.
"""
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlparse

from . import http_util, openrouter
from .config import Config

DEFAULT_MODELS = "openai/gpt-5-mini,anthropic/claude-sonnet-4.6,google/gemini-2.5-flash"
# Pin the search engine so models are compared against the same retrieval surface.
SEARCH_ENGINE = "exa"


def _fold_domain(value: str) -> str:
    value = (value or "").strip().lower()
    if "//" in value:
        value = urlparse(value).netloc
    return value.removeprefix("www.").rstrip("/")


def _domain_matches(url: str, target_domain: str) -> bool:
    """Host match including subdomains (blog.example.com counts for example.com)."""
    host = _fold_domain(url)
    target = _fold_domain(target_domain)
    return bool(host) and (host == target or host.endswith("." + target))


def citation_matches(citation: dict[str, Any], target_domain: str) -> bool:
    """Does a citation refer to the target domain? Checks the URL host, and
    falls back to the title — Gemini's grounding chunks carry the source
    domain in `title` while `uri` is an opaque redirect."""
    url = citation.get("url") or ""
    if url and _domain_matches(url, target_domain):
        return True
    title = _fold_domain(citation.get("title") or "")
    target = _fold_domain(target_domain)
    return bool(title) and (title == target or title.endswith("." + target))


def _dedupe(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique = []
    for c in citations:
        key = (c.get("url") or c.get("title") or "").strip().lower()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        unique.append(c)
    return unique


def probe_names(cfg: Config) -> list[str]:
    models = openrouter.model_list(cfg.get("AI_VISIBILITY_MODELS") or DEFAULT_MODELS)
    return [f"openrouter:{model}:search={SEARCH_ENGINE}" for model in models]


def _provider_configured(cfg: Config, name: str) -> bool:
    return cfg.has("OPENROUTER_API_KEY") and name in probe_names(cfg)


def probe(cfg: Config, prompt: str, name: str) -> dict[str, Any]:
    if name not in probe_names(cfg):
        raise openrouter.OpenRouterError("Unknown OpenRouter probe identity")
    model = name.removeprefix("openrouter:").removesuffix(f":search={SEARCH_ENGINE}")
    data = openrouter.request(cfg, "/chat/completions", {
        "model": model, "messages": [
            {"role": "system", "content": "Search the web before answering. Cite the sources you use."},
            {"role": "user", "content": prompt}],
        "max_tokens": 4096, "max_tool_calls": 3,
        "tools": [{"type": "openrouter:web_search", "parameters": {
            "engine": SEARCH_ENGINE, "max_results": 5, "max_total_results": 10, "max_uses": 3}}],
    }, timeout=180)
    msg = openrouter.message(data)
    citations = []
    for annotation in msg.get("annotations") or []:
        if annotation.get("type") == "url_citation":
            citation = annotation.get("url_citation") or annotation
            if citation.get("url"):
                citations.append({"url": citation["url"], "title": citation.get("title")})
    search_count = ((data.get("usage") or {}).get("server_tool_use") or {}).get("web_search_requests")
    if search_count == 0 or (not search_count and not citations):
        raise openrouter.OpenRouterError("No web-search evidence returned; citation visibility is unknown")
    return {"provider": name, "model": data.get("model") or model, "gateway": "openrouter",
            "search_engine": SEARCH_ENGINE, "measurement_kind": "openrouter_search_api_sample",
            "prompt": prompt, "citations": _dedupe(citations), "raw": data}


def probe_all(cfg: Config, prompt: str, target_domain: str) -> dict[str, Any]:
    results = {}
    for name in probe_names(cfg):
        if not _provider_configured(cfg, name):
            results[name] = {"configured": False}
            continue
        try:
            outcome = probe(cfg, prompt, name)
            results[name] = {
                "configured": True,
                "cited": any(citation_matches(c, target_domain) for c in outcome["citations"]),
                "citation_count": len(outcome["citations"]), "citations": outcome["citations"],
                "model": outcome["model"], "search_engine": SEARCH_ENGINE,
            }
        except Exception as exc:
            results[name] = {"configured": True, "error": http_util.sanitize_text(str(exc)),
                             "error_type": getattr(exc, "error_type", "") or type(exc).__name__}
    return {"prompt": prompt, "target_domain": target_domain, "providers": results}


def answer_text(provider: str, raw: dict[str, Any]) -> str:
    return openrouter.message(raw)["content"]


def profound_visibility(cfg: Config, category: Optional[str] = None) -> dict[str, Any]:
    key = cfg.require("PROFOUND_API_KEY", "Sign up at tryprofound.com; API is in beta.")
    resp = http_util.get(
        "https://api.tryprofound.com/v1/visibility",
        headers={"Authorization": f"Bearer {key}"},
        params={"category": category} if category else None,
        check=True,
    )
    return resp.json()


def otterly_visibility(cfg: Config, project_id: str) -> dict[str, Any]:
    key = cfg.require("OTTERLY_API_KEY", "Sign up at otterly.ai; API requires Standard tier or above.")
    resp = http_util.get(
        f"https://data.otterly.ai/api/v1/projects/{project_id}/visibility",
        headers={"Authorization": f"Bearer {key}"},
        check=True,
    )
    return resp.json()
