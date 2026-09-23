"""pub-research: research an article's topic against the live web and write a
SOURCED outline into the draft — the step before a writing kernel drafts.

Phases (the vendor's plan -> gather -> read -> direction -> synthesize -> verify,
publication-playbook §4):
  plan        LLM turns the topic + strategy into 4-8 search queries and the
              subsections the piece must cover (plus any --must-include)
  gather      Firecrawl search (or SociaVault Google search) per query; the
              client's landing pages whose context matches are added as
              candidate sources so the client can be cited honestly
  read        fetch each candidate (raw HTML -> text; Firecrawl scrape for thin
              JS pages), keep up to --max-sources with an excerpt on disk
  direction   LLM proposes three directions (thesis + framework) and recommends
              one; --direction-gate pauses here for a human choice
  synthesize  LLM writes the outline: refined title, dek, 6-8 declarative H2
              sections each with claims tied to quoted evidence and a source
              index, an opening statistic, closing advice, 1-2 diagram briefs
  verify      every quoted evidence line is checked against the fetched source
              text; unverifiable claims are dropped and counted

The result lands in the draft's frontmatter under `research:` (outline,
paper_trail, sources, direction, verification counts) and in the `sources`
list, so pub-write and pub-enhance never touch the network for it.

Usage:
    python3 research_outline.py --publication llm-billboard --slug advertiser-readiness
    python3 research_outline.py --publication llm-billboard --topic "Advertiser readiness for the AI search transition" \\
        --source-url https://www.emarketer.com/... --must-include "measurement readiness"
    python3 research_outline.py --publication llm-billboard --slug advertiser-readiness --direction-gate   # pauses
    python3 research_outline.py --publication llm-billboard --slug advertiser-readiness --choice 2         # resumes
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
from typing import Any, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from scripts.lib import firecrawl, http_util, llm, publication, pubstate, sociavault
from scripts.lib.config import Config

MAX_SOURCE_URLS = 20
MAX_MUST_INCLUDE = 40
EXCERPT_CHARS = 9000
MIN_SOURCE_WORDS = 120
VERIFY_RATIO = 0.82

PLAN_SYSTEM = (
    "You plan research for a long-read article in an independent trade publication. Return ONLY JSON: "
    "{\"queries\": [4-8 web search queries that would surface primary data, vendor announcements, analyst numbers and "
    "practitioner accounts], \"must_cover\": [4-8 short subsection subjects the piece must address], \"entities\": "
    "[names of companies/reports likely to hold the key numbers]}. Prefer queries that find statistics and named sources."
)
DIRECTION_SYSTEM = (
    "You are a features editor. Given a topic, the publication's direction and stances, and source summaries, propose "
    "three distinct directions for the article: each {thesis (one sentence), framework (the organizing device: a "
    "diagnosis, a comparison, a sequence, a scorecard...), why_now}. Then pick the strongest as recommended (index). "
    "Return ONLY JSON: {\"options\": [...3], \"recommended\": 0|1|2}."
)
SYNTH_SYSTEM = (
    "You write a sourced outline for a 2,200-2,600 word long read in an independent trade publication. House rules: "
    "the opening paragraph leads with a cited statistic; 6-8 H2 sections whose headings are full declarative sentences "
    "of 8-14 words (no questions except possibly the last one, which may be 'What should <reader> do ...?'); every "
    "factual claim is tied to a VERBATIM quote (10-40 words, copied exactly) from one of the numbered sources; numbers "
    "are anchored on the exact figure as it appears in the source; the close returns to the opening number and gives "
    "sequenced advice. Never invent a source or a number. Return ONLY JSON: {\"title\": str, \"dek\": str (one sentence, "
    "<= 140 chars), \"opening\": {\"claim\": str, \"quote\": str, \"source\": int}, \"sections\": [{\"heading\": str, "
    "\"goal\": str, \"points\": [{\"claim\": str, \"quote\": str, \"source\": int}], \"internal_link_hint\": str|null}], "
    "\"closing_advice\": [str], \"diagrams\": [{\"title\": str, \"brief\": str, \"type\": \"stat_callout\"|\"stepped_flow\"|"
    "\"funnel\"|\"comparison\", \"data\": object}], \"keywords\": [str]}. Diagram `data` must only use numbers present in "
    "the sources."
)


def _draft_path(root: Path, slug: str) -> Path:
    return root / "drafts" / f"{slug}.md"


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9$%.,]+", " ", (text or "").lower()).strip()


def fetch_text(cfg: Config, url: str) -> tuple[str, str]:
    """(title, text) for a URL. Raw fetch first; Firecrawl for thin pages when configured."""
    title, text = "", ""
    try:
        resp = http_util.get(url, timeout=30.0, min_interval=0.7, cache_dir=cfg.state_dir / "http-cache", cache_ttl=7 * 86400)
        ctype = resp.headers.get("content-type", "")
        if resp.status_code == 200 and ("html" in ctype or "xml" in ctype or not ctype):
            soup = BeautifulSoup(resp.text, "lxml")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "svg"]):
                tag.decompose()
            title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
            main = soup.find("article") or soup.find("main") or soup.body or soup
            text = re.sub(r"\s+", " ", main.get_text(" ", strip=True))
        elif resp.status_code == 200 and "text/plain" in ctype:
            text = resp.text
    except Exception as exc:
        text = ""
        title = f"(fetch failed: {http_util.sanitize_text(str(exc))[:80]})"
    if len(text.split()) < MIN_SOURCE_WORDS and cfg.integration_available("firecrawl"):
        try:
            data = firecrawl.scrape(cfg, url, formats=["markdown"])
            md = (data.get("data", data) or {}).get("markdown", "")
            if len(md.split()) > len(text.split()):
                text = re.sub(r"\s+", " ", md)
                title = title or (data.get("data", data) or {}).get("metadata", {}).get("title", "")
        except Exception:
            pass
    return title, text


def verify_quote(quote: str, source_text: str) -> bool:
    q, source = _normalize(quote), _normalize(source_text)
    return bool(q and source and q in source)


def landing_candidates(strategy: dict[str, Any], topic: str, brief: str) -> list[dict[str, Any]]:
    out = []
    for landing in strategy.get("landings", []):
        score = pubstate.overlap(f"{topic} {brief}", f"{landing.get('context', '')}")
        if score >= 0.15:
            out.append({"url": landing["url"], "title": landing.get("context", "")[:120], "origin": "client_landing", "score": round(score, 3)})
    return sorted(out, key=lambda x: -x["score"])[:2]


def plan(cfg: Config, topic: str, brief: str, angle: str, strategy: dict[str, Any], must_include: list[str]) -> dict[str, Any]:
    user = (f"Topic: {topic}\nAngle: {angle or '-'}\nBrief: {brief or '-'}\nPublication direction: {strategy.get('direction')}\n"
            f"Stances: {strategy.get('stances')}\nAvoid: {strategy.get('avoid_topics')}\nMust include (from the owner): {must_include}")
    data = llm.complete_json(cfg, PLAN_SYSTEM, user, tier="cheap", max_tokens=1500)
    queries = [str(q) for q in data.get("queries", []) if q][:8] or [topic]
    must = [str(m) for m in data.get("must_cover", []) if m][:8]
    return {"queries": queries, "must_cover": list(dict.fromkeys(must_include + must))[:MAX_MUST_INCLUDE],
            "entities": [str(e) for e in data.get("entities", [])][:10]}


def gather(cfg: Config, queries: list[str], seed_urls: list[str], client_domain: str, *, no_search: bool) -> tuple[list[dict[str, Any]], list[str]]:
    notes: list[str] = []
    candidates: list[dict[str, Any]] = [{"url": u, "title": "", "origin": "seed"} for u in seed_urls]
    if not no_search:
        if cfg.integration_available("firecrawl"):
            for q in queries:
                try:
                    for r in firecrawl.search(cfg, q, limit=6):
                        candidates.append({"url": r["url"], "title": r.get("title") or "", "origin": f"search:{q}"})
                except Exception as exc:
                    notes.append(f"search failed for {q!r}: {http_util.sanitize_text(str(exc))[:100]}")
        elif cfg.integration_available("sociavault"):
            for q in queries:
                try:
                    payload = sociavault.google_search(cfg, q, date_posted=None)
                    for r in sociavault._items(payload, "results", "items"):
                        n = sociavault.normalize("google", r)
                        if n.get("url"):
                            candidates.append({"url": n["url"], "title": n.get("title") or "", "origin": f"search:{q}"})
                except Exception as exc:
                    notes.append(f"search failed for {q!r}: {http_util.sanitize_text(str(exc))[:100]}")
        else:
            notes.append("no search provider (FIRECRAWL_API_KEY or SOCIAVAULT_API_KEY) — only seed URLs are read")
    seen: set[str] = set()
    unique = []
    for c in candidates:
        key = c["url"].split("#")[0].rstrip("/")
        host = urlparse(key).netloc.lower().removeprefix("www.")
        if not key.startswith("http") or key in seen:
            continue
        if client_domain and host.endswith(client_domain) and c["origin"] != "client_landing" and c["origin"] != "seed":
            continue
        if re.search(r"\.(pdf|png|jpe?g|gif|zip)$", key, re.I) or any(b in host for b in ("youtube.com", "twitter.com", "x.com", "facebook.com", "linkedin.com")):
            continue
        seen.add(key)
        unique.append(c)
    return unique, notes


def read(cfg: Config, candidates: list[dict[str, Any]], max_sources: int, cache_dir: Path) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for c in candidates:
        if len(sources) >= max_sources:
            break
        title, text = fetch_text(cfg, c["url"])
        if len(text.split()) < MIN_SOURCE_WORDS and c["origin"] != "client_landing":
            continue
        digest = hashlib.sha256((c["url"] + "\0" + text).encode("utf-8")).hexdigest()
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{digest}.txt"
        if not cache_path.exists():
            pubstate.atomic_text(cache_path, text)
        sources.append({"index": len(sources) + 1, "url": c["url"], "title": (c.get("title") or title or urlparse(c["url"]).netloc)[:160],
                        "origin": c["origin"], "words": len(text.split()), "cache": str(cache_dir / f"{digest}.txt")})
    return sources


def _source_digest(sources: list[dict[str, Any]], per_source_chars: int) -> str:
    parts = []
    for s in sources:
        text = Path(s["cache"]).read_text(encoding="utf-8") if Path(s["cache"]).is_file() else ""
        parts.append(f"[{s['index']}] {s['title']} — {s['url']}\n{text[:per_source_chars]}")
    return "\n\n".join(parts)


def directions(cfg: Config, topic: str, strategy: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    user = (f"Topic: {topic}\nDirection: {strategy.get('direction')}\nStances: {strategy.get('stances')}\n\n"
            f"Sources (summaries):\n{_source_digest(sources, 700)}")
    data = llm.complete_json(cfg, DIRECTION_SYSTEM, user, max_tokens=2000)
    options = [o for o in data.get("options", []) if isinstance(o, dict)][:3]
    rec = data.get("recommended", 0)
    return {"options": options, "recommended": rec if isinstance(rec, int) and 0 <= rec < len(options) else 0}


def synthesize(cfg: Config, topic: str, brief: str, direction: dict[str, Any], plan_data: dict[str, Any], strategy: dict[str, Any],
               sources: list[dict[str, Any]], depth: str, ranking_targets: list[str]) -> dict[str, Any]:
    user = (f"Topic: {topic}\nBrief: {brief}\nChosen direction: {json.dumps(direction, ensure_ascii=False)}\n"
            f"Must cover: {plan_data.get('must_cover')}\nRanking targets in play (only if natural): {ranking_targets}\n"
            f"Depth: {'headings + goals only' if depth == 'barebones' else 'headings with 3-6 evidenced points each'}\n"
            f"Publication stances: {strategy.get('stances')}\nAvoid: {strategy.get('avoid_topics')}\n\n"
            f"Numbered sources:\n{_source_digest(sources, EXCERPT_CHARS if depth == 'fleshed_out' else 3000)}")
    return llm.complete_json(cfg, SYNTH_SYSTEM, user, max_tokens=12000, effort="high")


def verify(outline: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    texts = {s["index"]: (Path(s["cache"]).read_text(encoding="utf-8") if Path(s["cache"]).is_file() else "") for s in sources}
    kept = dropped = 0
    trail: dict[int, list[str]] = {}

    def check(point: dict[str, Any]) -> bool:
        nonlocal kept, dropped
        idx = point.get("source")
        quote = str(point.get("quote") or "")
        ok = isinstance(idx, int) and idx in texts and verify_quote(quote, texts[idx])
        if ok:
            kept += 1
            trail.setdefault(idx, []).append(quote)
        else:
            dropped += 1
        point["verified"] = ok
        return ok

    if isinstance(outline.get("opening"), dict):
        if not check(outline["opening"]):
            outline.pop("opening")
    for section in outline.get("sections", []):
        section["points"] = [p for p in section.get("points", []) if isinstance(p, dict) and check(p)]
    paper_trail = [{"index": s["index"], "url": s["url"], "title": s["title"], "quotes": trail.get(s["index"], [])} for s in sources]
    return {"kept": kept, "dropped": dropped, "paper_trail": paper_trail}


def main() -> int:
    parser = argparse.ArgumentParser(description="Research a topic and write a verified, sourced outline into a draft.")
    parser.add_argument("--publication", help="Publication slug")
    parser.add_argument("--slug", help="Draft slug (drafts/<slug>.md); created from --topic if missing")
    parser.add_argument("--topic", help="Topic/working title when no draft exists yet")
    parser.add_argument("--spoke-id", help="Topic-map spoke this article covers (recorded in the draft)")
    parser.add_argument("--source-url", action="append", default=[], help=f"Seed URL to read first (repeatable, max {MAX_SOURCE_URLS})")
    parser.add_argument("--must-include", action="append", default=[], help=f"Subsection the outline must cover (repeatable, max {MAX_MUST_INCLUDE})")
    parser.add_argument("--depth", choices=["barebones", "fleshed_out"], default="fleshed_out")
    parser.add_argument("--max-sources", type=int, default=12, help="Sources to read (default 12)")
    parser.add_argument("--direction-gate", action="store_true", help="Pause after proposing directions (status awaiting_direction)")
    parser.add_argument("--direction", help="Resume with your own direction/thesis")
    parser.add_argument("--choice", type=int, help="Resume by picking a proposed direction (0-based index)")
    parser.add_argument("--no-search", action="store_true", help="Read only --source-url seeds and matching landings")
    parser.add_argument("--publications-dir", help="Override the publications directory")
    args = parser.parse_args()

    cfg = config_module.load()
    if args.publications_dir:
        cfg.site["publications_dir"] = args.publications_dir
    if len(args.source_url) > MAX_SOURCE_URLS or len(args.must_include) > MAX_MUST_INCLUDE:
        parser.error(f"at most {MAX_SOURCE_URLS} --source-url and {MAX_MUST_INCLUDE} --must-include")
    if not llm.configured_providers(cfg):
        print(json.dumps({"checked": False, "error": "research needs an LLM key (ANTHROPIC_API_KEY / OPENAI_API_KEY / GOOGLE_GEMINI_API_KEY)"}, indent=2))
        return 1
    root = publication.find_publication(cfg, args.publication)
    strategy = pubstate.load_strategy(root)
    topic_map = pubstate.load_topic_map(root)

    slug = args.slug or (publication.slugify(args.topic, max_len=70) if args.topic else None)
    if not slug:
        parser.error("pass --slug (existing draft) or --topic")
    path = _draft_path(root, slug)
    if path.is_file():
        meta, body = publication.read_post(path)
    else:
        if not args.topic:
            parser.error(f"{path} does not exist — pass --topic to create it")
        meta, body = {"title": args.topic, "slug": slug, "status": "draft", "created_at": pubstate.now_iso()}, ""
    if args.spoke_id:
        meta["spoke_id"] = args.spoke_id
    spoke = pubstate.find_spoke(topic_map, str(meta.get("spoke_id") or "")) or {}
    topic = str(meta.get("title") or args.topic)
    brief = str(meta.get("brief") or spoke.get("brief") or "")
    angle = str(spoke.get("angle") or "")
    if meta.get("refresh_of"):
        brief += "\nRefresh this existing article; preserve useful material and identify only substantive deltas:\n" + str(meta.get("original_body") or "")
    research = meta.get("research") if isinstance(meta.get("research"), dict) else {}
    result: dict[str, Any] = {"checked": True, "publication": root.name, "draft": str(path), "topic": topic, "notes": []}
    cache_dir = cfg.state_dir / "pub-research" / root.name / slug

    if research.get("status") == "awaiting_direction" and (args.direction or args.choice is not None):
        sources = research.get("sources", [])
        plan_data = research.get("plan", {})
        options = research.get("direction_options", [])
        if args.direction:
            direction = {"thesis": args.direction, "framework": "", "why_now": "", "source": "user"}
        else:
            if args.choice is None or not 0 <= args.choice < len(options):
                parser.error(f"--choice must be 0..{len(options) - 1}")
            direction = {**options[args.choice], "source": f"option {args.choice}"}
    else:
        seed_urls = list(dict.fromkeys(args.source_url + [str(u) for u in (meta.get("source_urls") or [])]))
        plan_data = plan(cfg, topic, brief, angle, strategy, args.must_include)
        result["plan"] = plan_data
        candidates, notes = gather(cfg, plan_data["queries"], seed_urls, str(strategy.get("client", {}).get("domain") or ""), no_search=args.no_search)
        candidates = landing_candidates(strategy, topic, brief) + candidates
        result["notes"] += notes
        sources = read(cfg, candidates, args.max_sources, cache_dir)
        if not sources:
            research.update({"status": "failed", "reason": "no readable sources", "plan": plan_data})
            meta["research"] = research
            publication.write_post(path, meta, body)
            result.update({"checked": False, "error": "no readable sources found — add --source-url seeds or configure a search provider"})
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 1
        dirs = directions(cfg, topic, strategy, sources)
        research = {"status": "awaiting_direction" if args.direction_gate else "synthesizing", "plan": plan_data, "sources": sources,
                    "direction_options": dirs["options"], "recommended": dirs["recommended"], "started_at": pubstate.now_iso()}
        if args.direction_gate:
            meta["research"] = research
            publication.write_post(path, meta, body)
            result.update({"status": "awaiting_direction", "direction_options": dirs["options"], "recommended": dirs["recommended"],
                           "next_step": f"rerun with --choice N (0..{len(dirs['options']) - 1}) or --direction \"...\""})
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        direction = {**(dirs["options"][dirs["recommended"]] if dirs["options"] else {"thesis": topic}), "source": "recommended"}

    targets = [t.get("phrase") for t in strategy.get("ranking_targets", []) if pubstate.overlap(str(t.get("phrase")), f"{topic} {brief}") > 0.2]
    outline = synthesize(cfg, topic, brief, direction, plan_data, strategy, sources, args.depth, targets)
    verification = verify(outline, sources)
    research.update({"status": "done", "direction": direction, "outline": outline, "verification": {k: verification[k] for k in ("kept", "dropped")},
                     "paper_trail": verification["paper_trail"], "finished_at": pubstate.now_iso()})
    meta["research"] = research
    if outline.get("title"):
        meta["title"] = str(outline["title"])
    if outline.get("dek"):
        meta["dek"] = str(outline["dek"])
    meta["sources"] = [{"url": s["url"], "title": s["title"]} for s in sources if any(p["index"] == s["index"] and p["quotes"] for p in verification["paper_trail"])]
    publication.write_post(path, meta, body)
    result.update({"status": "done", "title": meta["title"], "sources_read": len(sources), "claims_verified": verification["kept"],
                   "claims_dropped": verification["dropped"], "sections": len(outline.get("sections", [])),
                   "diagrams": len(outline.get("diagrams", [])), "direction": direction})
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
