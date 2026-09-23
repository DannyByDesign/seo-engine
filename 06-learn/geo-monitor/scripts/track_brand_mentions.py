"""geo-monitor: brand-mention tracking across AI assistants — the Lettertrace
method (MIT), see publication-playbook.md section 7 and geo-playbook.md
section 9.

What it measures, per run: for each tracked prompt x configured provider x
--replicates, the assistant's full ANSWER TEXT (not only its citations) is
checked for the brand and each competitor with deterministic detection
(scripts/lib/mentions.py: name + aliases, never the domain label, link
targets blanked, longest alias first). Detected entities are enriched with
a cheap model for sentiment (positive|neutral|negative) and `recommended`.
Cited sources are kept with an `owned` flag (brand domains + publication
domains) so "cited without being named" is visible.

Metrics (each rate with a Wilson interval): mention rate, share of voice,
average prominence (1 - first position), recommend rate, sentiment score,
owned citation rate, informative rate, and the five-state verdict
no-data | no-competitors | thin-sample | real-gap | healthy. Per-prompt entity
breakdown surfaces the questions competitors win; per-page cited rates show
which publication posts assistants actually cite.

Prompt design follows the one rule that measured anything in the vendor's
pilots: a prompt only measures something if the answer names companies.
--generate turns each topic into variations that mostly demand named
vendors ("List the top 5 ... by name"), labeled general|mid|niche.

Usage:
    python3 track_brand_mentions.py --publication llm-billboard --generate --dry-run   # see prompts + cost
    python3 track_brand_mentions.py --publication llm-billboard --replicates 2
    python3 track_brand_mentions.py --brand thrad --domain thrad.ai --alias "Thrad AI" \\
        --competitor "Lapis=trylapis.com" --topic "LLM advertising platforms" --generate
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
from scripts.lib import config as config_module  # noqa: E402

import argparse  # noqa: E402
import json
import hashlib
import inspect  # noqa: E402
import time  # noqa: E402
from typing import Any, Optional  # noqa: E402
from urllib.parse import urlparse  # noqa: E402

from scripts.lib import ai_visibility, http_util, llm, mentions, publication, pubstate, stats  # noqa: E402
from scripts.lib.config import Config  # noqa: E402

PROVIDER_ORDER = ["openai", "anthropic", "perplexity", "gemini"]
DEFAULT_VARIATIONS = 8
LOW_INFORMATIVE_RATE = 0.5

VARIATION_SYSTEM = (
    "You generate the questions a brand-monitoring tool will ask an AI assistant (ChatGPT, Claude) to discover which "
    "companies get named in answers about a topic.\n\nA question is only useful if the answer to it names specific "
    "companies. Questions that read naturally but get answered with explanation instead of names measure nothing. That "
    "is the most common failure and the one to avoid.\n\nRules:\n- At least two thirds of the questions must explicitly "
    "demand named companies. Shapes that work: \"List the top 5 companies that…\", \"Name the specific vendors that…\", "
    "\"Rank the leading providers of… by name\", \"Which companies sell…? Just the company names.\" Use the words "
    "\"companies\", \"vendors\", or \"providers\", and ask for them by name.\n- Never ask for \"a shortlist\" or for how to "
    "choose/evaluate. Both get answered with advice about making a decision rather than with the options themselves.\n"
    "- Keep the remaining questions in a buyer's own words (\"What's the best X for Y?\", \"Who are the main players in "
    "X?\") so the set reflects real usage, but keep them the minority.\n- Do NOT name any specific brand in the questions "
    "unless the brand is part of the topic itself.\n- Vary buyer intent and seniority, not just the wording.\n- Spread the "
    "questions across a specificity ladder and label each one: \"general\" = the broad category question anyone might ask; "
    "\"mid\" = qualified by a segment or use case; \"niche\" = a specific buyer situation, narrow enough that smaller or "
    "newer companies can realistically be named. Aim for a roughly even mix of the three tiers. The named-companies rule "
    "applies at every tier.\n- Return ONLY a JSON array of objects shaped {\"question\": string, \"specificity\": "
    "\"general\" | \"mid\" | \"niche\"}. No commentary."
)
ANALYZE_SYSTEM = (
    "You analyze how brands are portrayed inside an AI assistant's answer. For each entity you are given, decide:\n"
    "- sentiment: how the answer talks about it, \"positive\", \"neutral\", or \"negative\".\n"
    "- recommended: true if the answer actively recommends / suggests / endorses it, otherwise false.\n"
    "Only judge based on the provided answer text. Return ONLY JSON: {\"results\": [{\"key\": str, \"sentiment\": str, \"recommended\": bool}]}."
)


def resolve_subject(cfg: Config, args: argparse.Namespace) -> dict[str, Any]:
    """Brand, aliases, owned domains, competitors, topics — from a publication's strategy or from flags/config."""
    subject: dict[str, Any] = {"slug": "main", "brand": args.brand, "aliases": list(args.alias or []), "domains": list(args.domain or []),
                               "competitors": [], "topics": list(args.topic or []), "publication_domains": []}
    if args.publication or (not args.brand and publication.list_publications(cfg)):
        root = publication.find_publication(cfg, args.publication)
        pub = publication.load_publication(root)
        strategy = pubstate.load_strategy(root)
        client = strategy.get("client") or {}
        subject.update({"slug": root.name, "brand": subject["brand"] or client.get("name"),
                        "aliases": subject["aliases"] or list(client.get("aliases") or []),
                        "domains": subject["domains"] or [d for d in [client.get("domain")] if d],
                        "publication_domains": [pub.host] + [urlparse(str(p.get("site_url"))).netloc.removeprefix("www.")
                                                             for p in (cfg.site.get("publications") or []) if isinstance(p, dict) and p.get("site_url")],
                        "competitors": [{"key": f"comp-{i}", "name": c.get("name") or c.get("domain"), "domain": c.get("domain"),
                                         "aliases": list(c.get("aliases") or [])} for i, c in enumerate(strategy.get("competitors") or []) if c.get("name") or c.get("domain")],
                        "topics": subject["topics"] or [t.get("phrase") for t in strategy.get("ranking_targets") or [] if t.get("phrase")]
                        or list(strategy.get("priority_topics") or [])[:3]})
    for spec in args.competitor or []:
        name, _, domain = spec.partition("=")
        subject["competitors"].append({"key": f"comp-{len(subject['competitors'])}", "name": name.strip(), "domain": domain.strip() or None, "aliases": []})
    if not subject["topics"]:
        subject["topics"] = [t.strip() for t in (cfg.site.get("geo_topics") or []) if t and str(t).strip()]
    if not subject["brand"]:
        host = urlparse(cfg.site.get("site_url") or cfg.env.get("SEO_SITE_URL", "")).netloc.removeprefix("www.")
        subject["brand"] = host.split(".")[0] if host else None
        subject["domains"] = subject["domains"] or ([host] if host else [])
    return subject


