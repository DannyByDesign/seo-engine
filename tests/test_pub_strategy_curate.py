"""pub-strategy + pub-curate: offline tests through the fake transport.
Script modules are imported by path (they bootstrap sys.path themselves)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent


def _load(script: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(script.stem + "_mod", script)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


positioning = _load(REPO / "skills/pub-strategy/scripts/positioning.py")
scrape = _load(REPO / "skills/pub-strategy/scripts/scrape_competitors.py")
topic_map_mod = _load(REPO / "skills/pub-curate/scripts/build_topic_map.py")
scoring = _load(REPO / "skills/pub-curate/scripts/score_suggestions.py")
seers_mod = _load(REPO / "skills/pub-curate/scripts/seers.py")

from scripts.lib import publication, pubstate
from scripts.lib.config import Config


def _repo(tmp_path: Path, **env) -> tuple[Config, Path]:
    (tmp_path / ".seo-engine").mkdir()
    root = tmp_path / "publications" / "adsinllms"
    (root / "posts").mkdir(parents=True)
    (root / "drafts").mkdir()
    (root / "site.yml").write_text(yaml.safe_dump({
        "name": "Ads in LLMs", "slug": "adsinllms", "tagline": "Tactical guide to buying placements inside LLMs.",
        "site_url": "https://adsinllms.com", "theme": "forum",
        "sections": [{"slug": "campaign-setup", "name": "Campaign Setup", "description": "Seats, deal IDs, taxonomy, QA."},
                     {"slug": "features", "name": "Features"}],
        "authors": [{"slug": "kwame-contreras", "name": "Kwame Contreras", "role": "Senior Writer"}],
        "client": {"name": "thrad", "domain": "thrad.ai"},
    }), encoding="utf-8")
    cfg = Config(repo_root=tmp_path, env={k: v for k, v in env.items()}, site={"publications_dir": "publications"})
    return cfg, root


def _run(mod: ModuleType, cfg: Config, argv: list[str], monkeypatch, capsys) -> dict:
    monkeypatch.setattr(mod.config_module, "load", lambda *a, **k: cfg)
    monkeypatch.setattr(sys, "argv", ["x", *argv])
    code = mod.main()
    out = json.loads(capsys.readouterr().out)
    out["_exit"] = code
    return out


def test_positioning_sets_validates_and_applies(tmp_path, monkeypatch, capsys, fake_transport):
    cfg, root = _repo(tmp_path, ANTHROPIC_API_KEY="sk-ant")
    out = _run(positioning, cfg, ["--publication", "adsinllms", "--direction", "how trading desks buy LLM placements",
                                  "--mention-degree", "subtle", "--mention-rate", "0.1"], monkeypatch, capsys)
    strategy = pubstate.load_strategy(root)
    assert out["written"] and strategy["client"] == {"name": "thrad", "domain": "thrad.ai", "description": "", "slogan": ""}
    assert strategy["direction"].startswith("how trading desks")

    proposal = {"priority_topics": ["LLM ad auctions", "deal IDs for AI inventory"], "stances": ["CPM-first buying is wrong"],
                "avoid_topics": ["thrad funding news"],
                "ranking_targets": [{"phrase": f"target {i}", "basis": "white_space", "mention_framing": "as the DSP option"} for i in range(7)],
                "competitors": [{"name": "AdExchanger", "domain": "https://adexchanger.com/", "reason": "trade press"}],
                "landings": [{"url": "https://www.thrad.ai/content/guide", "context": "when CPM ranges come up"}, {"url": "not-a-url"}]}
    fake_transport.route("POST", "https://api.anthropic.com/v1/messages", {
        "body": json.dumps({"content": [{"type": "text", "text": json.dumps(proposal)}], "stop_reason": "end_turn", "usage": {}})})
    out = _run(positioning, cfg, ["--publication", "adsinllms", "--suggest"], monkeypatch, capsys)
    assert "proposal" in out and len(out["proposal"]["ranking_targets"]) == 5 and "applied" not in out
    assert pubstate.load_strategy(root)["priority_topics"] == []

    out = _run(positioning, cfg, ["--publication", "adsinllms", "--suggest", "--apply", "--validate"], monkeypatch, capsys)
    strategy = pubstate.load_strategy(root)
    assert out["applied"] and strategy["priority_topics"] == ["LLM ad auctions", "deal IDs for AI inventory"]
    assert strategy["competitors"][0]["domain"] == "adexchanger.com" and len(strategy["ranking_targets"]) == 5
    assert [l["url"] for l in strategy["landings"]] == ["https://www.thrad.ai/content/guide"]
    assert out["validation"] == [] and out["_exit"] == 0


def test_scrape_competitors_builds_topic_files(tmp_path, monkeypatch, capsys, fake_transport):
    cfg, root = _repo(tmp_path)
    fake_transport.route("GET", "https://adexchanger.com/robots.txt", {"body": "User-agent: *\nAllow: /\nSitemap: https://adexchanger.com/sitemap.xml\n"})
    fake_transport.route("GET", "https://adexchanger.com/sitemap.xml", {"body": (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        '<url><loc>https://adexchanger.com/blog/llm-ad-auctions-explained</loc></url>'
        '<url><loc>https://adexchanger.com/blog/deal-ids-for-ai-inventory</loc></url>'
        '<url><loc>https://adexchanger.com/tag/ai</loc></url>'
        '<url><loc>https://adexchanger.com/blog/cat-videos</loc></url>'
        '<url><loc>https://adexchanger.com/blog/x1</loc></url><url><loc>https://adexchanger.com/blog/x2</loc></url>'
        '</urlset>'), "headers": {"Content-Type": "application/xml"}})
    page = '<html><head><title>{t}</title><meta name="description" content="d"><meta property="article:published_time" content="2026-09-0{n}T00:00:00Z"></head><body></body></html>'
    for n, (slug, title) in enumerate([("llm-ad-auctions-explained", "LLM ad auctions explained"), ("deal-ids-for-ai-inventory", "Deal IDs for AI inventory"),
                                       ("cat-videos", "Cat videos"), ("x1", "X one"), ("x2", "X two")], start=1):
        fake_transport.route("GET", f"https://adexchanger.com/blog/{slug}", {"body": page.format(t=title, n=n), "headers": {"Content-Type": "text/html"}})
    out = _run(scrape, cfg, ["--publication", "adsinllms", "--domain", "adexchanger.com", "--no-llm", "--no-volume", "--max-pages", "10"], monkeypatch, capsys)
    comp = out["competitors"][0]
    assert comp["topics"] == 5 and comp["new_topics"] == 5
    data = pubstate.load_json(root / "competitors" / "adexchanger.com.json")
    assert {t["url"] for t in data["topics"]} >= {"https://adexchanger.com/blog/llm-ad-auctions-explained"}
    assert all("/tag/" not in t["url"] for t in data["topics"])
    assert data["topics"][0]["inferred_keyword"] and data["topics"][0]["keyword_priority"] == "medium"
    assert out["fresh_posts"][0]["title"] == "X two"
    assert pubstate.load_strategy(root)["competitors"][0]["domain"] == "adexchanger.com"
    again = _run(scrape, cfg, ["--publication", "adsinllms", "--no-llm", "--no-volume"], monkeypatch, capsys)
    assert again["competitors"][0]["skipped"] is True


def test_topic_map_heuristics_statuses_and_scoring(tmp_path, monkeypatch, capsys):
    cfg, root = _repo(tmp_path)
    strategy = pubstate.load_strategy(root)
    strategy["priority_topics"] = ["LLM ad auction bidding strategy"]
    pubstate.save_strategy(root, strategy)
    pubstate.save_json(root / "competitors" / "adexchanger.com.json", {"name": "AdExchanger", "topics": [
        {"url": "u1", "title": "Deal ID structures for private AI publisher supply", "inferred_keyword": "deal id ai supply", "keyword_priority": "high", "msv": 800, "kd": 30},
        {"url": "u2", "title": "QA checklist before an AI placement goes live", "inferred_keyword": "ai placement qa", "keyword_priority": "medium"},
        {"url": "u3", "title": "Deal ID structures for private AI publisher supply chains", "inferred_keyword": "deal id", "keyword_priority": "high"},
    ]})
    publication.write_post(root / "posts" / "qa-checklist.md", {"title": "QA Checklist Before an AI Placement Goes Live", "slug": "qa-checklist",
                                                                 "section": "Campaign Setup", "author": "kwame-contreras",
                                                                 "published_at": "2026-09-04T13:59:59Z"}, "body")
    out = _run(topic_map_mod, cfg, ["--publication", "adsinllms", "--no-llm", "--no-volume"], monkeypatch, capsys)
    tm = pubstate.load_topic_map(root)
    subtopics = [s["subtopic"] for _, s in pubstate.all_spokes(tm)]
    assert "LLM ad auction bidding strategy" in subtopics
    assert subtopics.count("Deal ID structures for private AI publisher supply") == 1
    assert "Deal ID structures for private AI publisher supply chains" not in subtopics
    covered = [s for _, s in pubstate.all_spokes(tm) if s["status"] == "covered"]
    assert len(covered) == 1 and covered[0]["article_slug"] == "qa-checklist" and out["summary"]["covered"] == 1
    campaign = next(p for p in tm["pillars"] if p["slug"] == "campaign-setup")
    assert any(s["subtopic"].startswith("Deal ID") for s in campaign["spokes"])

    added = _run(topic_map_mod, cfg, ["--publication", "adsinllms", "--add", "Bid adjustment logic in conversational auctions",
                                      "--pillar", "features", "--brief", "Multi-turn sessions need their own bid logic."], monkeypatch, capsys)
    assert added["added"].startswith("sp-")
    dup = _run(topic_map_mod, cfg, ["--publication", "adsinllms", "--add", "Bid adjustment logic in conversational auctions"], monkeypatch, capsys)
    assert dup["added"] is None
    refreshed = _run(topic_map_mod, cfg, ["--publication", "adsinllms", "--refresh", "--no-llm", "--no-volume"], monkeypatch, capsys)
    assert refreshed["summary"]["covered"] == 1

    scored = _run(scoring, cfg, ["--publication", "adsinllms", "--no-llm", "--no-social", "--target", "5"], monkeypatch, capsys)
    assert scored["_exit"] == 0 and scored["dropped_as_cannibalizing"] == 0
    heads = [s["headline"] for s in scored["suggestions"]]
    assert "QA checklist before an AI placement goes live" not in heads
    top = scored["suggestions"][0]
    assert set(top["signal_breakdown"]) == {"competitor", "geo", "seo", "cluster", "authority", "social", "cannibalization"}
    deal = next(s for s in scored["suggestions"] if s["subtopic"].startswith("Deal ID"))
    assert deal["signal_breakdown"]["competitor"] == 1.0 and deal["signal_breakdown"]["seo"] > 0
    state = pubstate.load_json(pubstate.state_path(cfg, "suggestions", "adsinllms"))
    assert len(state["items"]) == scored["open_spokes_scored"] == 3 and state["items"][0]["status"] == "suggested"

    publication.write_post(root / "posts" / "bid-adjustment.md", {"title": "Bid Adjustment Logic in Conversational Auctions", "slug": "bid-adjustment",
                                                                   "section": "Features", "author": "kwame-contreras", "published_at": "2026-09-05T13:00:00Z"}, "body")
    scored2 = _run(scoring, cfg, ["--publication", "adsinllms", "--no-llm", "--no-social"], monkeypatch, capsys)
    assert scored2["dropped_as_cannibalizing"] >= 1
    assert all(not s["subtopic"].startswith("Bid adjustment") for s in scored2["suggestions"])


def test_seers_spec_change_and_github_release(tmp_path, monkeypatch, capsys, fake_transport):
    cfg, root = _repo(tmp_path)
    pubstate.save_yaml(pubstate.seers_path(root), {"seers": [
        {"name": "OpenRTB spec", "provider": "spec_change", "mode": "suggest", "section": "features", "config": {"url": "https://spec.example/openrtb"}},
        {"name": "SDK releases", "provider": "github_release", "mode": "auto", "section": "campaign-setup", "config": {"repo": "acme/sdk"}},
        {"name": "News", "provider": "news_trend", "mode": "suggest", "config": {"query": "x"}},
    ]})
    fake_transport.route("GET", "https://spec.example/openrtb",
                         {"body": "<html><body><p>Version 2.6. Bid requests carry intent signals.</p></body></html>", "headers": {"Content-Type": "text/html"}},
                         {"body": "<html><body><p>Version 2.7. Bid requests carry conversational intent signals.</p></body></html>", "headers": {"Content-Type": "text/html"}})
    fake_transport.route("GET", "https://api.github.com/repos/acme/sdk/releases", {"body": json.dumps([
        {"id": 1, "tag_name": "v1.2.0", "html_url": "https://github.com/acme/sdk/releases/v1.2.0", "body": "Adds conversational bid hints", "published_at": "2026-09-01T00:00:00Z"},
        {"id": 2, "draft": True, "tag_name": "v1.3.0-draft", "html_url": "x"}])})
    first = _run(seers_mod, cfg, ["--publication", "adsinllms"], monkeypatch, capsys)
    by_name = {r["seer"]: r for r in first["runs"]}
    assert by_name["OpenRTB spec"]["new_events"] == 0
    assert by_name["SDK releases"]["new_events"] == 1 and by_name["SDK releases"]["produced"] == 1
    assert "notes" in by_name["News"] and by_name["News"]["events_detected"] == 0
    drafts = list((root / "drafts").glob("*.md"))
    assert len(drafts) == 1
    meta, body = publication.read_post(drafts[0])
    assert meta["status"] == "draft" and meta["source"]["provider"] == "github_release" and meta["section"] == "Campaign Setup"

    second = _run(seers_mod, cfg, ["--publication", "adsinllms", "--force"], monkeypatch, capsys)
    by_name = {r["seer"]: r for r in second["runs"]}
    assert by_name["OpenRTB spec"]["new_events"] == 1 and "2.7" in by_name["OpenRTB spec"]["events"][0]["title"] or by_name["OpenRTB spec"]["new_events"] == 1
    assert by_name["SDK releases"]["new_events"] == 0
    suggestions = pubstate.load_json(pubstate.state_path(cfg, "suggestions", "adsinllms"))
    kinds = {i["source_type"] for i in suggestions["items"]}
    assert kinds == {"seer:github_release", "seer:spec_change"}

    proposal = _run(seers_mod, cfg, ["--publication", "adsinllms", "--propose"], monkeypatch, capsys)
    assert proposal["proposals"] == [] or all(p["provider"] in seers_mod.PROVIDERS for p in proposal["proposals"])
