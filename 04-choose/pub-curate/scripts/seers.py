"""pub-curate: Seers — event-driven topic sources ("signal in, story out").

A seer points a provider at a source and turns what it detects into a
headline suggestion (mode `suggest`) or a draft with a brief (mode `auto`).
Providers (the vendor's six, plus the social one this repo adds):
  news_trend         web news for a query in the last day/week (Firecrawl search,
                     else SociaVault Google search)
  regulation_change  news_trend with a regulatory query template
  social_trend       Reddit / X / TikTok / YouTube conversations for a query (SociaVault)
  github_release     new releases of a public repo (GITHUB_TOKEN optional)
  github_pr          merged pull requests of a repo in the window
  spec_change        a URL whose normalized text changed since the last poll (hash + diff)
  notion_activity    pages edited in a Notion workspace since the last poll (NOTION_TOKEN)

Configuration lives in <publication>/seers.yml:
  - name: "AI ad platform news"
    provider: news_trend
    enabled: true
    mode: suggest            # suggest | auto
    poll_interval_minutes: 720
    section: ai-search       # pillar slug drafts/suggestions land in
    config: {query: "ChatGPT ads OR Perplexity ads", recency: week, min_results: 2}

State (cursors, seen ids/hashes) lives in .seo-engine/state/pub-seers-<slug>.json
so a signal is produced once. --propose drafts seers from strategy.yml (LLM,
or deterministic: one news_trend per priority topic + one social_trend);
--apply writes them.

Usage:
    python3 seers.py --publication llm-billboard --propose            # proposal only
    python3 seers.py --publication llm-billboard --propose --apply
    python3 seers.py --publication llm-billboard                      # poll every due seer
    python3 seers.py --publication llm-billboard --seer "AI ad platform news" --force
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info < (3, 9):
    sys.exit("seo-engine requires Python 3.9+ (found %d.%d)" % sys.version_info[:2])


def _find_engine_root(start: Path) -> Path:
    import os

    env = os.environ.get("SEO_ENGINE_ROOT")
    if env and (Path(env) / "scripts" / "lib" / "config.py").is_file():
        return Path(env)
    for candidate in [start, *start.parents]:
        if (candidate / "scripts" / "lib" / "config.py").is_file():
            return candidate
    raise SystemExit(
        "Could not locate seo-engine root (scripts/lib/config.py). If skills were "
        "copied (not symlinked), set SEO_ENGINE_ROOT=/path/to/seo-engine."
    )


sys.path.insert(0, str(_find_engine_root(Path(__file__).resolve())))
from scripts.lib import config as config_module

import argparse
import difflib
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from scripts.lib import firecrawl, http_util, llm, publication, pubstate, sociavault
from scripts.lib.config import Config

PROVIDERS = ("news_trend", "regulation_change", "social_trend", "github_release", "github_pr", "spec_change", "notion_activity")
DEFAULT_INTERVAL = {"news_trend": 720, "regulation_change": 1440, "social_trend": 720, "github_release": 360,
                    "github_pr": 360, "spec_change": 1440, "notion_activity": 120}
RECENCY_TBS = {"day": "qdr:d", "week": "qdr:w", "month": "qdr:m"}
PROPOSE_SYSTEM = (
    "You propose automated monitors ('seers') for an independent trade publication. Given its strategy, propose 3-6 "
    "seers from the providers news_trend (config.query), regulation_change (config.query naming the regulator or law), "
    "social_trend (config.query), spec_change (config.url of a public spec/changelog/docs page), github_release "
    "(config.repo owner/name of a public repo). Each: name, provider, section (one of the given pillar slugs), config, "
    "and why. Return ONLY JSON: [{name, provider, section, config, why}]."
)


def _event(seer: dict[str, Any], key: str, title: str, url: str, summary: str, **extra: Any) -> dict[str, Any]:
    return {"seer": seer["name"], "provider": seer["provider"], "dedupe_key": key, "title": title, "url": url,
            "summary": summary, "detected_at": pubstate.now_iso(), **extra}


def news_trend(cfg: Config, seer: dict[str, Any], cursor: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    conf = seer.get("config") or {}
    query = str(conf.get("query") or "")
    if seer["provider"] == "regulation_change":
        query = query or f"{conf.get('regulator', 'regulator')} {conf.get('topic', '')} rule OR guidance OR enforcement"
    recency = str(conf.get("recency") or "week")
    results: list[dict[str, Any]] = []
    notes: list[str] = []
    if cfg.integration_available("firecrawl"):
        results = firecrawl.search(cfg, query, limit=int(conf.get("limit") or 10), tbs=RECENCY_TBS.get(recency))
    elif cfg.integration_available("sociavault"):
        payload = sociavault.google_search(cfg, query, date_posted={"day": "last-day", "week": "last-week", "month": "last-month"}.get(recency))
        results = [sociavault.normalize("google", r) for r in sociavault._items(payload, "results", "items")]
    else:
        return [], ["neither FIRECRAWL_API_KEY nor SOCIAVAULT_API_KEY set — news_trend cannot search"]
    events = []
    for r in results:
        url = r.get("url")
        if not url:
            continue
        key = hashlib.sha1(url.encode()).hexdigest()[:16]
        events.append(_event(seer, key, str(r.get("title") or url), url, str(r.get("description") or r.get("text") or "")[:300]))
    return events, notes


def social_trend(cfg: Config, seer: dict[str, Any], cursor: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    conf = seer.get("config") or {}
    if not cfg.integration_available("sociavault"):
        return [], ["SOCIAVAULT_API_KEY not set — social_trend skipped"]
    result = sociavault.search_conversations(cfg, str(conf.get("query") or ""), recency=str(conf.get("recency") or "week"),
                                             platforms=tuple(conf.get("platforms") or ("reddit", "twitter", "tiktok", "youtube")), limit=int(conf.get("limit") or 15))
    min_engagement = float(conf.get("min_engagement") or 0)
    events = []
    for p in result["posts"]:
        engagement = float(p.get("score") or 0) + 2 * float(p.get("comments") or 0)
        if engagement < min_engagement or not p.get("url"):
            continue
        key = hashlib.sha1(str(p["url"]).encode()).hexdigest()[:16]
        text = (p.get("title") or p.get("text") or "")[:200]
        events.append(_event(seer, key, f"[{p['platform']}] {text}", p["url"], (p.get("text") or "")[:300],
                             platform=p["platform"], engagement=engagement, author=p.get("author")))
    notes = [f"{k}: {v}" for k, v in result["errors"].items()]
    return events, notes


def _github(cfg: Config, path: str) -> Any:
    headers = {"Accept": "application/vnd.github+json"}
    if cfg.has("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {cfg.require('GITHUB_TOKEN', 'optional')}"
    resp = http_util.get(f"https://api.github.com{path}", headers=headers, timeout=30.0, check=True)
    return resp.json()


def github_release(cfg: Config, seer: dict[str, Any], cursor: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    repo = str((seer.get("config") or {}).get("repo") or "")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        return [], [f"github_release needs config.repo as owner/name (got {repo!r})"]
    events = []
    for rel in _github(cfg, f"/repos/{repo}/releases?per_page=10") or []:
        if rel.get("draft"):
            continue
        events.append(_event(seer, f"rel-{rel.get('id')}", f"{repo} {rel.get('tag_name') or rel.get('name')}", rel.get("html_url", ""),
                             (rel.get("body") or "")[:400], published_at=rel.get("published_at")))
    return events, []


def github_pr(cfg: Config, seer: dict[str, Any], cursor: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    conf = seer.get("config") or {}
    repo = str(conf.get("repo") or "")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        return [], [f"github_pr needs config.repo as owner/name (got {repo!r})"]
    since = datetime.now(timezone.utc) - timedelta(days=int(conf.get("days") or 7))
    events = []
    for pr in _github(cfg, f"/repos/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page=30") or []:
        merged = publication.parse_iso(pr.get("merged_at"))
        if not merged or merged < since:
            continue
        events.append(_event(seer, f"pr-{pr.get('number')}", f"{repo}#{pr.get('number')}: {pr.get('title')}", pr.get("html_url", ""),
                             (pr.get("body") or "")[:400], merged_at=pr.get("merged_at")))
    return events, []


def spec_change(cfg: Config, seer: dict[str, Any], cursor: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    from bs4 import BeautifulSoup

    conf = seer.get("config") or {}
    urls = conf.get("urls") or ([conf["url"]] if conf.get("url") else [])
    if not urls:
        return [], ["spec_change needs config.url or config.urls"]
    events, notes = [], []
    hashes = cursor.setdefault("hashes", {})
    for url in urls:
        try:
            resp = http_util.get(url, timeout=30.0, check=True)
        except Exception as exc:
            notes.append(f"{url}: {http_util.sanitize_text(str(exc))[:120]}")
            continue
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        digest = hashlib.sha256(text.encode()).hexdigest()
        previous = hashes.get(url)
        if previous and previous.get("hash") != digest:
            old_lines = (previous.get("excerpt") or "").split(". ")
            new_lines = text.split(". ")
            diff = [l for l in difflib.unified_diff(old_lines, new_lines, lineterm="", n=0) if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))]
            events.append(_event(seer, f"spec-{digest[:12]}", f"Change detected: {url}", url, "\n".join(diff[:40])[:1500], changed_lines=len(diff)))
        hashes[url] = {"hash": digest, "checked_at": pubstate.now_iso(), "excerpt": text[:20000]}
    return events, notes


def notion_activity(cfg: Config, seer: dict[str, Any], cursor: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    if not cfg.has("NOTION_TOKEN"):
        return [], ["NOTION_TOKEN not set — notion_activity skipped"]
    conf = seer.get("config") or {}
    since = cursor.get("since") or (datetime.now(timezone.utc) - timedelta(days=int(conf.get("days") or 7))).isoformat()
    body = {"sort": {"direction": "descending", "timestamp": "last_edited_time"}, "page_size": 25}
    if conf.get("query"):
        body["query"] = str(conf["query"])
    resp = http_util.post("https://api.notion.com/v1/search", headers={"Authorization": f"Bearer {cfg.require('NOTION_TOKEN', 'optional')}",
                                                                      "Notion-Version": "2022-06-28"}, json_body=body, timeout=30.0, check=True)
    events = []
    for page in resp.json().get("results", []):
        edited = page.get("last_edited_time", "")
        if edited <= since:
            continue
        title = ""
        for prop in (page.get("properties") or {}).values():
            if prop.get("type") == "title":
                title = "".join(t.get("plain_text", "") for t in prop.get("title", []))
        events.append(_event(seer, f"notion-{page.get('id')}-{edited[:16]}", title or page.get("id", ""), page.get("url", ""), f"edited {edited}"))
    cursor["since"] = pubstate.now_iso()
    return events, []


HANDLERS: dict[str, Callable[..., tuple[list[dict[str, Any]], list[str]]]] = {
    "news_trend": news_trend, "regulation_change": news_trend, "social_trend": social_trend,
    "github_release": github_release, "github_pr": github_pr, "spec_change": spec_change, "notion_activity": notion_activity,
}


def headline_for(cfg: Config, event: dict[str, Any], strategy: dict[str, Any]) -> tuple[str, str]:
    if not llm.configured_providers(cfg):
        return event["title"][:110], f"Detected by seer {event['seer']}."
    try:
        data = llm.complete_json(cfg, "Turn a detected signal into one article headline (6-11 words, specific noun phrase, no clickbait) for "
                                      "an independent trade publication, plus one sentence on why it matters to the publication's readers. "
                                      "Return ONLY JSON: {\"headline\": str, \"why\": str}.",
                                 f"Publication direction: {strategy.get('direction')}\nSignal: {event['title']}\nURL: {event['url']}\nSummary: {event['summary']}",
                                 tier="cheap", max_tokens=400)
        return str(data.get("headline") or event["title"])[:110], str(data.get("why") or "")
    except llm.LlmError:
        return event["title"][:110], f"Detected by seer {event['seer']}."


def produce(cfg: Config, root: Path, pub: publication.Publication, strategy: dict[str, Any], seer: dict[str, Any],
            events: list[dict[str, Any]], suggestions: dict[str, Any]) -> list[dict[str, Any]]:
    produced = []
    for ev in events:
        headline, why = headline_for(cfg, ev, strategy)
        item = {"id": f"sr-{hashlib.sha1(ev['dedupe_key'].encode()).hexdigest()[:8]}", "status": "suggested", "created_at": pubstate.now_iso(),
                "headline": headline, "why": why, "source_type": f"seer:{seer['provider']}", "seer": seer["name"], "pillar": seer.get("section"),
                "event": {"title": ev["title"], "url": ev["url"], "summary": ev["summary"][:500]}, "score": None, "signal_breakdown": None}
        suggestions.setdefault("items", []).append(item)
        if seer.get("mode") == "auto":
            slug = publication.slugify(headline, max_len=70)
            path = root / "drafts" / f"{slug}.md"
            if not path.exists():
                section = next((s["name"] for s in pub.sections if s["slug"] == seer.get("section")), pub.sections[0]["name"] if pub.sections else "Features")
                publication.write_post(path, {"title": headline, "slug": slug, "status": "draft", "section": section,
                                              "brief": why, "source": {"seer": seer["name"], "provider": seer["provider"], "url": ev["url"]},
                                              "source_urls": [ev["url"]], "created_at": pubstate.now_iso()},
                                       "")
                item["draft"] = str(path)
        produced.append(item)
    return produced


def propose(cfg: Config, pub: publication.Publication, strategy: dict[str, Any]) -> list[dict[str, Any]]:
    pillars = [s["slug"] for s in pub.sections] or ["features"]
    if llm.configured_providers(cfg):
        try:
            data = llm.complete_json(cfg, PROPOSE_SYSTEM, f"Strategy: {json.dumps({k: strategy.get(k) for k in ('direction', 'priority_topics', 'client', 'landings')}, ensure_ascii=False)}\n"
                                                          f"Pillar slugs: {pillars}", tier="cheap", max_tokens=3000)
            out = []
            for s in data if isinstance(data, list) else data.get("seers", []):
                if isinstance(s, dict) and s.get("provider") in PROVIDERS and s.get("name"):
                    out.append({"name": str(s["name"]), "provider": s["provider"], "enabled": True, "mode": "suggest",
                                "poll_interval_minutes": DEFAULT_INTERVAL[s["provider"]], "section": s.get("section") if s.get("section") in pillars else pillars[0],
                                "config": s.get("config") or {}, "why": str(s.get("why") or "")})
            if out:
                return out
        except llm.LlmError:
            pass
    out = []
    for topic in strategy.get("priority_topics", [])[:4]:
        out.append({"name": f"News: {topic}", "provider": "news_trend", "enabled": True, "mode": "suggest", "poll_interval_minutes": 720,
                    "section": pillars[0], "config": {"query": topic, "recency": "week"}, "why": "priority topic"})
    if strategy.get("priority_topics"):
        out.append({"name": "Conversations: category", "provider": "social_trend", "enabled": True, "mode": "suggest", "poll_interval_minutes": 720,
                    "section": pillars[0], "config": {"query": strategy["priority_topics"][0], "recency": "week", "min_engagement": 20}, "why": "where buyers talk"})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Run, propose or apply a publication's seers.")
    parser.add_argument("--publication", help="Publication slug")
    parser.add_argument("--seer", help="Run only this seer (by name)")
    parser.add_argument("--force", action="store_true", help="Ignore poll intervals")
    parser.add_argument("--propose", action="store_true", help="Propose seers from strategy.yml")
    parser.add_argument("--apply", action="store_true", help="Write proposed seers into seers.yml (idempotent by name)")
    parser.add_argument("--dry-run", action="store_true", help="Detect events but write no suggestions/drafts/state")
    parser.add_argument("--publications-dir", help="Override the publications directory")
    args = parser.parse_args()

    cfg = config_module.load()
    if args.publications_dir:
        cfg.site["publications_dir"] = args.publications_dir
    root = publication.find_publication(cfg, args.publication)
    pub = publication.load_publication(root)
    strategy = pubstate.load_strategy(root)
    seers_cfg = pubstate.load_yaml(pubstate.seers_path(root), {"seers": []})
    seers = [s for s in seers_cfg.get("seers", []) if isinstance(s, dict)]
    result: dict[str, Any] = {"checked": True, "publication": root.name, "seers_file": str(pubstate.seers_path(root)), "notes": []}

    if args.propose:
        proposals = propose(cfg, pub, strategy)
        result["proposals"] = proposals
        if args.apply:
            names = {s["name"] for s in seers}
            seers += [p for p in proposals if p["name"] not in names]
            pubstate.save_yaml(pubstate.seers_path(root), {"seers": seers})
            result["applied"] = len([p for p in proposals if p["name"] not in names])
        else:
            result["notes"].append("proposal only — rerun with --apply to write seers.yml")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if not seers:
        result.update({"checked": False, "error": "no seers configured — run --propose --apply or edit seers.yml"})
        print(json.dumps(result, indent=2))
        return 1
    state = pubstate.load_json(pubstate.state_path(cfg, "seers", root.name), {"seers": {}})
    suggestions = pubstate.load_json(pubstate.state_path(cfg, "suggestions", root.name), {"publication": root.name, "items": []})
    runs = []
    for seer in seers:
        if args.seer and seer.get("name") != args.seer:
            continue
        if not seer.get("enabled", True):
            continue
        if seer.get("provider") not in HANDLERS:
            runs.append({"seer": seer.get("name"), "skipped": f"unknown provider {seer.get('provider')}"})
            continue
        st = state["seers"].setdefault(seer["name"], {"seen": [], "cursor": {}, "last_polled_at": None})
        last = publication.parse_iso(st.get("last_polled_at"))
        interval = timedelta(minutes=int(seer.get("poll_interval_minutes") or DEFAULT_INTERVAL[seer["provider"]]))
        if last and not args.force and datetime.now(timezone.utc) - last < interval:
            runs.append({"seer": seer["name"], "skipped": f"polled {last.isoformat()}, interval {interval}"})
            continue
        try:
            events, notes = HANDLERS[seer["provider"]](cfg, seer, st["cursor"])
        except Exception as exc:
            runs.append({"seer": seer["name"], "error": http_util.sanitize_text(str(exc))[:200]})
            continue
        seen = set(st.get("seen", []))
        fresh = [e for e in events if e["dedupe_key"] not in seen]
        produced = [] if args.dry_run else produce(cfg, root, pub, strategy, seer, fresh, suggestions)
        if not args.dry_run:
            st["seen"] = (list(seen) + [e["dedupe_key"] for e in fresh])[-500:]
            st["last_polled_at"] = pubstate.now_iso()
        runs.append({"seer": seer["name"], "provider": seer["provider"], "events_detected": len(events), "new_events": len(fresh),
                     "produced": len(produced), "mode": seer.get("mode", "suggest"), "notes": notes,
                     "events": [{"title": e["title"], "url": e["url"]} for e in fresh[:10]]})
    if not args.dry_run:
        pubstate.save_json(pubstate.state_path(cfg, "seers", root.name), state)
        pubstate.save_json(pubstate.state_path(cfg, "suggestions", root.name), suggestions)
    result["runs"] = runs
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
