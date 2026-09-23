"""pub-strategy: scrape tracked competitors' content inventories into
per-domain topic files, with an inferred keyword and priority per topic.

The vendor's "Watch Competitor Blogs": sitemap → article URLs → title,
description, publish date → LLM-inferred primary keyword + priority (high |
medium | low) scored against the client's description → optional DataForSEO
monthly volume / difficulty. Output feeds build_topic_map.py (spokes from
gaps) and score_suggestions.py (the competitor signal) and positioning.py
(--suggest reads the titles).

Freshness: a domain scraped within --max-age-hours (default 24) is skipped
unless --force, so repeated pipeline runs never re-crawl a competitor. All
fetches go through the shared HTTP layer with a polite per-host interval and
the on-disk cache; robots.txt is honored with RFC 9309 semantics.

Usage:
    python3 scrape_competitors.py --publication llm-billboard              # every competitor in strategy.yml
    python3 scrape_competitors.py --publication llm-billboard --domain adweek.com --max-pages 30
    python3 scrape_competitors.py --publication llm-billboard --fresh-posts   # newest posts across competitors
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
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from scripts.lib import dataforseo, http_util, llm, publication, pubstate, robots, sitemaps
from scripts.lib.config import Config

ARTICLE_HINT = re.compile(r"/(blog|posts?|articles?|content|guides?|resources?|insights?|news|learn|stories|research)(/|$)", re.I)
EXCLUDE = re.compile(r"/(tag|tags|category|categories|author|authors|page|search|feed|wp-json|cart|login|privacy|terms)(/|$)|\.(png|jpe?g|gif|svg|webp|pdf|xml|css|js)$", re.I)
KEYWORD_SYSTEM = (
    "You infer the primary search keyword and the client-relevance priority of competitor articles. For each numbered "
    "title, return the 2-5 word keyword a searcher would type to find it, and priority 'high' (squarely in the client's "
    "category and buyer intent), 'medium' (adjacent), or 'low' (off-category or generic). Return ONLY JSON: "
    "[{\"i\": number, \"keyword\": string, \"priority\": \"high\"|\"medium\"|\"low\"}]."
)


def article_urls(site_url: str, max_pages: int) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    policy = robots.fetch(site_url)
    inv = sitemaps.fetch_url_set(site_url, policy, max_urls=5000)
    urls = [u for u in inv.get("page_urls", []) if not EXCLUDE.search(urlparse(u).path)]
    host = urlparse(site_url).netloc.lower().removeprefix("www.")
    urls = [u for u in urls if urlparse(u).netloc.lower().removeprefix("www.") == host and urlparse(u).path.strip("/")]
    hinted = [u for u in urls if ARTICLE_HINT.search(urlparse(u).path)]
    if len(hinted) >= 5:
        urls = hinted
    else:
        notes.append("no /blog|/posts|/articles path pattern found — using every non-excluded sitemap URL")
    if not inv.get("found"):
        notes.append("no sitemap found; nothing to scrape (the crawler is not used for competitors on purpose: politeness)")
    urls = [u for u in urls if policy.allowed(http_util.USER_AGENT, u)]
    return urls[:max_pages], notes


def read_page(cfg: Config, url: str) -> Optional[dict[str, Any]]:
    try:
        resp = http_util.get(url, timeout=25.0, min_interval=1.0, cache_dir=cfg.state_dir / "http-cache", cache_ttl=7 * 86400)
    except Exception:
        return None
    if resp.status_code != 200 or "html" not in (resp.headers.get("content-type") or ""):
        return None
    soup = BeautifulSoup(resp.text, "lxml")
    title = ""
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        title = str(og["content"]).strip()
    elif soup.title and soup.title.string:
        title = soup.title.string.strip()
    if not title:
        return None
    desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    published = ""
    pt = soup.find("meta", attrs={"property": "article:published_time"})
    if pt and pt.get("content"):
        published = str(pt["content"])
    else:
        m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', resp.text)
        published = m.group(1) if m else ""
    return {"url": url, "title": re.sub(r"\s+", " ", title)[:200], "description": (str(desc.get("content") or "")[:300] if desc else ""),
            "published_at": published}


def infer_keywords(cfg: Config, client_description: str, topics: list[dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    pending = [t for t in topics if not t.get("inferred_keyword")]
    if not pending:
        return notes
    if llm.configured_providers(cfg):
        for start in range(0, len(pending), 40):
            batch = pending[start:start + 40]
            listing = "\n".join(f"{i}. {t['title']}" for i, t in enumerate(batch))
            try:
                data = llm.complete_json(cfg, KEYWORD_SYSTEM, f"Client: {client_description or '(unknown)'}\n\nTitles:\n{listing}",
                                         tier="cheap", max_tokens=3000)
                for row in data if isinstance(data, list) else data.get("items", []):
                    try:
                        t = batch[int(row["i"])]
                    except (KeyError, ValueError, IndexError, TypeError):
                        continue
                    t["inferred_keyword"] = str(row.get("keyword") or "").strip().lower()
                    t["keyword_priority"] = row.get("priority") if row.get("priority") in ("high", "medium", "low") else "medium"
            except Exception as exc:
                notes.append(f"LLM keyword inference failed for a batch: {http_util.sanitize_text(str(exc))[:120]}")
    for t in pending:
        if not t.get("inferred_keyword"):
            words = [w for w in pubstate.tokens(t["title"]).keys()][:4]
            t["inferred_keyword"] = " ".join(words)
            t.setdefault("keyword_priority", "medium")
            t["keyword_source"] = "heuristic"
    if not llm.configured_providers(cfg):
        notes.append("no LLM key — keywords are title-token heuristics, priority defaults to medium")
    return notes


def enrich_volume(cfg: Config, topics: list[dict[str, Any]]) -> list[str]:
    if not cfg.integration_available("dataforseo"):
        return ["DATAFORSEO_LOGIN/PASSWORD not set — no search volume/difficulty attached"]
    keywords = sorted({t["inferred_keyword"] for t in topics if t.get("inferred_keyword") and t.get("msv") is None})
    if not keywords:
        return []
    data = dataforseo.volume_and_difficulty(cfg, keywords)
    for t in topics:
        row = data.get(t.get("inferred_keyword") or "")
        if row:
            t["msv"], t["kd"] = row["msv"], row["kd"]
    return []


def scrape_one(cfg: Config, root: Path, comp: dict[str, Any], client_description: str, *, max_pages: int,
               max_age_hours: float, force: bool, no_llm: bool, no_volume: bool) -> dict[str, Any]:
    domain = str(comp["domain"]).lower().removeprefix("www.")
    out_path = pubstate.competitors_dir(root) / f"{domain}.json"
    existing = pubstate.load_json(out_path, {})
    scraped_at = publication.parse_iso(existing.get("scraped_at"))
    if scraped_at and not force and datetime.now(timezone.utc) - scraped_at < timedelta(hours=max_age_hours):
        return {"domain": domain, "skipped": True, "reason": f"scraped {scraped_at.isoformat()} (< {max_age_hours}h); pass --force",
                "topics": len(existing.get("topics", []))}
    site_url = f"https://{domain}"
    urls, notes = article_urls(site_url, max_pages)
    known = {t["url"]: t for t in existing.get("topics", [])}
    topics: list[dict[str, Any]] = []
    for url in urls:
        if url in known:
            topics.append(known[url])
            continue
        page = read_page(cfg, url)
        if page:
            topics.append(page)
    if not no_llm:
        notes += infer_keywords(cfg, client_description, topics)
    else:
        for t in topics:
            t.setdefault("inferred_keyword", " ".join(list(pubstate.tokens(t["title"]))[:4]))
            t.setdefault("keyword_priority", "medium")
    if not no_volume:
        notes += enrich_volume(cfg, topics)
    record = {"domain": domain, "name": comp.get("name") or domain, "scraped_at": pubstate.now_iso(),
              "sitemap_urls_considered": len(urls), "topics": topics, "notes": notes}
    pubstate.save_json(out_path, record)
    comp["last_scraped_at"] = record["scraped_at"]
    return {"domain": domain, "skipped": False, "topics": len(topics), "new_topics": sum(1 for t in topics if t["url"] not in known),
            "file": str(out_path), "notes": notes}


def fresh_posts(root: Path, limit: int = 20) -> list[dict[str, Any]]:
    rows = []
    for f in pubstate.competitors_dir(root).glob("*.json"):
        data = pubstate.load_json(f, {})
        for t in data.get("topics", []):
            rows.append({"competitor": data.get("name") or f.stem, "title": t.get("title"), "url": t.get("url"),
                         "published_at": t.get("published_at") or "", "keyword": t.get("inferred_keyword"),
                         "priority": t.get("keyword_priority")})
    rows.sort(key=lambda r: r["published_at"], reverse=True)
    return rows[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape competitor content inventories into per-domain topic files.")
    parser.add_argument("--publication", help="Publication slug")
    parser.add_argument("--domain", action="append", help="Ad-hoc competitor domain (repeatable; also added to strategy.yml)")
    parser.add_argument("--max-pages", type=int, default=40, help="Article pages to read per competitor (default 40)")
    parser.add_argument("--max-age-hours", type=float, default=24.0, help="Skip domains scraped more recently than this")
    parser.add_argument("--force", action="store_true", help="Re-scrape regardless of freshness")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM keyword inference (title heuristics instead)")
    parser.add_argument("--no-volume", action="store_true", help="Skip DataForSEO volume/difficulty enrichment")
    parser.add_argument("--fresh-posts", action="store_true", help="Only print the newest posts across scraped competitors")
    parser.add_argument("--publications-dir", help="Override the publications directory")
    args = parser.parse_args()

    cfg = config_module.load()
    if args.publications_dir:
        cfg.site["publications_dir"] = args.publications_dir
    root = publication.find_publication(cfg, args.publication)
    strategy = pubstate.load_strategy(root)
    if args.fresh_posts:
        print(json.dumps({"checked": True, "publication": root.name, "fresh_posts": fresh_posts(root)}, indent=2, ensure_ascii=False))
        return 0
    competitors = [c for c in strategy.get("competitors", []) if isinstance(c, dict) and c.get("domain")]
    for d in args.domain or []:
        bare = d.replace("https://", "").replace("http://", "").strip("/").lower()
        if not any(c["domain"].lower().removeprefix("www.") == bare.removeprefix("www.") for c in competitors):
            comp = {"name": bare, "domain": bare, "block_from_mentions": False, "source": "user"}
            competitors.append(comp)
            strategy.setdefault("competitors", []).append(comp)
    if not competitors:
        print(json.dumps({"checked": False, "publication": root.name,
                          "error": "no competitors in strategy.yml — add some (positioning.py --suggest, or edit the file, or pass --domain)"}, indent=2))
        return 1
    results = [scrape_one(cfg, root, c, strategy["client"].get("description", ""), max_pages=args.max_pages,
                          max_age_hours=args.max_age_hours, force=args.force, no_llm=args.no_llm, no_volume=args.no_volume)
               for c in competitors]
    pubstate.save_strategy(root, strategy)
    print(json.dumps({"checked": True, "publication": root.name, "competitors": results,
                      "fresh_posts": fresh_posts(root, 10)}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
