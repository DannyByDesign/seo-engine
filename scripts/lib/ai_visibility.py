"""AI-visibility / GEO citation-probing client.

Primary approach (sustainable, always-available): call each AI vendor's own
official web-search/grounding tool directly and check whether a target
domain appears among the citations for a set of prompts. This is the DIY
equivalent of what commercial AI-visibility trackers sell.

Measurement honesty (geo-playbook.md §9): LLM answers are stochastic — a
single probe is a coin flip, not a measurement. This module exposes
`probe_all` for one sample; geo-monitor's tracker takes N samples per
prompt×provider and majority-votes. A provider API error is returned as an
explicit error state (`error` + `error_type`) — it must NEVER be conflated
with "not cited" by consumers.

Gemini note: `groundingChunks[].web.uri` is a vertexaisearch.cloud.google.com
redirect URL, not the source — the source domain arrives in `web.title`.
Citation matching therefore checks titles as well as URL hosts.

Never scrape ChatGPT/Perplexity/AI-Overview web UIs directly — that likely
violates each provider's ToS. Use the documented APIs below instead.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlparse

from . import http_util
from .config import INTEGRATION_ENV_VARS, Config

LLM_TIMEOUT = 180.0  # web-search-tool calls routinely exceed ordinary timeouts


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


# ---------- OpenAI ----------

def probe_openai(cfg: Config, prompt: str, model: str = "gpt-4.1") -> dict[str, Any]:
    """Responses API with the web_search tool. Citations arrive as
    annotations of type url_citation on the output text."""
    key = cfg.require("OPENAI_API_KEY", "Get a key at platform.openai.com/api-keys.")
    resp = http_util.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json_body={"model": model, "input": prompt, "tools": [{"type": "web_search"}]},
        timeout=LLM_TIMEOUT, check=True,
    )
    data = resp.json()

    citations = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            for annotation in content.get("annotations", []):
                if annotation.get("type") == "url_citation":
                    citations.append({"url": annotation.get("url"), "title": annotation.get("title")})
    return {"provider": "openai", "prompt": prompt, "citations": _dedupe(citations), "raw": data}


# ---------- Anthropic ----------

def probe_anthropic(
    cfg: Config, prompt: str, model: str = "claude-sonnet-4-5",
    allowed_domains: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Messages API with the web_search tool. Citations arrive inline per
    text block as {url, title, cited_text}. max_tokens is generous — a
    truncated answer loses its trailing citations and reads as a false
    "not cited"."""
    key = cfg.require("ANTHROPIC_API_KEY", "Get a key at console.anthropic.com.")
    tool: dict[str, Any] = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
    if allowed_domains:
        tool["allowed_domains"] = allowed_domains

    resp = http_util.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json_body={
            "model": model, "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [tool],
        },
        timeout=LLM_TIMEOUT, check=True,
    )
    data = resp.json()

    citations = []
    for block in data.get("content", []):
        for citation in block.get("citations", []) or []:
            citations.append({
                "url": citation.get("url"),
                "title": citation.get("title"),
                "cited_text": citation.get("cited_text"),
            })
    return {"provider": "anthropic", "prompt": prompt, "citations": _dedupe(citations), "raw": data}


# ---------- Perplexity ----------

def probe_perplexity(cfg: Config, prompt: str, model: str = "sonar") -> dict[str, Any]:
    key = cfg.require("PERPLEXITY_API_KEY", "Get a key at perplexity.ai/settings/api.")
    resp = http_util.post(
        "https://api.perplexity.ai/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json_body={"model": model, "messages": [{"role": "user", "content": prompt}]},
        timeout=LLM_TIMEOUT, check=True,
    )
    data = resp.json()

    # The deprecated top-level `citations` and the newer `search_results`
    # overlap heavily — dedupe so citation_count isn't double-inflated.
    citations = [{"url": u, "title": None} for u in data.get("citations", [])]
    for result in data.get("search_results", []) or []:
        citations.append({"url": result.get("url"), "title": result.get("title")})
    return {"provider": "perplexity", "prompt": prompt, "citations": _dedupe(citations), "raw": data}


# ---------- Google Gemini (grounding — NOT the same system as AI Overviews/AI Mode) ----------

def probe_gemini(cfg: Config, prompt: str, model: str = "gemini-2.5-flash") -> dict[str, Any]:
    """Gemini API's own Google Search grounding. Distinct from AI Overviews/
    AI Mode in Search itself, which have no public API — this only tells you
    how Gemini-the-API-product grounds answers, a useful proxy but not
    identical to Search's AI surfaces."""
    key = cfg.require("GOOGLE_GEMINI_API_KEY", "Get a key at aistudio.google.com/apikey.")
    resp = http_util.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key},
        json_body={
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
        },
        timeout=LLM_TIMEOUT, check=True,
    )
    data = resp.json()

    citations = []
    grounding = data.get("candidates", [{}])[0].get("groundingMetadata", {})
    for chunk in grounding.get("groundingChunks", []) or []:
        web = chunk.get("web", {})
        # web.uri is a vertexaisearch redirect; web.title carries the domain.
        citations.append({"url": web.get("uri"), "title": web.get("title")})
    return {"provider": "gemini", "prompt": prompt, "citations": _dedupe(citations), "raw": data}


# ---------- Unified probing ----------

PROBERS = {
    "openai": probe_openai,
    "anthropic": probe_anthropic,
    "perplexity": probe_perplexity,
    "gemini": probe_gemini,
}


def _provider_configured(cfg: Config, name: str) -> bool:
    spec = INTEGRATION_ENV_VARS[name]
    env_vars = spec.get("all") or spec.get("any") or []
    return all(cfg.has(v) for v in env_vars)


def probe_all(cfg: Config, prompt: str, target_domain: str) -> dict[str, Any]:
    """Runs every configured provider ONCE for one prompt and reports whether
    the target domain was cited by each. Skips providers with no key.

    A provider failure is an explicit `error` state with `error_type` —
    consumers must treat it as "unknown", never as "not cited" (see
    geo-monitor's diff logic). One sample is one coin flip: callers that
    persist state must aggregate multiple samples (track_ai_visibility.py).
    """
    results = {}
    for name, fn in PROBERS.items():
        if not _provider_configured(cfg, name):
            results[name] = {"configured": False}
            continue
        try:
            outcome = fn(cfg, prompt)
            cited = any(citation_matches(c, target_domain) for c in outcome["citations"])
            results[name] = {
                "configured": True, "cited": cited,
                "citation_count": len(outcome["citations"]),
                "citations": outcome["citations"],
            }
        except Exception as exc:  # noqa: BLE001 — surface per-provider failure, don't abort the sweep
            results[name] = {
                "configured": True,
                "error": http_util.sanitize_text(str(exc)),
                "error_type": getattr(exc, "error_type", "") or type(exc).__name__,
            }
    return {"prompt": prompt, "target_domain": target_domain, "providers": results}


# ---------- Commercial trackers (optional, thin adapters) ----------
# Endpoint shapes are from vendor marketing/docs pages and are NOT
# independently verified — exercise via scripts/dev/smoke.py before relying
# on them. Both are optional supplements to the vendor-API probing above.

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
