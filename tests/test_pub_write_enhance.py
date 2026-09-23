"""pub-write / pub-enhance / pub-research: offline tests with fake LLM and
fake pages. The kernel/judge/verifier contracts are what matter here."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import yaml

REPO = Path(__file__).resolve().parent.parent


def _load(script: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(script.stem + "_mod", script)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


research_mod = _load(REPO / "skills/pub-research/scripts/research_outline.py")
write_mod = _load(REPO / "skills/pub-write/scripts/write_article.py")
shred_mod = _load(REPO / "skills/pub-write/scripts/shred.py")
enhance_mod = _load(REPO / "skills/pub-enhance/scripts/enhance_article.py")
relink_mod = _load(REPO / "skills/pub-enhance/scripts/relink.py")

from scripts.lib import article, publication, pubstate
from scripts.lib.config import Config

SOURCE_TEXT = ("US spending on AI search ads is set to jump from $2.08 billion in 2026, just 1.3% of total US search ad spending, "
               "to $25.93 billion by 2029, when it will make up 13.6% of the market, according to eMarketer. " * 6)
LANDING_TEXT = ("ChatGPT launched ads in February 2026 at $25 to $60 CPM according to thrad's publisher guide. " * 12)


def _repo(tmp_path: Path, **env) -> tuple[Config, Path]:
    (tmp_path / ".seo-engine").mkdir()
    root = tmp_path / "publications" / "llm-billboard"
    for sub in ("posts", "drafts", "assets"):
        (root / sub).mkdir(parents=True)
    (root / "site.yml").write_text(yaml.safe_dump({
        "name": "LLM Billboard", "slug": "llm-billboard", "tagline": "Conversational AI advertising.", "site_url": "https://llmbillboard.com",
        "sections": [{"slug": "ai-search", "name": "AI Search"}, {"slug": "advertiser-strategy", "name": "Advertiser Strategy"}],
        "authors": [{"slug": "ezra-mbeki", "name": "Ezra Mbeki", "role": "Features Editor"}], "client": {"name": "thrad", "domain": "thrad.ai"},
    }), encoding="utf-8")
    strategy = pubstate.load_strategy(root)
    strategy["client"].update({"name": "thrad", "domain": "thrad.ai", "description": "the DSP for LLMs"})
    strategy["direction"] = "how advertisers prepare for AI search"
    strategy["landings"] = [{"url": "https://www.thrad.ai/content/integrating-ads", "context": "advertiser readiness for the AI search transition: CPM ranges and ad formats inside LLM chat interfaces"}]
    strategy["mention"] = {"degree": "subtle", "rate": 0.5}
    pubstate.save_strategy(root, strategy)
    cfg = Config(repo_root=tmp_path, env=dict(env), site={"publications_dir": "publications"})
    return cfg, root


def _run(mod: ModuleType, cfg: Config, argv: list[str], monkeypatch, capsys) -> dict:
    monkeypatch.setattr(mod.config_module, "load", lambda *a, **k: cfg)
    monkeypatch.setattr(sys, "argv", ["x", *argv])
    code = mod.main()
    out = json.loads(capsys.readouterr().out)
    out["_exit"] = code
    return out


def _llm(fake_transport, replies: list[dict]):
    """Queue OpenRouter replies in order (each a JSON-able object), replacing any earlier OpenRouter route."""
    fake_transport._routes = [r for r in fake_transport._routes if not r["prefix"].startswith("https://openrouter.ai")]
    fake_transport.route("POST", "https://openrouter.ai/api/v1/chat/completions", *[
        {"body": json.dumps({"choices": [{"message": {"content": json.dumps(r)}, "finish_reason": "stop"}], "usage": {}})} for r in replies])


def test_article_helpers():
    p = "Spending rises from $2.08 billion in 2026 to $25.93 billion by 2029, per eMarketer."
    out, changed = article.anchor_number(p, "$2.08 billion", "https://e.com/x")
    assert changed and "[$2.08 billion](https://e.com/x)" in out
    out2, changed2 = article.anchor_number(out, "$2.08 billion", "https://e.com/x")
    assert not changed2
    phrase = article.find_anchor_phrase("Most teams still run keyword taxonomies to intent-topic frameworks badly.",
                                        "Keyword Taxonomies to Intent-Topic Frameworks for Search Advertisers")
    assert phrase and phrase.lower().startswith("keyword taxonomies")
    assert article.numbers_in("13.6% of $25.93 billion, or 2,000 units") == {"13.6%", "25.93", "2000"}
    md, removed = article.strip_links_to_host("see [rate](https://www.thrad.ai/x) and [other](https://e.com)", "thrad.ai")
    assert removed == 1 and "[other](https://e.com)" in md and "thrad.ai" not in md
    assert article.guard_unchanged("A 13.6% rise. [x](https://a)", "A 12% rise.") == ["numbers lost: ['13.6%']", "numbers added: ['12%']", "links lost: ['https://a']"] or article.guard_unchanged("A 13.6% rise. [x](https://a)", "A 12% rise.")


def test_research_write_enhance_pipeline(tmp_path, monkeypatch, capsys, fake_transport):
    cfg, root = _repo(tmp_path, OPENROUTER_API_KEY="sk", FIRECRAWL_API_KEY="fc")
    fake_transport.route("POST", "https://api.firecrawl.dev/v2/search", {"body": json.dumps({"data": [
        {"url": "https://www.emarketer.com/content/ai-search-ads", "title": "AI search ads surge"},
        {"url": "https://www.thrad.ai/content/other-page", "title": "thrad other"}]})})
    fake_transport.route("GET", "https://www.thrad.ai/content/integrating-ads", {"body": f"<html><title>Integrating ads</title><body><article>{LANDING_TEXT}</article></body></html>", "headers": {"Content-Type": "text/html"}})
    fake_transport.route("GET", "https://www.emarketer.com/content/ai-search-ads", {"body": f"<html><title>AI search ads surge</title><body><article>{SOURCE_TEXT}</article></body></html>", "headers": {"Content-Type": "text/html"}})
    outline = {"title": "Advertiser Readiness Assessment for the AI Search Transition", "dek": "Most advertisers lack the chops for AI search.",
               "opening": {"claim": "AI search ad spend rises from $2.08 billion in 2026 to $25.93 billion by 2029",
                           "quote": "jump from $2.08 billion in 2026, just 1.3% of total US search ad spending, to $25.93 billion by 2029", "source": 2},
               "sections": [
                   {"heading": "AI search differs structurally from the results page advertisers know", "goal": "contrast",
                    "points": [{"claim": "ChatGPT ads launched at $25 to $60 CPM", "quote": "ChatGPT launched ads in February 2026 at $25 to $60 CPM", "source": 1},
                               {"claim": "made up 13.6% share", "quote": "it will make up 13.6% of the market", "source": 2},
                               {"claim": "fabricated", "quote": "this sentence exists nowhere", "source": 2}]},
                   {"heading": "What should advertisers do before 2029?", "goal": "advice", "points": [
                       {"claim": "share is 1.3%", "quote": "just 1.3% of total US search ad spending", "source": 2}]}],
               "closing_advice": ["start with tagging"], "diagrams": [{"title": "AI Search Ad Spend: From 1.3% to 13.6%", "brief": "Show the share trajectory.",
                                                                         "type": "stat_callout", "data": {"from": "1.3%", "to": "13.6%"}}], "keywords": ["ai search ads"]}
    _llm(fake_transport, [
        {"queries": ["AI search ad spend 2029"], "must_cover": ["measurement"], "entities": ["eMarketer"]},
        {"options": [{"thesis": "readiness is four dimensions", "framework": "scorecard", "why_now": "spend shift"}], "recommended": 0},
        outline,
    ])
    res = _run(research_mod, cfg, ["--publication", "llm-billboard", "--topic", "Advertiser readiness for the AI search transition"], monkeypatch, capsys)
    assert res["_exit"] == 0 and res["status"] == "awaiting_interview", res
    from content_helpers import approved
    from scripts.lib import content
    draft_slug = "advertiser-readiness-for-the-ai-search-transition"
    pending, _ = publication.read_post(root / "drafts" / f"{draft_slug}.md")
    approved(tmp_path, content.publication_id(root, draft_slug), pending['research'])
    res = _run(research_mod, cfg, ["--publication", "llm-billboard", "--slug", draft_slug], monkeypatch, capsys)
    assert res["_exit"] == 0 and res["status"] == "done", res
    assert res["sources_read"] == 2 and res["claims_dropped"] == 1 and res["claims_verified"] == 4
    meta, body = publication.read_post(root / "drafts" / "advertiser-readiness-for-the-ai-search-transition.md")
    assert meta["title"].startswith("Advertiser Readiness") and [s["url"] for s in meta["sources"]] == [
        "https://www.thrad.ai/content/integrating-ads", "https://www.emarketer.com/content/ai-search-ads"]
    assert meta["research"]["sources"][0]["origin"] == "client_landing"
    assert all("other-page" not in s["url"] for s in meta["research"]["sources"])

    slug = "advertiser-readiness-for-the-ai-search-transition"
    sec1 = ("Legacy search runs on a keyword that triggers a slot. ChatGPT launched ads in February 2026 at $25 to $60 CPM, "
            "and AI search will make up 13.6% of the market by 2029, per eMarketer. " * 5)
    sec2 = "If measurement is the gap, start with tagging. The share is 1.3% today and the window is open. " * 6
    _llm(fake_transport, [
        {"opening": "US spending on AI search ads will jump from $2.08 billion in 2026 to $25.93 billion by 2029, according to eMarketer.\n\nReadiness splits across four dimensions."},
        {"candidates": [sec1, sec1 + " Second version."]}, {"winner": 1, "scores": [7, 8], "notes": "tighter"},
        {"candidates": [sec2, sec2]}, {"winner": 0, "scores": [8, 8], "notes": "same"},
    ])
    w = _run(write_mod, cfg, ["--publication", "llm-billboard", "--slug", slug, "--candidates", "2"], monkeypatch, capsys)
    assert w["_exit"] == 0 and w["sections"] == 2 and w["numeric_anchors"] >= 3, w
    assert w["mention"]["allowed"] is True and w["mention"]["applied"] is True and "thrad.ai" in w["mention"]["landing_url"]
    assert w["judge"][0]["winner"] == 1
    meta, body = publication.read_post(root / "drafts" / f"{slug}.md")
    assert body.count("## ") == 2 and "[$2.08 billion](https://www.emarketer.com/content/ai-search-ads)" in body
    assert body.count("thrad.ai") == 1 and meta["status"] == "written"
    assert len(meta['writing_example_ids']) == 6
    calls = [c for c in fake_transport.calls if 'openrouter.ai' in c[1]]
    assert any('FROZEN HUMAN WRITING REFERENCES' in json.dumps(c[2]) for c in calls)

    publication.write_post(root / "posts" / "keyword-to-prompt.md", {
        "title": "Keyword Taxonomies to Intent-Topic Frameworks for Search Advertisers", "slug": "keyword-to-prompt", "dek": "Translate keywords into prompts.",
        "section": "AI Search", "author": "ezra-mbeki", "published_at": "2026-08-29T20:00:00Z"}, "## Intent topic frameworks\n\nBody about keyword taxonomies.")
    meta, body = publication.read_post(root / "drafts" / f"{slug}.md")
    body += "\n\nTeams still map keyword taxonomies to intent-topic frameworks by hand, and 42% of them fail."
    publication.write_post(root / "drafts" / f"{slug}.md", meta, body)
    e = _run(enhance_mod, cfg, ["--publication", "llm-billboard", "--slug", slug, "--stages", "links,sources,anchors,diagrams,verify,meta"], monkeypatch, capsys)
    assert e["_exit"] == 0 and e["links"]["inserted"] and e["links"]["inserted"][0]["target"] == "keyword-to-prompt"
    assert "42%" in e["verify"]["unverified"] and "13.6%" not in e["verify"]["unverified"]
    assert e["diagrams"]["specs_written"] and (root / "assets" / slug / "diagram-1.json").is_file()
    meta, body = publication.read_post(root / "drafts" / f"{slug}.md")
    assert "](/posts/keyword-to-prompt)" in body and "![Diagram: AI Search Ad Spend" in body
    assert meta["sources"][0]["url"].startswith("https://") and meta["reading_minutes"] >= 1
    strict = _run(enhance_mod, cfg, ["--publication", "llm-billboard", "--slug", slug, "--stages", "verify", "--strict-verify"], monkeypatch, capsys)
    assert strict["_exit"] == 1

    strategy = pubstate.load_strategy(root)
    strategy["mention"]["degree"] = "off"
    pubstate.save_strategy(root, strategy)
    _llm(fake_transport, [
        {"opening": "Opening with $2.08 billion, per eMarketer."},
        {"candidates": ["ChatGPT launched ads at [$25 to $60](https://www.thrad.ai/content/integrating-ads) CPM. " * 8]},
        {"candidates": ["Closing. The share is 1.3% today. " * 8]},
    ])
    w2 = _run(write_mod, cfg, ["--publication", "llm-billboard", "--slug", slug, "--candidates", "1", "--force"], monkeypatch, capsys)
    assert w2["mention"]["allowed"] is False and w2["mention"]["stripped"] == 8
    _, body2 = publication.read_post(root / "drafts" / f"{slug}.md")
    assert "thrad.ai" not in body2


def test_relink_bumps_only_changed_posts(tmp_path, monkeypatch, capsys):
    cfg, root = _repo(tmp_path)
    publication.write_post(root / "posts" / "old-post.md", {"title": "Old Post", "slug": "old-post", "dek": "d", "section": "AI Search",
                                                            "author": "ezra-mbeki", "published_at": "2026-08-01T00:00:00Z", "updated_at": "2026-08-01T00:00:00Z"},
                           "Intent signal decay shapes multi-turn AI conversations more than anyone expects.\n\nUnrelated paragraph about cats.")
    publication.write_post(root / "posts" / "unrelated.md", {"title": "Unrelated", "slug": "unrelated", "dek": "d", "section": "AI Search",
                                                             "author": "ezra-mbeki", "published_at": "2026-08-02T00:00:00Z", "updated_at": "2026-08-02T00:00:00Z"},
                           "Quarterly budget planning for programmatic buyers.")
    publication.write_post(root / "posts" / "intent-decay.md", {"title": "Intent Signal Decay in Multi-Turn AI Conversations", "slug": "intent-decay",
                                                                "dek": "Signals dissolve within two turns.", "section": "AI Search", "author": "ezra-mbeki",
                                                                "published_at": "2026-09-01T00:00:00Z"}, "## Why signals decay\n\nBody.")
    dry = _run(relink_mod, cfg, ["--publication", "llm-billboard", "--dry-run"], monkeypatch, capsys)
    assert dry["new_post"] == "intent-decay" and [c["post"] for c in dry["changes"]] == ["old-post"]
    meta, _ = publication.read_post(root / "posts" / "old-post.md")
    assert meta["updated_at"] == "2026-08-01T00:00:00Z"
    real = _run(relink_mod, cfg, ["--publication", "llm-billboard"], monkeypatch, capsys)
    assert real["changes"][0]["updated_at_bumped"] is False
    assert real["changes"][0]["review_draft"]
    meta, body = publication.read_post(root / "posts" / "old-post.md")
    assert "](/posts/intent-decay)" not in body and meta["updated_at"] == "2026-08-01T00:00:00Z"
    draft_meta, draft_body = publication.read_post(root / "drafts/old-post.md")
    assert "](/posts/intent-decay)" in draft_body and draft_meta["refresh_of"] == "old-post"
    meta_u, _ = publication.read_post(root / "posts" / "unrelated.md")
    assert meta_u["updated_at"] == "2026-08-02T00:00:00Z"
    again = _run(relink_mod, cfg, ["--publication", "llm-billboard"], monkeypatch, capsys)
    assert again["changes"][0]["skipped"] == "existing draft preserved"


def test_shred_keeps_facts_and_structure(tmp_path, monkeypatch, capsys, fake_transport):
    cfg, root = _repo(tmp_path, OPENROUTER_API_KEY="sk")
    body = ("## Heading stays\n\nSpending will reach $25.93 billion by 2029, per [eMarketer](https://e.com/x). Buyers should plan for that shift now. "
            "A third sentence describes the auction mechanics in plain words.\n\n- list item stays\n")
    publication.write_post(root / "drafts" / "piece.md", {"title": "Piece", "slug": "piece", "composition": {"provider": "openrouter", "model": "anthropic/claude-sonnet-4.6"}}, body)
    _llm(fake_transport, [
        {"sentence": "Spending will reach a lot by 2029, per [eMarketer](https://e.com/x)."},
        {"sentence": "By 2029 spending will reach $25.93 billion, per [eMarketer](https://e.com/x)."},
        {"sentence": "Buyers ought to plan for that shift today."},
        {"sentence": "A third sentence explains the auction mechanics in everyday words."},
    ])
    out = _run(shred_mod, cfg, ["--publication", "llm-billboard", "--slug", "piece", "--coverage", "1.0", "--seed", "1"], monkeypatch, capsys)
    assert out["status"] == "shredded" and out["guard"] == [], out
    assert out["summary"]["kept_original"] + out["summary"]["shredded"] == 3
    _, new_body = publication.read_post(root / "drafts" / "piece.md")
    assert "## Heading stays" in new_body and "- list item stays" in new_body and "$25.93 billion" in new_body and "https://e.com/x" in new_body
    assert "a lot by 2029" not in new_body
    log = pubstate.load_json(pubstate.state_path(cfg, "shred", "llm-billboard"))
    assert log["runs"][-1]["status"] == "shredded"


def test_shred_rotates_models_with_one_account(tmp_path):
    from scripts.lib import llm
    import pytest
    cfg = Config(repo_root=tmp_path, env={"OPENROUTER_API_KEY": "test", "LLM_REWRITE_MODELS": "a/one,b/two,a/one"}, site={})
    assert shred_mod.model_rotation(cfg, "a/one") == ["b/two"]
    cfg.env["LLM_REWRITE_MODELS"] = "a/one"
    with pytest.raises(llm.LlmError, match="different from the writer"):
        shred_mod.model_rotation(cfg, "a/one")
