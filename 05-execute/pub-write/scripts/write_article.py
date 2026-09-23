"""pub-write: turn a verified outline into a full draft in a chosen voice.

The writing kernel is a voice card (kernels/<name>.md) plus a content template
(templates/<key>.yml) plus the house rules measured on live phantoms
(publication-playbook §3). Composition is section by section, candidate-and-
judge: the quality model returns --candidates versions of each section in one
call, a cheap judge picks the one that best obeys the voice card and uses
the evidence, and the pick is kept. That is the practical form of the
vendor's "adversarial voting"; --candidates 1 skips the judge.

Evidence discipline: the writer receives ONLY the verified points from
research (claim + verbatim quote + source URL). It may paraphrase, it may not
add facts. After composition, every number that appears in a verified point
is anchored to its source URL in the prose ([$2.08 billion](url)) — the
inline-citation pattern measured at 57% numeric anchors.

Mention policy (playbook §6) is decided here, once per article: the client
may be cited only if strategy.mention.degree is not off, the publication's
running mention share is under strategy.mention.rate, and a client landing
survived research as a source. Otherwise the writer is told not to name the
client and any client link that slips through is stripped and logged.

Usage:
    python3 write_article.py --publication llm-billboard --slug advertiser-readiness
    python3 write_article.py --publication llm-billboard --slug advertiser-readiness --kernel juniper --candidates 3
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

from scripts.lib import article, http_util, llm, publication, pubstate
from scripts.lib.config import Config

SKILL_DIR = Path(__file__).resolve().parent.parent
KERNELS_DIR = SKILL_DIR / "kernels"
TEMPLATES_DIR = SKILL_DIR / "templates"
DEFAULT_KERNEL = "editorial"
DEFAULT_TEMPLATE = "long-read"

HOUSE_RULES = (
    "House rules (non-negotiable): third-person trade journalism; no first person; British or American spelling "
    "consistently (follow the sources); paragraphs of 40-90 words; every factual claim comes from the provided evidence "
    "points and may be paraphrased but never extended; every number is written exactly as it appears in its evidence "
    "quote; name the source organization in prose the first time it appears; no headings inside a section (no H3); "
    "no tables; at most one bulleted list per two sections; never praise the client or any vendor; never invent a "
    "statistic, study, quote, or source; do not write a title or the H2 — only the section body in markdown."
)
JUDGE_SYSTEM = (
    "You judge candidate versions of one article section against a voice card, house rules and the evidence points "
    "they were allowed to use. Score each on: fidelity to the voice card, use of the evidence (numbers present, sources "
    "named, nothing invented), specificity, and rhythm. Penalize any fact not in the evidence heavily. Return ONLY JSON: "
    "{\"winner\": index, \"scores\": [numbers], \"notes\": \"one sentence\"}."
)


def load_kernel(name: str) -> str:
    path = KERNELS_DIR / f"{name}.md"
    if not path.is_file():
        raise SystemExit(f"Unknown kernel {name!r}. Available: {', '.join(sorted(p.stem for p in KERNELS_DIR.glob('*.md')))}")
    return path.read_text(encoding="utf-8")


def load_template(key: str) -> dict[str, Any]:
    path = TEMPLATES_DIR / f"{key}.yml"
    if not path.is_file():
        raise SystemExit(f"Unknown template {key!r}. Available: {', '.join(sorted(p.stem for p in TEMPLATES_DIR.glob('*.yml')))}")
    return pubstate.load_yaml(path, {})


def mention_decision(pub: publication.Publication, strategy: dict[str, Any], research: dict[str, Any]) -> dict[str, Any]:
    policy = strategy.get("mention") or {}
    degree = str(policy.get("degree") or "subtle")
    rate = float(policy.get("rate") or 0)
    client = strategy.get("client") or {}
    client_host = str(client.get("domain") or "").lower().removeprefix("www.")
    published = len(pub.posts)
    with_mention = sum(1 for p in pub.posts if isinstance(p.meta.get("mention"), dict) and p.meta["mention"].get("applied"))
    budget = max(1, int(round(rate * (published + 1)))) if rate > 0 else 0
    within_rate = with_mention < budget
    landing = next((s for s in research.get("sources", []) if s.get("origin") == "client_landing"), None)
    trail_ok = landing is not None and any(
        p.get("index") == landing.get("index") and p.get("quotes") for p in research.get("paper_trail", []))
    allowed = degree != "off" and within_rate and trail_ok and bool(client_host)
    reasons = []
    if degree == "off":
        reasons.append("mention.degree is off")
    if not within_rate:
        reasons.append(f"{with_mention} of {published} published posts already mention the client; rate {rate} allows {budget} of {published + 1}")
    if not trail_ok:
        reasons.append("no client landing survived research as a verified source")
    return {"allowed": allowed, "degree": degree if allowed else "off", "client_name": client.get("name") or "", "client_host": client_host,
            "landing_url": landing["url"] if (landing and allowed) else None, "reasons": reasons,
            "share_before": round(with_mention / max(published, 1), 3) if published else 0.0}


def _evidence_block(points: list[dict[str, Any]], sources: dict[int, dict[str, Any]]) -> str:
    lines = []
    for p in points:
        src = sources.get(p.get("source"), {})
        lines.append(f"- CLAIM: {p.get('claim')}\n  EVIDENCE (verbatim): \"{p.get('quote')}\"\n  SOURCE: {src.get('title', '')} — {src.get('url', '')}")
    return "\n".join(lines) or "- (no verified evidence for this section: write from the goal only, without any numbers)"


def compose_section(cfg: Config, kernel: str, section: dict[str, Any], sources: dict[int, dict[str, Any]], context: str,
                    candidates: int, mention: dict[str, Any], is_closing: bool, closing_advice: list[str]) -> tuple[str, dict[str, Any]]:
    mention_rule = (
        f"The client {mention['client_name']} may be cited in this section ONLY through its landing page {mention['landing_url']} and only "
        f"if one of the evidence points uses it; degree '{mention['degree']}': "
        + ("cite it exactly like any other source — anchor the number, no adjectives, no CTA." if mention["degree"] == "subtle"
           else "one natural sentence may name it as context, plus the link; no praise, no CTA.")
        if mention["allowed"] else
        f"Do not name or link the client ({mention['client_name'] or 'the client'}, {mention['client_host'] or 'client domain'}) anywhere."
    )
    closing = ""
    if is_closing:
        closing = "This is the CLOSING section: give sequenced advice ('If X is the gap, do Y'), one short paragraph per item, and end by returning to the opening number.\nAdvice items to cover: " + "; ".join(closing_advice)
    user = (
        f"VOICE CARD:\n{kernel}\n\n{HOUSE_RULES}\n\nARTICLE CONTEXT:\n{context}\n\nSECTION HEADING (already written, do not repeat): {section.get('heading')}\n"
        f"SECTION GOAL: {section.get('goal')}\n\nEVIDENCE POINTS (use these and only these):\n{_evidence_block(section.get('points', []), sources)}\n\n"
        f"MENTION RULE: {mention_rule}\n{closing}\n\n"
        f"Write {candidates} distinct candidate versions of this section body (250-420 words each, markdown paragraphs, inline links "
        f"allowed only to the SOURCE URLs above). Return ONLY JSON: {{\"candidates\": [markdown strings]}}."
    )
    data = llm.complete_json(cfg, "You are the writing kernel of an independent trade publication.", user, max_tokens=8000, effort="high")
    raw = data.get("candidates") if isinstance(data, dict) else data
    versions = [str(c) for c in raw if str(c).strip()] if isinstance(raw, list) else ([str(raw)] if isinstance(raw, str) and raw.strip() else [])
    if not versions:
        raise llm.LlmError(f"kernel returned no candidates for section {section.get('heading')!r}")
    if len(versions) == 1 or candidates == 1:
        return versions[0], {"candidates": len(versions), "winner": 0, "notes": "single candidate"}
    numbered = "\n\n".join(f"=== CANDIDATE {i} ===\n{v}" for i, v in enumerate(versions))
    try:
        verdict = llm.complete_json(cfg, JUDGE_SYSTEM, f"VOICE CARD:\n{kernel}\n\nEVIDENCE:\n{_evidence_block(section.get('points', []), sources)}\n\n{numbered}",
                                    tier="cheap", max_tokens=600)
        winner = int(verdict.get("winner", 0))
        winner = winner if 0 <= winner < len(versions) else 0
        return versions[winner], {"candidates": len(versions), "winner": winner, "scores": verdict.get("scores"), "notes": verdict.get("notes")}
    except (llm.LlmError, ValueError, TypeError):
        return versions[0], {"candidates": len(versions), "winner": 0, "notes": "judge failed; first candidate kept"}


def compose_opening(cfg: Config, kernel: str, outline: dict[str, Any], sources: dict[int, dict[str, Any]], context: str,
                    template_block: str, mention: dict[str, Any]) -> str:
    opening = outline.get("opening") or {}
    if not opening.get("verified"):
        return ""
    src = sources.get(opening.get("source"), {})
    user = (f"VOICE CARD:\n{kernel}\n\n{HOUSE_RULES}\n\nARTICLE CONTEXT:\n{context}\n\nTEMPLATE BLOCK:\n{template_block}\n\n"
            f"OPENING STATISTIC: {opening.get('claim')}\nEVIDENCE (verbatim): \"{opening.get('quote')}\"\nSOURCE: {src.get('title', '')} — {src.get('url', '')}\n"
            f"SECTIONS TO COME: {[s.get('heading') for s in outline.get('sections', [])]}\n"
            f"MENTION RULE: {'the client may not be named here' if not mention['allowed'] else 'do not name the client in the opening'}\n\n"
            f"Write the opening (two or three paragraphs, 120-220 words, no heading). Return ONLY JSON: {{\"opening\": markdown}}.")
    data = llm.complete_json(cfg, "You are the writing kernel of an independent trade publication.", user, max_tokens=2000, effort="high")
    return str(data.get("opening") if isinstance(data, dict) else data).strip()


def anchor_evidence(md: str, outline: dict[str, Any], sources: dict[int, dict[str, Any]]) -> tuple[int, str]:
    """Link every statistic from a verified point to that point's source URL in the prose."""
    anchored = 0
    pts = ([outline.get("opening")] if isinstance(outline.get("opening"), dict) else []) + \
          [p for s in outline.get("sections", []) for p in s.get("points", [])]
    items = article.blocks(md)
    for p in pts:
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
                    anchored += 1
                    break
    return anchored, article.join_blocks(items)


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a draft from its verified outline in a chosen voice.")
    parser.add_argument("--publication", help="Publication slug")
    parser.add_argument("--slug", required=True, help="Draft slug (drafts/<slug>.md with research.outline)")
    parser.add_argument("--kernel", help=f"Voice card (default: strategy.brand_voice.kernel or {DEFAULT_KERNEL})")
    parser.add_argument("--template", default=DEFAULT_TEMPLATE, help=f"Content template key (default {DEFAULT_TEMPLATE})")
    parser.add_argument("--candidates", type=int, default=2, help="Candidate versions per section before the judge (default 2)")
    parser.add_argument("--force", action="store_true", help="Rewrite even if the draft already has a body")
    parser.add_argument("--publications-dir", help="Override the publications directory")
    args = parser.parse_args()

    cfg = config_module.load()
    if args.publications_dir:
        cfg.site["publications_dir"] = args.publications_dir
    if not llm.configured_providers(cfg):
        print(json.dumps({"checked": False, "error": "writing needs an LLM key (ANTHROPIC_API_KEY / OPENAI_API_KEY / GOOGLE_GEMINI_API_KEY)"}, indent=2))
        return 1
    root = publication.find_publication(cfg, args.publication)
    pub = publication.load_publication(root)
    strategy = pubstate.load_strategy(root)
    path = root / "drafts" / f"{args.slug}.md"
    if not path.is_file():
        print(json.dumps({"checked": False, "error": f"{path} not found — create it with pub-research first"}, indent=2))
        return 1
    meta, body = publication.read_post(path)
    research = meta.get("research") if isinstance(meta.get("research"), dict) else {}
    outline = research.get("outline") or {}
    if research.get("status") != "done" or not outline.get("sections"):
        print(json.dumps({"checked": False, "error": "draft has no completed research outline — run research_outline.py first"}, indent=2))
        return 1
    if body.strip() and not args.force:
        print(json.dumps({"checked": False, "error": "draft already has a body — pass --force to rewrite"}, indent=2))
        return 1

    kernel_name = args.kernel or str((strategy.get("brand_voice") or {}).get("kernel") or DEFAULT_KERNEL)
    kernel = load_kernel(kernel_name)
    from scripts.lib import writing
    references = writing.packet('article', args.slug)
    kernel += '\n\nFROZEN HUMAN WRITING REFERENCES — technique only:\n' + writing.prompt('article', args.slug)
    template = load_template(args.template)
    blocks = {b.get("id"): b for b in template.get("blocks", [])}
    sources = {s["index"]: s for s in research.get("sources", [])}
    mention = mention_decision(pub, strategy, research)
    section = pub.section_for(publication.Post(slug=args.slug, meta=meta, body_md=""))
    context = (f"Publication: {pub.name} — {pub.tagline}\nSection: {section['name']}\nTitle: {meta.get('title')}\nDek: {meta.get('dek')}\n"
               f"Direction/thesis: {json.dumps(research.get('direction') or {}, ensure_ascii=False)}\nStances: {strategy.get('stances')}\n"
               f"Target length: {template.get('target_words', 2400)} words across {len(outline['sections'])} sections.")

    if meta.get("refresh_of"):
        context += "\nORIGINAL ARTICLE TO REFRESH (preserve correct useful material; change only what new evidence warrants):\n" + str(meta.get("original_body") or "")
    parts: list[str] = []
    judge_log: list[dict[str, Any]] = []
    opening = compose_opening(cfg, kernel, outline, sources, context, str(blocks.get("opening", {}).get("text", "")), mention)
    parts.append(opening)
    sections = outline["sections"]
    for i, sec in enumerate(sections):
        is_closing = i == len(sections) - 1
        text, verdict = compose_section(cfg, kernel, sec, sources, context, max(1, args.candidates), mention, is_closing,
                                        [str(a) for a in outline.get("closing_advice", [])])
        judge_log.append({"heading": sec.get("heading"), **verdict})
        parts.append(f"## {sec.get('heading')}\n\n{text.strip()}")
    md = "\n\n".join(parts).strip() + "\n"

    anchored, md = anchor_evidence(md, outline, sources)
    stripped = 0
    if mention["client_host"] and not mention["allowed"]:
        md, stripped = article.strip_links_to_host(md, mention["client_host"])
    client_links = [u for _, u in article.links_in(md) if mention["client_host"] and mention["client_host"] in urlparse(u).netloc.lower()]
    if mention["allowed"] and len(client_links) > 1:
        first = client_links[0]
        count = 0

        def keep_first(m: re.Match) -> str:
            nonlocal count
            if m.group(2) == first:
                count += 1
                return m.group(0) if count == 1 else m.group(1)
            return m.group(1) if mention["client_host"] in m.group(2) else m.group(0)
        md = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", keep_first, md)
        client_links = client_links[:1]

    words = article.word_count(md)
    meta.update({
        "status": "written", "kernel": kernel_name, "template": template.get("key", args.template), "word_count": words,
        "written_at": pubstate.now_iso(), "kicker": meta.get("kicker") or "Long read",
        "mention": {"allowed": mention["allowed"], "degree": mention["degree"], "applied": bool(client_links),
                    "landing_url": client_links[0] if client_links else None, "reasons": mention["reasons"], "stripped": stripped},
        "composition": {"candidates": args.candidates, "judge": judge_log, "numeric_anchors": anchored},
        "writing_example_ids": references['example_ids'],
    })
    if not meta.get("section"):
        meta["section"] = section["name"]
    from scripts.lib import languagetool
    meta['languagetool'] = languagetool.check(cfg, md)
    publication.write_post(path, meta, md)
    target = int(template.get("target_words", 2400))
    notes = []
    if words < target * 0.75:
        notes.append(f"short: {words} words vs target {target} — consider --candidates 3 or a richer outline")
    if words > target * 1.35:
        notes.append(f"long: {words} words vs target {target}")
    print(json.dumps({"checked": True, "draft": str(path), "title": meta.get("title"), "kernel": kernel_name, "words": words,
                      "sections": len(sections), "numeric_anchors": anchored, "mention": meta["mention"], "judge": judge_log,
                      "notes": notes, "languagetool": meta['languagetool']}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
