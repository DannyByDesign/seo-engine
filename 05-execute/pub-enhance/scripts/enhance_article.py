"""pub-enhance: the editing passes a senior editor adds before an article
ships — internal links from the publication's own catalogue, the Sources
list, numeric anchors, a number verifier, diagram placement, metadata, and
(opt-in) a voice pass. The vendor's Enhance flow stages (publication-playbook
§4): add_links -> sources -> visuals -> keywords -> verify -> voice.

Stages (--stages, default all except voice):
  links     contextual links to published posts: candidates ranked by term
            overlap between each paragraph and a post's title/dek/H2s; the
            anchor is a phrase from the target title that already appears in
            the paragraph; one link per paragraph, at most --max-internal-links
  sources   frontmatter `sources` = paper-trail sources that back a quote +
            every external URL actually linked in the body, in body order
  anchors   any verified-point number still unlinked gets linked to its source
  diagrams  research.outline.diagrams -> assets/<slug>/diagram-N.json specs
            (rendered by pub-visuals) + image placeholders after the most
            relevant section, alt "Diagram: <title>. Visualizes: <brief>"
  keywords  LLM suggestions (report only): 3-6 semantic phrases the piece
            lacks for its keyword — the agent decides whether to weave them in
  verify    every number in the prose must appear in a cached source text or
            a linked page (--check-links fetches unlinked/uncached sources);
            --strict-verify fails the run on any unverified number
  meta      dek <= 160 chars, title length, tags = [section], kicker, reading time
  voice     LLM pass against the voice card; accepted only if numbers, links,
            headings and length are unchanged

Usage:
    python3 enhance_article.py --publication llm-billboard --slug advertiser-readiness
    python3 enhance_article.py --publication llm-billboard --slug advertiser-readiness --stages links,sources,verify --strict-verify
    python3 enhance_article.py --publication llm-billboard --slug advertiser-readiness --posts --stages links --dry-run
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
from typing import Any, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from scripts.lib import article, http_util, llm, publication, pubstate
from scripts.lib.config import Config

ALL_STAGES = ["links", "sources", "anchors", "diagrams", "keywords", "verify", "meta", "voice", "language"]
DEFAULT_STAGES = [s for s in ALL_STAGES if s != "voice"]
LINK_MIN_OVERLAP = 0.12
KEYWORDS_SYSTEM = (
    "You are an SEO editor. Given an article's target keyword, title, headings and a text sample, list 3-6 semantically "
    "related phrases a comprehensive treatment would naturally contain but this text lacks. Return ONLY JSON: {\"missing\": [str]}."
)
VOICE_SYSTEM = (
    "You are a line editor enforcing a voice card. Rewrite ONLY sentences that violate it (hedging, first person, filler, "
    "banned words, throat-clearing). Keep every number, link, heading, list and paragraph break exactly as is. Return the "
    "full markdown body unchanged except for those sentences. Return ONLY JSON: {\"markdown\": string}."
)


def catalogue(pub: publication.Publication, exclude_slug: str) -> list[dict[str, Any]]:
    items = []
    for p in pub.posts:
        if p.slug == exclude_slug:
            continue
        items.append({"slug": p.slug, "title": p.title, "text": f"{p.title} {p.dek} {' '.join(article.headings(p.body_md))}"})
    return items


def stage_links(body: str, targets: list[dict[str, Any]], max_links: int) -> tuple[str, list[dict[str, Any]]]:
    items = article.blocks(body)
    existing = {u for _, u in article.links_in(body)}
    used_targets = {u.split("/posts/")[1].split("#")[0].split(")")[0] for u in existing if "/posts/" in u}
    inserted: list[dict[str, Any]] = []
    for b in items:
        if len(inserted) >= max_links:
            break
        if b["kind"] != "para" or "](/posts/" in b["text"]:
            continue
        best: Optional[tuple[float, dict[str, Any], str]] = None
        for t in targets:
            if t["slug"] in used_targets:
                continue
            score = pubstate.overlap(b["text"], t["text"])
            if score < LINK_MIN_OVERLAP:
                continue
            phrase = article.find_anchor_phrase(b["text"], t["title"])
            if phrase and (best is None or score > best[0]):
                best = (score, t, phrase)
        if best:
            new, changed = article.insert_link(b["text"], best[2], f"/posts/{best[1]['slug']}")
            if changed:
                b["text"] = new
                used_targets.add(best[1]["slug"])
                inserted.append({"target": best[1]["slug"], "anchor": best[2], "overlap": round(best[0], 3)})
    return article.join_blocks(items), inserted


def stage_sources(meta: dict[str, Any], body: str, site_host: str) -> list[dict[str, Any]]:
    trail = {p["url"]: p for p in ((meta.get("research") or {}).get("paper_trail") or []) if p.get("quotes")}
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, url in article.links_in(body):
        host = urlparse(url).netloc.lower().removeprefix("www.")
        if not url.startswith("http") or host == site_host or host.endswith("." + site_host) or url in seen:
            continue
        seen.add(url)
        ordered.append({"url": url, "title": trail.get(url, {}).get("title") or host})
    for url, p in trail.items():
        if url not in seen:
            seen.add(url)
            ordered.append({"url": url, "title": p.get("title") or urlparse(url).netloc})
    return ordered


def stage_anchors(body: str, research: dict[str, Any]) -> tuple[str, int]:
    sources = {s["index"]: s for s in research.get("sources", [])}
    outline = research.get("outline") or {}
    points = ([outline.get("opening")] if isinstance(outline.get("opening"), dict) else []) + \
             [p for s in outline.get("sections", []) for p in s.get("points", [])]
    items = article.blocks(body)
    count = 0
    for p in points:
        url = sources.get(p.get("source"), {}).get("url")
        if not url:
            continue
        for tok in article.statistic_tokens(f"{p.get('claim') or ''} {p.get('quote') or ''}")[:4]:
            for b in items:
                if b["kind"] != "para":
                    continue
                new, changed = article.anchor_number(b["text"], tok, url)
                if changed:
                    b["text"] = new
                    count += 1
                    break
    return article.join_blocks(items), count


def stage_diagrams(root: Path, slug: str, body: str, research: dict[str, Any]) -> tuple[str, list[str]]:
    diagrams = [d for d in ((research.get("outline") or {}).get("diagrams") or []) if isinstance(d, dict) and d.get("title")][:2]
    if not diagrams:
        return body, []
    asset_dir = root / "assets" / slug
    publication.assert_unpublished_assets(root, asset_dir)
    asset_dir.mkdir(parents=True, exist_ok=True)
    items = article.blocks(body)
    written = []
    for n, d in enumerate(diagrams, start=1):
        spec_path = asset_dir / f"diagram-{n}.json"
        alt = f"Diagram: {d['title']}. Visualizes: {str(d.get('brief') or '').strip()}"
        if f"diagram-{n}." in body:
            continue
        spec_path.write_text(json.dumps({"type": d.get("type") or "stat_callout", "title": d["title"], "brief": d.get("brief"),
                                         "data": d.get("data") or {}, "alt": alt}, indent=2, ensure_ascii=False), encoding="utf-8")
        written.append(str(spec_path))
        best_i, best = None, 0.0
        for i, b in enumerate(items):
            if b["kind"] == "heading":
                sec_text = b["text"] + " " + " ".join(x["text"] for x in items[i + 1:i + 4] if x["kind"] == "para")
                score = pubstate.overlap(f"{d['title']} {d.get('brief', '')}", sec_text)
                if score > best:
                    best, best_i = score, i
        image = {"kind": "image", "text": f"![{alt}](diagram-{n}.svg)"}
        if best_i is None:
            items.append({"kind": "blank", "text": ""})
            items.append(image)
        else:
            j = best_i + 1
            while j < len(items) and items[j]["kind"] != "heading":
                j += 1
            items[j:j] = [{"kind": "blank", "text": ""}, image, {"kind": "blank", "text": ""}]
    return article.join_blocks(items), written


def stage_keywords(cfg: Config, meta: dict[str, Any], body: str, keyword: str) -> list[str]:
    if not llm.configured_providers(cfg) or not keyword:
        return []
    sample = " ".join(b["text"] for b in article.blocks(body) if b["kind"] == "para")[:6000]
    try:
        data = llm.complete_json(cfg, KEYWORDS_SYSTEM, f"Keyword: {keyword}\nTitle: {meta.get('title')}\nHeadings: {article.headings(body)}\nText: {sample}",
                                 tier="cheap", max_tokens=400)
        return [str(k) for k in data.get("missing", [])][:6]
    except llm.LlmError:
        return []


def stage_verify(cfg: Config, body: str, research: dict[str, Any], *, check_links: bool) -> dict[str, Any]:
    texts: list[str] = []
    for s in research.get("sources", []):
        p = Path(str(s.get("cache") or ""))
        if p.is_file():
            texts.append(p.read_text(encoding="utf-8"))
    fetched = 0
    if check_links:
        for _, url in article.links_in(body):
            if url.startswith("http") and not any(url == s.get("url") for s in research.get("sources", [])):
                try:
                    resp = http_util.get(url, timeout=25.0, cache_dir=cfg.state_dir / "http-cache", cache_ttl=7 * 86400)
                    soup = BeautifulSoup(resp.text, "lxml")
                    texts.append(re.sub(r"\s+", " ", soup.get_text(" ", strip=True)))
                    fetched += 1
                except Exception:
                    continue
    corpus = " ".join(texts)
    corpus_numbers = article.numbers_in(corpus)
    prose = " ".join(b["text"] for b in article.blocks(body) if b["kind"] in ("para", "list"))
    prose_numbers = article.numbers_in(prose)
    unverified = sorted(n for n in prose_numbers if n not in corpus_numbers and n.rstrip("%") not in corpus_numbers)
    return {"method": "numeric_presence_only_not_claim_verification", "numbers_in_prose": len(prose_numbers), "verified": len(prose_numbers) - len(unverified), "unverified": unverified,
            "sources_available": len(texts), "links_fetched": fetched}


def stage_meta(meta: dict[str, Any], body: str, section_name: str) -> list[str]:
    notes = []
    dek = str(meta.get("dek") or "")
    if len(dek) > 160:
        notes.append(f"dek is {len(dek)} chars (> 160); shorten it")
    if len(str(meta.get("title") or "")) > 75:
        notes.append("title is over 75 characters")
    meta.setdefault("tags", [section_name])
    meta.setdefault("kicker", "Long read")
    meta["word_count"] = article.word_count(body)
    meta["reading_minutes"] = publication.reading_minutes(meta["word_count"])
    seo = meta.get("seo") if isinstance(meta.get("seo"), dict) else {}
    seo.setdefault("description", dek[:160])
    meta["seo"] = seo
    return notes


def stage_voice(cfg: Config, body: str, kernel_name: str) -> tuple[str, str]:
    kernel_path = Path(__file__).resolve().parent.parent.parent / "pub-write" / "kernels" / f"{kernel_name}.md"
    if not kernel_path.is_file() or not llm.configured_providers(cfg):
        return body, "voice pass skipped (no kernel file or no LLM key)"
    try:
        data = llm.complete_json(cfg, VOICE_SYSTEM, f"VOICE CARD:\n{kernel_path.read_text(encoding='utf-8')}\n\nBODY:\n{body}", max_tokens=16000)
        new = str(data.get("markdown") or "")
    except llm.LlmError as exc:
        return body, f"voice pass failed: {http_util.sanitize_text(str(exc))[:120]}"
    problems = article.guard_unchanged(body, new)
    if problems or not new.strip():
        return body, f"voice pass rejected: {problems or 'empty'}"
    return new, "voice pass applied"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Enhance passes over a draft or post.")
    parser.add_argument("--publication", help="Publication slug")
    parser.add_argument("--slug", required=True, help="Article slug")
    parser.add_argument("--posts", action="store_true", help="Operate on posts/<slug>.md instead of drafts/")
    parser.add_argument("--stages", default=",".join(DEFAULT_STAGES), help=f"Comma list from {ALL_STAGES}")
    parser.add_argument("--max-internal-links", type=int, default=4, help="Cap on inserted internal links (default 4)")
    parser.add_argument("--check-links", action="store_true", help="verify: fetch linked pages not in the research cache")
    parser.add_argument("--strict-verify", action="store_true", help="Exit 1 if any number cannot be verified")
    parser.add_argument("--voice", action="store_true", help="Include the voice stage")
    parser.add_argument("--dry-run", action="store_true", help="Compute and report; write nothing")
    parser.add_argument("--publications-dir", help="Override the publications directory")
    args = parser.parse_args()

    cfg = config_module.load()
    if args.publications_dir:
        cfg.site["publications_dir"] = args.publications_dir
    stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    unknown = [s for s in stages if s not in ALL_STAGES]
    if unknown:
        parser.error(f"unknown stages {unknown}; choose from {ALL_STAGES}")
    if args.voice and "voice" not in stages:
        stages.append("voice")
    root = publication.find_publication(cfg, args.publication)
    pub = publication.load_publication(root)
    path = root / ("posts" if args.posts else "drafts") / f"{args.slug}.md"
    if not path.is_file():
        print(json.dumps({"checked": False, "error": f"{path} not found"}, indent=2))
        return 1
    meta, body = publication.read_post(path)
    if args.posts and not args.dry_run:
        print(json.dumps({'checked': False, 'error': 'enhance an isolated refresh draft, not a published post'})); return 1
    if not body.strip():
        print(json.dumps({"checked": False, "error": "article body is empty — run pub-write first"}, indent=2))
        return 1
    research = meta.get("research") if isinstance(meta.get("research"), dict) else {}
    section = pub.section_for(publication.Post(slug=args.slug, meta=meta, body_md=body))
    report: dict[str, Any] = {"checked": True, "file": str(path), "stages": stages, "dry_run": args.dry_run}
    original = body

    if "links" in stages:
        body, inserted = stage_links(body, catalogue(pub, args.slug), args.max_internal_links)
        report["links"] = {"inserted": inserted, "candidates": len(pub.posts) - (1 if args.posts else 0)}
    if "anchors" in stages:
        body, n = stage_anchors(body, research)
        report["anchors"] = {"added": n}
    if "diagrams" in stages:
        if args.dry_run:
            specs = []
        else:
            asset_dir = publication.draft_assets(root, args.slug, meta)
            body, specs = stage_diagrams(root, asset_dir.name, body, research)
        report["diagrams"] = {"specs_written": specs}
    if "voice" in stages:
        body, note = stage_voice(cfg, body, str(meta.get("kernel") or (pubstate.load_strategy(root).get("brand_voice") or {}).get("kernel") or "editorial"))
        report["voice"] = note
    if "sources" in stages:
        meta["sources"] = stage_sources(meta, body, pub.host)
        report["sources"] = {"count": len(meta["sources"])}
    if "keywords" in stages:
        spoke = pubstate.find_spoke(pubstate.load_topic_map(root), str(meta.get("spoke_id") or "")) or {}
        report["keywords"] = {"missing_phrases": stage_keywords(cfg, meta, body, str(spoke.get("seo_keyword") or meta.get("seo_keyword") or ""))}
    if "verify" in stages:
        report["verify"] = stage_verify(cfg, body, research, check_links=args.check_links)
    if "meta" in stages:
        report["meta"] = {"notes": stage_meta(meta, body, section["name"])}

    if 'language' in stages:
        if args.dry_run:
            report['languagetool'] = {'checked': False, 'status': 'dry_run'}
        else:
            from scripts.lib import languagetool
            meta['languagetool'] = languagetool.check(cfg, body)
            report['languagetool'] = meta['languagetool']

    guard = article.guard_unchanged(original, body) if "voice" in stages else []
    report["guard"] = guard
    changed = body != original
    if not args.dry_run and not guard:
        meta["enhanced_at"] = pubstate.now_iso()
        if "verify" in report:
            meta["verification"] = report["verify"]
        publication.write_post(path, meta, body)
        report["written"] = True
    report["changed"] = changed
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.strict_verify and report.get("verify", {}).get("unverified"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