def generate_variations(cfg: Config, topic: str, brand_description: str, count: int) -> list[dict[str, Any]]:
    user = (f"Topic: {topic}\nThe company being monitored (context only — NEVER name it in the questions): {brand_description}\n\n"
            f"Generate {count} distinct questions a person might ask an AI assistant related to this topic. Return a JSON array.")
    data = llm.complete_json(cfg, VARIATION_SYSTEM, user, tier="cheap", max_tokens=2000)
    out = []
    for item in data if isinstance(data, list) else data.get("questions", []):
        if isinstance(item, str):
            out.append({"text": item.strip(), "specificity": None})
        elif isinstance(item, dict) and item.get("question"):
            spec = item.get("specificity")
            out.append({"text": str(item["question"]).strip(), "specificity": spec if spec in ("general", "mid", "niche") else None})
    seen: set[str] = set()
    unique = []
    for v in out:
        key = v["text"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(v)
    return unique[:count]


def enrich(cfg: Config, question: str, answer: str, entities: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    if not entities:
        return {}
    listing = "\n".join(f'- key="{e["key"]}" name="{e["name"]}"' for e in entities)
    user = f"QUESTION ASKED:\n{question}\n\nAI ASSISTANT ANSWER:\n\"\"\"\n{answer[:6000]}\n\"\"\"\n\nENTITIES TO JUDGE:\n{listing}"
    try:
        data = llm.complete_json(cfg, ANALYZE_SYSTEM, user, tier="cheap", max_tokens=700)
    except llm.LlmError:
        return {e["key"]: {"sentiment": "neutral", "recommended": False} for e in entities}
    by_key = {e["key"]: e for e in entities}
    by_name = {e["name"].lower(): e for e in entities}
    out: dict[str, dict[str, Any]] = {}
    for row in (data.get("results") if isinstance(data, dict) else data) or []:
        if not isinstance(row, dict):
            continue
        ent = None
        for candidate in (row.get("key"), row.get("name"), row.get("entity")):
            if candidate and str(candidate) in by_key:
                ent = by_key[str(candidate)]
                break
            if candidate and str(candidate).lower() in by_name:
                ent = by_name[str(candidate).lower()]
                break
        if ent is None or ent["key"] in out:
            continue
        sentiment = row.get("sentiment") if row.get("sentiment") in ("positive", "neutral", "negative") else "neutral"
        out[ent["key"]] = {"sentiment": sentiment, "recommended": bool(row.get("recommended"))}
    for e in entities:
        out.setdefault(e["key"], {"sentiment": "neutral", "recommended": False})
    return out


def owned_host(url: str, owned: list[str]) -> bool:
    host = urlparse(url or "").netloc.lower().removeprefix("www.")
    return any(host == d or host.endswith("." + d) for d in owned if d)


def summarize(responses: list[dict[str, Any]], entity_names: dict[str, str]) -> dict[str, Any]:
    """Lettertrace's computeEntityStats / citation / measurement quality, over all responses of a run."""
    total = len(responses)
    per_entity: dict[str, dict[str, Any]] = {}
    grand_total = 0
    for r in responses:
        for key, hit in (r.get("mentions") or {}).items():
            if not hit.get("mentioned"):
                continue
            e = per_entity.setdefault(key, {"responses": 0, "count": 0, "positions": [], "recommended": 0, "pos": 0, "neu": 0, "neg": 0})
            e["responses"] += 1
            e["count"] += int(hit.get("count", 0))
            grand_total += int(hit.get("count", 0))
            if hit.get("first_position", -1) >= 0:
                e["positions"].append(1 - float(hit["first_position"]))
            enrich_row = (r.get("enrichment") or {}).get(key) or {}
            e["recommended"] += bool(enrich_row.get("recommended"))
            e[{"positive": "pos", "neutral": "neu", "negative": "neg"}.get(enrich_row.get("sentiment", "neutral"), "neu")] += 1
    entities = []
    for key in ["brand", *sorted(k for k in entity_names if k != "brand")]:
        e = per_entity.get(key, {"responses": 0, "count": 0, "positions": [], "recommended": 0, "pos": 0, "neu": 0, "neg": 0})
        judged = e["pos"] + e["neu"] + e["neg"]
        entities.append({
            "key": key, "name": entity_names.get(key, key), "responses_mentioned": e["responses"],
            "mention_rate": stats.rate(e["responses"], total), "total_mention_count": e["count"],
            "share_of_voice": round(e["count"] / grand_total, 4) if grand_total else 0.0,
            "avg_prominence": round(sum(e["positions"]) / len(e["positions"]), 4) if e["positions"] else None,
            "recommend_rate": round(e["recommended"] / e["responses"], 4) if e["responses"] else 0.0,
            "sentiment": {"positive": e["pos"], "neutral": e["neu"], "negative": e["neg"]},
            "sentiment_score": round((e["pos"] - e["neg"]) / judged, 4) if judged else 0.0,
        })
    entities.sort(key=lambda x: (x["key"] != "brand", -x["share_of_voice"]))
    owned_responses = sum(1 for r in responses if any(c.get("owned") for c in r.get("citations", [])))
    owned_urls = {c["url"] for r in responses for c in r.get("citations", []) if c.get("owned") and c.get("url")}
    informative = sum(1 for r in responses if any(h.get("mentioned") for h in (r.get("mentions") or {}).values()))
    informative_rate = stats.rate(informative, total)
    brand = entities[0] if entities and entities[0]["key"] == "brand" else None
    if total == 0:
        verdict = "no-data"
    elif len(entity_names) <= 1:
        verdict = "no-competitors"
    elif total < 10 or informative_rate["hi"] < LOW_INFORMATIVE_RATE:
        verdict = "thin-sample"
    elif not (brand and brand["responses_mentioned"]):
        verdict = "sampled-absence"
    else:
        verdict = "sampled-presence"
    return {"total_responses": total, "entities": entities,
            "owned_citation_rate": stats.rate(owned_responses, total), "distinct_owned_urls": sorted(owned_urls),
            "informative_rate": informative_rate, "measurement_verdict": verdict}


def per_prompt(responses: list[dict[str, Any]], entity_names: dict[str, str]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in responses:
        groups.setdefault(r["prompt"], []).append(r)
    out = []
    for prompt, rs in groups.items():
        ents = {}
        for key, name in entity_names.items():
            hits = sum(1 for r in rs if (r.get("mentions") or {}).get(key, {}).get("mentioned"))
            ents[key] = {"name": name, "mention_rate": round(hits / len(rs), 4), "hits": hits, "asks": len(rs)}
        comp_best = max((v["mention_rate"] for k, v in ents.items() if k != "brand"), default=0.0)
        out.append({"prompt": prompt, "topic": rs[0].get("topic"), "specificity": rs[0].get("specificity"), "responses": len(rs),
                    "entities": ents, "competitor_wins": len(rs) >= 10 and max((stats.rate(v["hits"], len(rs))["lo"] for k, v in ents.items() if k != "brand"), default=0) > stats.rate(ents.get("brand", {}).get("hits", 0), len(rs))["hi"]})
    out.sort(key=lambda x: -max((v["mention_rate"] for k, v in x["entities"].items() if k != "brand"), default=0))
    return out


def per_page(responses: list[dict[str, Any]], owned: list[str]) -> list[dict[str, Any]]:
    pages: dict[str, int] = {}
    for r in responses:
        seen = set()
        for c in r.get("citations", []):
            url = str(c.get("url") or "")
            if c.get("owned") and url and url not in seen:
                seen.add(url)
                key = urlparse(url).netloc.removeprefix("www.") + urlparse(url).path.rstrip("/")
                pages[key] = pages.get(key, 0) + 1
    total = len(responses)
    return sorted(({"page": k, "responses_citing": n, "cited_rate": stats.rate(n, total)} for k, n in pages.items()),
                  key=lambda x: -x["responses_citing"])[:30]


def main() -> int:
    parser = argparse.ArgumentParser(description="Track brand mentions, share of voice and owned citations across AI assistants.")
    parser.add_argument("--publication", help="Use a publication's strategy (client, competitors, ranking targets) as the subject")
    parser.add_argument("--brand", help="Brand name (default: publication client, else site host)")
    parser.add_argument("--alias", action="append", help="Brand alias (repeatable)")
    parser.add_argument("--domain", action="append", help="Owned domain (repeatable)")
    parser.add_argument("--competitor", action="append", help='Competitor as "Name=domain" (repeatable)')
    parser.add_argument("--topic", action="append", help="Topic to generate prompts for (repeatable)")
    parser.add_argument("--variations", type=int, default=DEFAULT_VARIATIONS, help=f"Prompts per topic (default {DEFAULT_VARIATIONS}, max 20)")
    parser.add_argument("--generate", action="store_true", help="(Re)generate prompt variations for the topics")
    parser.add_argument("--replicates", type=int, default=1, help="Independent samples per prompt x provider (1-10)")
    parser.add_argument("--providers", help="Comma list to restrict providers (default: every configured)")
    parser.add_argument("--max-prompts", type=int, default=40, help="Cap on prompts per run (cost guard)")
    parser.add_argument("--no-enrich", action="store_true", help="Skip sentiment/recommended enrichment")
    parser.add_argument("--dry-run", action="store_true", help="Show prompts, providers and cost; make no probe calls")
    parser.add_argument("--publications-dir", help="Override the publications directory")
    args = parser.parse_args()

    cfg = config_module.load()
    if args.publications_dir:
        cfg.site["publications_dir"] = args.publications_dir
    if not 1 <= args.replicates <= 10:
        parser.error("--replicates must be 1..10")
    subject = resolve_subject(cfg, args)
    if not subject["brand"]:
        print(json.dumps({"checked": False, "error": "no brand to track — pass --brand or --publication"}, indent=2))
        return 1
    providers = [p for p in PROVIDER_ORDER if ai_visibility._provider_configured(cfg, p)]
    if args.providers:
        wanted = {p.strip() for p in args.providers.split(",")}
        providers = [p for p in providers if p in wanted]
    state_path = pubstate.state_path(cfg, "mentions", subject["slug"])
    state = pubstate.load_json(state_path, {"prompts": [], "runs": []})
    notes: list[str] = []

    if args.generate or not state.get("prompts"):
        if not subject["topics"]:
            print(json.dumps({"checked": False, "error": "no topics — pass --topic, set ranking_targets in strategy.yml, or geo_topics in config.yml"}, indent=2))
            return 1
        if not llm.configured_providers(cfg):
            print(json.dumps({"checked": False, "error": "prompt generation needs an LLM key (or write prompts into the state file by hand)"}, indent=2))
            return 1
        prompts = []
        for topic in subject["topics"]:
            for v in generate_variations(cfg, topic, f"{subject['brand']} ({', '.join(subject['domains'])})", min(20, args.variations)):
                prompts.append({"topic": topic, "text": v["text"], "specificity": v["specificity"], "active": True})
        state["prompts"] = prompts
        notes.append(f"generated {len(prompts)} prompts for {len(subject['topics'])} topic(s)")
    prompts = [p for p in state.get("prompts", []) if p.get("active", True)][: args.max_prompts]
    entity_terms = {"brand": mentions.brand_terms(subject["brand"], subject["aliases"])}
    entity_names = {"brand": subject["brand"]}
    for c in subject["competitors"]:
        entity_terms[c["key"]] = mentions.brand_terms(c["name"], c.get("aliases"))
        entity_names[c["key"]] = c["name"]
    owned = [d for d in subject["domains"] + subject["publication_domains"] if d]
    calls = len(prompts) * len(providers) * args.replicates
    plan = {"checked": True, "subject": {k: v for k, v in subject.items() if k != "competitors"}, "competitors": [c["name"] for c in subject["competitors"]],
            "providers": providers, "prompts": len(prompts), "replicates": args.replicates,
            "cost_note": f"{calls} billed web-search LLM calls + up to {calls} cheap enrichment calls", "notes": notes}
    if args.dry_run or not providers:
        plan["prompt_list"] = prompts
        if not providers:
            plan["notes"].append("no probe provider configured (OPENAI_API_KEY / ANTHROPIC_API_KEY / PERPLEXITY_API_KEY / GOOGLE_GEMINI_API_KEY)")
        pubstate.save_json(state_path, state)
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        return 0

    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    responses: list[dict[str, Any]] = []
    errors = 0
    for p in prompts:
        for name in providers:
            for _ in range(args.replicates):
                try:
                    outcome = ai_visibility.PROBERS[name](cfg, p["text"])
                except Exception as exc:  # noqa: BLE001 — a provider error is an unknown, never a non-mention
                    errors += 1
                    responses.append({"prompt": p["text"], "topic": p["topic"], "specificity": p.get("specificity"), "provider": name,
                                      "error": http_util.sanitize_text(str(exc))[:200]})
                    continue
                text = ai_visibility.answer_text(name, outcome.get("raw") or {})
                hits = mentions.detect_entities(text, entity_terms)
                detected = [{"key": k, "name": entity_names[k]} for k, h in hits.items() if h.get("mentioned")]
                enrichment = {} if args.no_enrich or not detected or not llm.configured_providers(cfg) else enrich(cfg, p["text"], text, detected)
                citations = [{"url": c.get("url"), "title": c.get("title"), "owned": owned_host(str(c.get("url") or ""), owned)
                              or (not c.get("url") and any(ai_visibility.citation_matches(c, d) for d in owned))} for c in outcome.get("citations", [])]
                responses.append({"prompt": p["text"], "topic": p["topic"], "specificity": p.get("specificity"), "provider": name,
                                  "answer_chars": len(text), "mentions": hits, "enrichment": enrichment, "citations": citations})
    valid = [r for r in responses if "error" not in r]
    summary = summarize(valid, entity_names)
    design = {'prompts': prompts, 'providers': providers, 'replicates': args.replicates,
              'entities': entity_terms, 'owned': owned,
              'implementation': hashlib.sha256(Path(ai_visibility.__file__).read_bytes()).hexdigest()}
    signature = hashlib.sha256(json.dumps(design, sort_keys=True).encode()).hexdigest()
    run = {"measurement_kind": "api_probe_not_consumer_traffic", "design_signature": signature, "run_id": run_id, "at": pubstate.now_iso(), "providers": providers, "replicates": args.replicates, "prompts": len(prompts),
           "responses": len(valid), "errors": errors, "summary": summary, "per_prompt": per_prompt(valid, entity_names),
           "per_page": per_page(valid, owned)}
    previous = state["runs"][-1] if state.get("runs") else None
    state["runs"] = (state.get("runs", []) + [run])[-52:]
    brand = summary["entities"][0] if summary["entities"] else {}
    if brand.get("responses_mentioned") and not state.get("first_mention_at"):
        state["first_mention_at"] = run["at"]
    pubstate.save_json(state_path, state)
    trend = None
    if previous and not errors and not previous.get("errors") and previous.get("design_signature") == signature and min(len(valid), previous.get("responses", 0)) >= 10:
        prev_brand = (previous.get("summary") or {}).get("entities", [{}])[0]
        trend = {"previous_run": previous.get("run_id"), "mention_rate": [prev_brand.get("mention_rate", {}).get("point"), brand.get("mention_rate", {}).get("point")],
                 "owned_citation_rate": [(previous.get("summary") or {}).get("owned_citation_rate", {}).get("point"), summary["owned_citation_rate"]["point"]]}
    report = {**plan, "run_id": run_id, "responses": len(valid), "provider_errors": errors, "summary": summary,
              "questions_competitors_win": [p for p in run["per_prompt"] if p["competitor_wins"]][:15], "cited_pages": run["per_page"],
              "trend": trend, "trend_note": "Only identical complete probe designs with at least ten responses are compared; samples may be correlated and not representative of consumers.", "first_mention_at": state.get("first_mention_at"), "state_file": str(state_path),
              "next_step": "pub-monitor report_performance.py --sync-geo turns competitor-won prompts into the GEO signal for pub-curate" if subject["slug"] != "main" else None}
    out = pubstate.report_path(cfg, "mentions", subject["slug"])
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    report["report_file"] = str(out)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
