"""pub-publish (planner, publish gate, pipeline dry run), pub-monitor (pure
aggregation + refresh triggers + GEO sync) and geo-monitor's brand-mention
tracker, all offline."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
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


planner_mod = _load(REPO / "skills/pub-publish/scripts/planner.py")
publish_mod = _load(REPO / "skills/pub-publish/scripts/publish_article.py")
pipeline_mod = _load(REPO / "skills/pub-publish/scripts/run_pipeline.py")
perf_mod = _load(REPO / "skills/pub-monitor/scripts/report_performance.py")
refresh_mod = _load(REPO / "skills/pub-monitor/scripts/refresh_triggers.py")
mentions_mod = _load(REPO / "skills/geo-monitor/scripts/track_brand_mentions.py")

from scripts.lib import publication, pubstate, editorial
from scripts.lib.config import Config


def _repo(tmp_path: Path, **env):
    (tmp_path / ".seo-engine").mkdir()
    root = tmp_path / "publications" / "llm-billboard"
    for sub in ("posts", "drafts", "assets"):
        (root / sub).mkdir(parents=True)
    (root / "site.yml").write_text(yaml.safe_dump({
        "name": "LLM Billboard", "slug": "llm-billboard", "tagline": "t", "site_url": "https://llmbillboard.com", "theme": "signal",
        "sections": [{"slug": "ai-search", "name": "AI Search"}, {"slug": "advertiser-strategy", "name": "Advertiser Strategy"}],
        "authors": [{"slug": "ezra-mbeki", "name": "Ezra Mbeki", "role": "Features Editor"}, {"slug": "lena-rossi", "name": "Lena Rossi", "role": "Senior Writer"}],
        "client": {"name": "thrad", "domain": "thrad.ai"},
        "disclosure": {"enabled": True, "text": "Published by thrad."},
    }))
    strategy = pubstate.load_strategy(root)
    strategy["client"].update({"name": "thrad", "domain": "thrad.ai", "aliases": ["Thrad AI"]})
    strategy["competitors"] = [{"name": "Lapis", "domain": "trylapis.com"}]
    strategy["ranking_targets"] = [{"phrase": "LLM advertising platforms", "mention_framing": "", "status": "active"}]
    pubstate.save_strategy(root, strategy)
    pubstate.save_topic_map(root, {"pillars": [
        {"slug": "ai-search", "name": "AI Search", "is_priority": True, "is_muted": False, "spokes": [
            {"id": "sp-0001", "subtopic": "Advertiser readiness assessment for the AI search transition", "angle": "scorecard", "brief": "Know your gaps.", "status": "open", "client_relevance": "high", "source": "ai"},
            {"id": "sp-0002", "subtopic": "Intent signal decay in multi-turn conversations", "angle": "", "brief": "Signals fade.", "status": "open", "client_relevance": "medium", "source": "ai"}]},
        {"slug": "advertiser-strategy", "name": "Advertiser Strategy", "is_priority": False, "is_muted": False, "spokes": [
            {"id": "sp-0003", "subtopic": "Budget allocation for performance marketers", "angle": "", "brief": "Where the money goes.", "status": "open", "client_relevance": "medium", "source": "ai"}]}]})
    cfg = Config(repo_root=tmp_path, env=dict(env), site={"publications_dir": "publications", "publications": [{"slug": "llm-billboard", "site_url": "https://llmbillboard.com"}]})
    return cfg, root


def _run(mod, cfg, argv, monkeypatch, capsys):
    monkeypatch.setattr(mod.config_module, "load", lambda *a, **k: cfg)
    monkeypatch.setattr(sys, "argv", ["x", *argv])
    code = mod.main()
    out = json.loads(capsys.readouterr().out)
    out["_exit"] = code
    return out


def _ready_draft(root: Path, slug: str, spoke_id: str) -> None:
    body = ("Opening with [$2.08 billion](https://e.com/a), per eMarketer.\n\n" + "\n\n".join(
        f"## Section heading number {i} is a full declarative sentence\n\n" + ("Paragraph text with substance and a source, per eMarketer. " * 40) for i in range(1, 7)))
    publication.write_post(root / "drafts" / f"{slug}.md", {
        "title": slug.replace("-", " ").title(), "slug": slug, "dek": "A dek.", "section": "AI Search", "spoke_id": spoke_id, "status": "written",
        "research": {"status": "done"}, "enhanced_at": "2026-09-08T00:00:00Z", "written_at": "2026-09-01T00:00:00Z",
        "cover": {"src": "cover.svg", "alt": "Cover", "width": 1600, "height": 900},
        "sources": [{"url": "https://e.com/a"}, {"url": "https://e.com/b"}, {"url": "https://e.com/c"}],
        "mention": {"allowed": False, "applied": False}}, body)
    (root / "assets" / slug).mkdir(parents=True, exist_ok=True)
    (root / "assets" / slug / "cover.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900"></svg>')


    _review_draft(root, slug)


def _review_draft(root, slug, reviewed_at=None):
    import hashlib
    path = root / 'drafts' / f'{slug}.md'
    meta, body = publication.read_post(path)
    text = editorial.plain(body)
    cache = root / f'{slug}-fixture-source.txt'
    cache.write_text(text)
    meta['research']['sources'] = [{'url': 'https://e.com/a', 'cache': str(cache)}]
    review = {'reviewer': 'Fixture Editor', 'reader_need': 'Synthetic article used to exercise publication state transitions.',
              'value_added': 'Synthetic fixture supporting deterministic integration testing.', 'facts_checked': True,
              'claims': [{'claim': text, 'source': 'https://e.com/a', 'quote': text,
                          'assessment': 'Synthetic fixture matches its synthetic source for state-transition testing only.'}]}
    meta['editorial_review'] = editorial.record_review(meta, body, root, review)
    if reviewed_at:
        meta['editorial_review']['reviewed_at'] = reviewed_at
    publication.write_post(path, meta, body)
    cfg = Config(repo_root=root.parents[1], env={}, site={})
    pubstate.save_json(pubstate.state_path(cfg, 'prepared', root.name + '-' + slug),
                      {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})


def test_planner_materializes_bursts_and_queues(tmp_path, monkeypatch, capsys):
    cfg, root = _repo(tmp_path)
    conf = _run(planner_mod, cfg, ["--publication", "llm-billboard", "--configure", "--cadence-per-week", "7", "--approval-mode", "manual", "--publish-hour", "20"], monkeypatch, capsys)
    assert conf["planner"]["cadence_per_week"] == 7 and conf["planner"]["publish_hour_utc"] == 20
    assert yaml.safe_load((root / "site.yml").read_text())["planner"]["approval_mode"] == "manual"
    pubstate.save_json(pubstate.state_path(cfg, "suggestions", "llm-billboard"), {"items": [
        {"id": "sg-0001", "status": "suggested", "spoke_id": "sp-0002", "headline": "Intent Signal Decay in Multi-Turn AI Conversations", "why": "w", "score": 0.7, "pillar": "ai-search"}]})
    out = _run(planner_mod, cfg, ["--publication", "llm-billboard", "--materialize", "--days", "3", "--queue"], monkeypatch, capsys)
    assert len(out["materialized"]) == 3 + 3
    assert out["queued"][0]["headline"] == "Intent Signal Decay in Multi-Turn AI Conversations"
    assert len(out["queued"]) == 3
    assert out["status"]["planned"] == 3 and out["status"]["queued"] == 3
    drafts = sorted(p.name for p in (root / "drafts").glob("*.md"))
    assert "intent-signal-decay-in-multi-turn-ai-conversations.md" in drafts and len(drafts) == 3
    tm = pubstate.load_topic_map(root)
    assert all(s["status"] == "queued" for _, s in pubstate.all_spokes(tm))
    meta, _ = publication.read_post(root / "drafts" / "advertiser-readiness-assessment-for-the-ai-search-transition.md")
    assert meta["spoke_id"] == "sp-0001" and meta["section"] == "AI Search" and meta["brief"] == "Know your gaps."
    again = _run(planner_mod, cfg, ["--publication", "llm-billboard", "--materialize", "--days", "3"], monkeypatch, capsys)
    assert again["materialized"] == []
    due = _run(planner_mod, cfg, ["--publication", "llm-billboard", "--due"], monkeypatch, capsys)
    assert isinstance(due["due"], list)


def test_publish_gate_then_success_with_build(tmp_path, monkeypatch, capsys):
    cfg, root = _repo(tmp_path)
    publication.write_post(root / "drafts" / "thin.md", {"title": "Thin", "slug": "thin", "section": "AI Search"}, "short body")
    refused = _run(publish_mod, cfg, ["--publication", "llm-billboard", "--slug", "thin", "--approve"], monkeypatch, capsys)
    assert refused["_exit"] == 1 and refused["published"] is False
    assert {"research not done", "not enhanced (run pub-enhance)"} <= set(refused["gate"])
    _ready_draft(root, "advertiser-readiness", "sp-0001")
    manual = _run(publish_mod, cfg, ["--publication", "llm-billboard", "--slug", "advertiser-readiness"], monkeypatch, capsys)
    assert manual["_exit"] == 1 and "manual" in manual["approval"]
    ok = _run(publish_mod, cfg, ["--publication", "llm-billboard", "--slug", "advertiser-readiness", "--approve", "--build"], monkeypatch, capsys)
    assert ok["_exit"] == 0 and ok["published"] and ok["url"] == "https://llmbillboard.com/posts/advertiser-readiness"
    assert not (root / "drafts" / "advertiser-readiness.md").exists() and (root / "posts" / "advertiser-readiness.md").is_file()
    meta, _ = publication.read_post(root / "posts" / "advertiser-readiness.md")
    assert meta["status"] == "published" and meta["published_at"] == meta["updated_at"] and meta["author"] in ("ezra-mbeki", "lena-rossi")
    tm = pubstate.load_topic_map(root)
    assert pubstate.find_spoke(tm, "sp-0001")["status"] == "covered"
    build_hook = ok["hooks"][0]
    assert build_hook["script"] == "build_site.py" and build_hook["exit"] == 0
    assert (root / "dist" / "posts" / "advertiser-readiness" / "index.html").is_file()

    plan = _run(pipeline_mod, cfg, ["--publication", "llm-billboard", "--slug", "x", "--dry-run"], monkeypatch, capsys)
    steps = [p["step"] for p in plan["plan"]]
    assert steps == ["research", "write", "enhance", "diagrams", "cover"]
    plan2 = _run(pipeline_mod, cfg, ["--publication", "llm-billboard", "--slug", "x", "--dry-run", "--approve", "--skip", ""], monkeypatch, capsys)
    assert plan2["_exit"] == 1 and "prepare and review" in plan2["error"]


def test_performance_aggregation_and_refresh_triggers(tmp_path, monkeypatch, capsys):
    cfg, root = _repo(tmp_path)
    for slug, day in (("old-post", "2026-01-01"), ("new-post", "2026-09-01")):
        publication.write_post(root / "posts" / f"{slug}.md", {"title": slug, "slug": slug, "section": "AI Search", "author": "ezra-mbeki",
                                                                 "published_at": f"{day}T00:00:00Z", "updated_at": f"{day}T00:00:00Z"},
                               "Spend was $4 billion in 2024 according to a report." if slug == "old-post" else "Fresh body.")
    pub = publication.load_publication(root)
    cur = [{"page": "https://llmbillboard.com/posts/old-post", "clicks": 10, "impressions": 400, "position": 12.0},
           {"page": "https://llmbillboard.com/posts/new-post", "clicks": 2, "impressions": 100, "position": 30.0},
           {"page": "https://llmbillboard.com/", "clicks": 1, "impressions": 10, "position": 5.0}]
    prev = [{"page": "https://llmbillboard.com/posts/old-post", "clicks": 30, "impressions": 200, "position": 8.0}]
    qp = [{"query": "ai search ads", "page": "https://llmbillboard.com/posts/old-post", "clicks": 8, "impressions": 300, "position": 11.0}]
    dates = [{"date": "2026-09-01", "clicks": 3, "impressions": 100, "position": 10.0}]
    state: dict = {}
    agg = perf_mod.aggregate(pub, cur, prev, qp, dates, state, {"start": "2026-08-31", "end": "2026-09-02"}, "2026-09-05")
    assert agg["site"]["current"] == {"clicks": 13, "impressions": 510, "ctr": round(13 / 510, 4), "position": round((12 * 400 + 30 * 100 + 5 * 10) / 510, 2)}
    by = {p["slug"]: p for p in agg["posts"]["items"]}
    assert by["old-post"]["state"] == "receiving" and by["old-post"]["delta"]["clicks"] == -20
    assert state["first_impression_at"]["new-post"] == "2026-09-05"
    assert agg["pillars"][0]["section"] == "AI Search" and agg["top_queries"][0]["posts"] == ["old-post"]
    assert len(agg["series"]) == 3 and agg["series"][1]["impressions"] == 100
    assert any("2 of 2 published posts" in i for i in agg["insights"])

    pubstate.save_json(pubstate.state_path(cfg, "performance", "llm-billboard"), {
        "first_impression_at": {"old-post": "2026-02-01"},
        "history": [{"period": "30d", "window": {"start": "2026-06-01", "end": "2026-06-30"}, "posts": {"old-post": {"clicks": 30}}}, {"period": "30d", "window": {"start": "2026-07-01", "end": "2026-07-30"}, "posts": {"old-post": {"clicks": 10}}}]})
    out = _run(refresh_mod, cfg, ["--publication", "llm-billboard", "--queue", "--awaiting-days", "1"], monkeypatch, capsys)
    flagged = {f["slug"]: {t["trigger"] for t in f["triggers"]} for f in out["flagged"]}
    assert flagged["old-post"] >= {"clicks_drop", "aged", "dated_numbers"}
    assert "no_recorded_impressions" in flagged["new-post"]
    tm = pubstate.load_topic_map(root)
    refresh_spokes = [s for _, s in pubstate.all_spokes(tm) if s.get("refresh_of")]
    assert {s["refresh_of"] for s in refresh_spokes} == {"old-post", "new-post"} and len(out["queued_spokes"]) == 2
    again = _run(refresh_mod, cfg, ["--publication", "llm-billboard", "--queue", "--awaiting-days", "1"], monkeypatch, capsys)
    assert again["queued_spokes"] == []


def test_brand_mentions_run_and_geo_sync(tmp_path, monkeypatch, capsys, fake_transport):
    cfg, root = _repo(tmp_path, ANTHROPIC_API_KEY="sk")

    def reply(obj):
        return {"body": json.dumps({"content": [{"type": "text", "text": json.dumps(obj) if not isinstance(obj, dict) or "content" not in obj else ""}],
                                    "stop_reason": "end_turn", "usage": {}}) if not (isinstance(obj, dict) and "content" in obj) else json.dumps(obj)}

    answer1 = {"content": [{"type": "text", "text": "Top vendors: Thrad AI leads for DSP buying, then Lapis. See https://llmbillboard.com/posts/x",
                            "citations": [{"url": "https://llmbillboard.com/posts/x", "title": "LLM Billboard"}, {"url": "https://other.com/a", "title": "Other"}]}],
               "stop_reason": "end_turn", "usage": {}}
    answer2 = {"content": [{"type": "text", "text": "Lapis is the main option most buyers name.", "citations": []}], "stop_reason": "end_turn", "usage": {}}
    fake_transport.route("POST", "https://api.anthropic.com/v1/messages",
                         reply([{"question": "List the top 5 LLM advertising platforms by name.", "specificity": "general"},
                                {"question": "Which vendors sell ads inside ChatGPT? Just the company names.", "specificity": "mid"}]),
                         reply(answer1),
                         reply({"results": [{"key": "brand", "sentiment": "positive", "recommended": True}, {"key": "comp-0", "sentiment": "neutral", "recommended": False}]}),
                         reply(answer2),
                         reply({"results": [{"key": "Lapis", "sentiment": "positive", "recommended": True}]}))
    dry = _run(mentions_mod, cfg, ["--publication", "llm-billboard", "--generate", "--dry-run"], monkeypatch, capsys)
    assert dry["prompts"] == 2 and dry["providers"] == ["anthropic"] and "2 billed" in dry["cost_note"]
    assert dry["subject"]["brand"] == "thrad" and dry["competitors"] == ["Lapis"]
    out = _run(mentions_mod, cfg, ["--publication", "llm-billboard"], monkeypatch, capsys)
    assert out["_exit"] == 0 and out["responses"] == 2
    s = out["summary"]
    brand, comp = s["entities"][0], s["entities"][1]
    assert brand["key"] == "brand" and brand["responses_mentioned"] == 1 and brand["mention_rate"]["point"] == 0.5
    assert comp["name"] == "Lapis" and comp["responses_mentioned"] == 2 and comp["share_of_voice"] > brand["share_of_voice"]
    assert brand["sentiment"]["positive"] == 1 and brand["recommend_rate"] == 1.0
    assert s["owned_citation_rate"]["point"] == 0.5 and s["distinct_owned_urls"] == ["https://llmbillboard.com/posts/x"]
    assert s["informative_rate"]["point"] == 1.0 and s["measurement_verdict"] == "thin-sample"
    assert out["questions_competitors_win"] == []
    assert out["cited_pages"][0]["page"] == "llmbillboard.com/posts/x"
    assert out["first_mention_at"]
    geo = perf_mod.sync_geo(cfg, "llm-billboard")
    assert geo["synced"] == 0
    items = pubstate.load_json(pubstate.state_path(cfg, "geo-opportunities", "llm-billboard"))["items"]
    assert items == []
