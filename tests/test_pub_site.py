"""End-to-end: scaffold -> build -> validate, run as subprocesses the way an
agent runs them, with every LLM/provider key stripped so nothing hits the
network. Also proves the validator against a real Letterstory phantom page
(tests/fixtures/letterstory-phantom-article.html) — the anatomy checks must
pass on the thing they were derived from."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "skills" / "pub-site" / "scripts"
FIXTURE = REPO / "tests" / "fixtures" / "letterstory-phantom-article.html"

POST = """---
title: {title}
slug: {slug}
dek: {dek}
section: {section}
author: {author}
published_at: "{published}"
sources:
  - {{url: "https://www.emarketer.com/content/example", title: "eMarketer"}}
---

US spending on AI search ads is set to jump from [$2.08 billion](https://www.emarketer.com/content/example) in 2026.

## The first section heading is a full declarative sentence

{para}

## The second section heading describes the diagnosis

{para} See [the sibling piece](/posts/{other}).

## The third section heading covers targeting readiness

{para}

## What should advertisers do before 2029?

{para}
"""

PARA = ("Legacy search runs on a simple mechanic: a keyword triggers a discrete ad slot, and the auction resolves "
        "in a way advertisers have spent two decades learning to game. LLM environments run on a different logic. "
        "A multi-turn conversation produces a fluid, generated response, and where an ad shows up inside that "
        "response follows rules that owe little to a search results page. ") * 6


def _env() -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.endswith("_API_KEY") and k not in ("DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD", "LLM_PROVIDER")}
    env["SEO_ENGINE_ROOT"] = str(REPO)
    return env


def run(script: str, repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = _env()
    env["SEO_REPO_ROOT"] = str(repo)
    return subprocess.run([sys.executable, str(SKILL / script), *args], cwd=repo, env=env,
                          capture_output=True, text=True, timeout=120)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".seo-engine").mkdir()
    (tmp_path / ".seo-engine" / "config.yml").write_text("site_url: https://thrad.ai\n", encoding="utf-8")
    return tmp_path


def _write_posts(pub_dir: Path, authors: list[str]) -> None:
    (pub_dir / "posts").mkdir(exist_ok=True)
    (pub_dir / "posts" / "advertiser-readiness.md").write_text(POST.format(
        title="Advertiser Readiness Assessment for the AI Search Transition", slug="advertiser-readiness",
        dek="Most advertisers lack the chops for AI search.", section="Advertiser Strategy", author=authors[0],
        published="2026-08-28T20:11:45.769Z", para=PARA, other="intent-decay"), encoding="utf-8")
    (pub_dir / "posts" / "intent-decay.md").write_text(POST.format(
        title="Intent Signal Decay in Multi-Turn AI Conversations", slug="intent-decay",
        dek="Early purchase signals dissolve within two turns.", section="AI Search", author=authors[1],
        published="2026-08-29T20:11:45.769Z", para=PARA, other="advertiser-readiness"), encoding="utf-8")


    # Synthetic source/reviewer fixture for production review gates; not real evidence.
    from scripts.lib import editorial, publication
    for path in (pub_dir / 'posts').glob('*.md'):
        meta, body = publication.read_post(path)
        text = editorial.plain(body)
        cache = pub_dir / (path.stem + '-fixture.txt'); cache.write_text(text)
        meta['research'] = {'status': 'done', 'sources': [{'url': 'https://fixture.test', 'cache': str(cache)}]}
        meta['editorial_review'] = editorial.record_review(meta, body, pub_dir, {
            'reviewer': 'Synthetic Fixture Editor', 'reader_need': 'Synthetic fixture verifying build and validator behavior.',
            'value_added': 'Exercises structural publication output in offline integration tests.', 'facts_checked': True,
            'claims': [{'claim': text, 'quote': text, 'source': 'https://fixture.test',
                        'assessment': 'Synthetic article matched to its synthetic evidence for tests only.'}]})
        publication.write_post(path, meta, body)


def test_scaffold_build_validate_roundtrip(repo: Path):
    dry = run("scaffold_publication.py", repo, "--name", "LLM Billboard", "--site-url", "https://llmbillboard.com",
              "--tagline", "A blog on conversational AI advertising.", "--sections", "Advertiser Strategy,AI Search",
              "--client-name", "thrad", "--client-domain", "thrad.ai", "--theme", "signal", "--icon", "leaf",
              "--deterministic-authors", "--dry-run")
    assert dry.returncode == 0, dry.stderr
    plan = json.loads(dry.stdout)["plan"]
    assert plan["slug"] == "llm-billboard" and len(plan["site"]["authors"]) == 1
    assert plan["site"]["disclosure"]["enabled"] is True and plan["site"]["theme"] == "signal"
    bio = plan["site"]["authors"][0]["bio"]
    assert plan["site"]["authors"][0]["type"] == "Organization" and "Based in" not in bio
    assert not (repo / "publications").exists()

    # the naming rule
    bad = run("scaffold_publication.py", repo, "--name", "Thrad Review", "--site-url", "https://x.com",
              "--client-name", "thrad", "--deterministic-authors", "--dry-run")
    assert bad.returncode != 0 and "contains the client name" in (bad.stderr + bad.stdout)

    real = run("scaffold_publication.py", repo, "--name", "LLM Billboard", "--site-url", "https://llmbillboard.com",
               "--tagline", "A blog on conversational AI advertising.", "--sections", "Advertiser Strategy,AI Search",
               "--client-name", "thrad", "--theme", "signal", "--deterministic-authors")
    assert real.returncode == 0, real.stderr
    pub_dir = repo / "publications" / "llm-billboard"
    site = yaml.safe_load((pub_dir / "site.yml").read_text())
    assert site["name"] == "LLM Billboard" and [s["slug"] for s in site["sections"]] == ["advertiser-strategy", "ai-search"]
    registry = yaml.safe_load((repo / ".seo-engine" / "config.yml").read_text())["publications"]
    assert registry == [{"slug": "llm-billboard", "site_url": "https://llmbillboard.com", "name": "LLM Billboard"}]
    again = run("scaffold_publication.py", repo, "--name", "LLM Billboard", "--site-url", "https://llmbillboard.com",
                "--deterministic-authors")
    assert again.returncode != 0 and "--force" in again.stderr

    authors = [a["slug"] for a in site["authors"][:2]]
    _write_posts(pub_dir, authors * 2)
    built = run("build_site.py", repo, "--publication", "llm-billboard")
    assert built.returncode == 0, built.stderr
    manifest = json.loads(built.stdout)["builds"][0]
    assert manifest["posts"] == 2 and "/posts/advertiser-readiness/index.html" in manifest["pages"]

    validated = run("validate_site.py", repo, "--publication", "llm-billboard", "--min-words", "300")
    report = json.loads(validated.stdout)
    assert report["summary"]["errors"] == 0, [f for f in report["findings"] if f["severity"] == "error"]
    assert validated.returncode == 0 and report["posts_checked"] == 2
    assert (repo / ".seo-engine" / "reports").glob("pub-site-validate-*.json")

    # planted defects are caught
    (pub_dir / "dist" / "robots.txt").write_text("User-agent: *\nAllow: /\n\nUser-agent: OAI-SearchBot\nDisallow: /\n"
                                                 "\nUser-agent: GPTBot\nDisallow: /\n")
    post_html = pub_dir / "dist" / "posts" / "advertiser-readiness" / "index.html"
    html = post_html.read_text(encoding="utf-8")
    html = html.replace('<link rel="canonical" href="https://llmbillboard.com/posts/advertiser-readiness">', "")
    html = html.replace("</article>", '<p><a href="https://adsinllms.com/posts/x">sibling</a></p></article>', 1)
    post_html.write_text(html, encoding="utf-8")
    run("scaffold_publication.py", repo, "--name", "Ads in LLMs", "--site-url", "https://adsinllms.com",
        "--client-name", "thrad", "--deterministic-authors")
    broken = run("validate_site.py", repo, "--publication", "llm-billboard", "--min-words", "300")
    rep = json.loads(broken.stdout)
    checks = {(f["check"], f["severity"]) for f in rep["findings"]}
    assert broken.returncode == 1
    assert ("ai-crawlers", "error") in checks and ("ai-crawlers", "warning") in checks
    assert ("canonical", "error") in checks and ("network-footprint", "error") in checks


def test_validator_accepts_the_real_letterstory_article(tmp_path: Path):
    assert FIXTURE.is_file()
    env = _env()
    result = subprocess.run([sys.executable, str(SKILL / "validate_site.py"), "--html-dir", str(FIXTURE.parent)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    report = json.loads(result.stdout)
    errors = [f for f in report["findings"] if f["severity"] == "error"]
    assert errors == [], errors
    assert report["posts_checked"] == 1 and result.returncode == 0
    # the two things their template lacks show up as warnings, not errors
    assert any(f["check"] == "img-dimensions" for f in report["findings"])
