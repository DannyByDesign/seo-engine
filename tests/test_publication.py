import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from scripts.lib import publication as pubmod

SITE = {
    "name": "Prompt Ledger", "slug": "prompt-ledger", "tagline": "A research publication on what prompts reveal.",
    "site_url": "https://promptledger.example", "theme": "signal", "icon": "leaf", "established": 2026,
    "sections": [{"slug": "intent", "name": "Conversational Intent", "description": "How buyers ask."},
                 {"slug": "features", "name": "Features"}],
    "authors": [{"slug": "talia-kowalski", "name": "Talia Kowalski", "role": "Editor at Large", "city": "Lisbon",
                 "started_at": "2019-04-01", "bio": "Talia covers conversational intent."}],
    "disclosure": {"enabled": False}, "client": {"name": "thrad", "domain": "thrad.ai"},
}

POST_A = """---
title: Linguistic Markers of Purchase Readiness
slug: linguistic-markers
dek: Only one in six prompts signals buying intent.
section: intent
author: talia-kowalski
published_at: "2026-09-01T21:24:29.257Z"
updated_at: "2026-09-06T10:00:00.000Z"
tags: [Conversational Intent]
cover: {src: cover.png}
sources:
  - {url: "https://www.emarketer.com/content/multi-prompt", title: "eMarketer"}
  - {url: "https://verve.com/blog/llm-intent"}
---

Only [one in six](https://www.emarketer.com/content/multi-prompt) prompts carry intent, per eMarketer.

## The distribution problem: most prompts are not buying signals

A paragraph with an internal link to [the funnel piece](https://promptledger.example/posts/funnel-positions) and a *table*.

| Signal | Share |
|---|---|
| Budget stated | 12% |

![Diagram: Four clusters. Visualizes: the funnel.](diagram-1.png)

## What should advertisers do before 2029?

Closing section.
"""

POST_B = """---
title: Funnel Positions
slug: funnel-positions
dek: Five prompt types, five funnel positions.
section: Features
author: Marcus Sabatini
published_at: "2026-09-02T20:05:23.308Z"
---

Body text with a **list**:

- one
- two
"""

DRAFT = """---
title: Not yet
slug: not-yet
status: draft
---

draft body
"""

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000005b6000005460806000000" + "00" * 8)


def _make_pub(tmp_path: Path) -> Path:
    root = tmp_path / "publications" / "prompt-ledger"
    (root / "posts").mkdir(parents=True)
    (root / "assets" / "linguistic-markers").mkdir(parents=True)
    (root / "static").mkdir()
    (root / "site.yml").write_text(yaml.safe_dump(SITE), encoding="utf-8")
    (root / "posts" / "linguistic-markers.md").write_text(POST_A, encoding="utf-8")
    (root / "posts" / "funnel-positions.md").write_text(POST_B, encoding="utf-8")
    (root / "posts" / "not-yet.md").write_text(DRAFT, encoding="utf-8")
    (root / "assets" / "linguistic-markers" / "cover.png").write_bytes(PNG_1X1)
    (root / "assets" / "linguistic-markers" / "diagram-1.png").write_bytes(PNG_1X1)
    (root / "static" / "google1234.html").write_text("google-site-verification: google1234.html")
    return root


def _ld(html: str) -> list:
    return [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


def test_image_placements_preserve_accessibility_rights_and_social_variants(tmp_path):
    from bs4 import BeautifulSoup
    root = _make_pub(tmp_path)
    path = root / 'posts/linguistic-markers.md'
    meta, body = pubmod.read_post(path)
    meta['image_assets'] = {'cover.png': {
        'source_type': 'screenshot', 'creator': {'type': 'Organization', 'name': 'Actual product team'},
        'credit_text': 'Product team', 'license_url': 'https://publisher.test/image-license',
        'copyright_notice': 'Copyright Product team', 'mime': 'image/png',
    }, 'social.svg': {'mime': 'image/svg+xml'}}
    meta['cover'] = {'src': 'cover.png', 'alt': '', 'decorative': True, 'caption': 'Actual caption <safe>',
                     'variants': [{'src': 'small.svg', 'width': 640}, {'src': 'cover.png', 'width': 1462}],
                     'sizes': '(max-width: 700px) 100vw, 704px',
                     'social': {'src': 'social.svg', 'alt': 'Product settings panel'}}
    assets = root / 'assets/linguistic-markers'
    (assets / 'small.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"/>')
    (assets / 'social.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630"/>')
    pubmod.write_post(path, meta, body + '\n\n![](small.svg)\n')
    pub = pubmod.load_publication(root)
    manifest = pubmod.build_site(pub)
    html = (Path(manifest['out_dir']) / 'posts/linguistic-markers/index.html').read_text()
    soup = BeautifulSoup(html, 'lxml')
    hero = soup.select_one('figure.cover img')
    assert hero['alt'] == '' and hero['width'] == '1462'
    assert hero['fetchpriority'] == 'high' and not hero.has_attr('loading')
    assert hero['srcset'] == '/assets/linguistic-markers/small.svg 640w, /assets/linguistic-markers/cover.png 1462w'
    assert hero['sizes'] == '(max-width: 700px) 100vw, 704px'
    assert 'Actual caption <safe>' in soup.select_one('figure.cover figcaption').get_text()
    assert not soup.select_one('figure.cover figcaption safe')
    assert soup.select_one('meta[property="og:image"]')['content'].endswith('/social.svg')
    assert soup.select_one('meta[property="og:image:width"]')['content'] == '1200'
    assert soup.select_one('meta[name="twitter:image:alt"]')['content'] == 'Product settings panel'
    image = _ld(html)[1]['image'][0]
    assert image['caption'] == 'Actual caption <safe>' and image['contentUrl'].endswith('/cover.png')
    assert image['creator'] == {'@type': 'Organization', 'name': 'Actual product team'}
    assert image['license'] == 'https://publisher.test/image-license' and image['creditText'] == 'Product team'
    assert image['copyrightNotice'] == 'Copyright Product team' and image['encodingFormat'] == 'image/png'
    home = BeautifulSoup((Path(manifest['out_dir']) / 'index.html').read_text(), 'lxml')
    for img in home.select('.card img[alt=""]'):
        assert img.parent.get('aria-label')
    post = next(p for p in pub.posts if p.slug == 'linguistic-markers')
    assert not any('image without alt' in warning for warning in post.warnings)
    # No invented caption or headline-derived alt when a legacy cover has no description.
    post.meta['cover'] = {'src': 'cover.png'}
    cover = pubmod.cover_of(pub, post, assets)
    assert cover['alt'] == '' and any('needs reviewed alt' in w for w in post.warnings)
    assert 'caption' not in pubmod.post_ld(pub, post, cover)['image'][0]


def test_load_and_build_reproduces_anatomy(tmp_path):
    root = _make_pub(tmp_path)
    pub = pubmod.load_publication(root)
    assert [p.slug for p in pub.posts] == ["funnel-positions", "linguistic-markers"]
    assert any("not-yet" in w for w in pub.warnings)
    manifest = pubmod.build_site(pub, build_time=datetime(2026, 9, 8, tzinfo=timezone.utc))
    dist = Path(manifest["out_dir"])
    assert manifest["posts"] == 2
    for rel in ["index.html", "posts/linguistic-markers/index.html", "sections/intent/index.html",
                "authors/talia-kowalski/index.html", "authors/marcus-sabatini/index.html", "about/index.html",
                "search/index.html", "feed.xml", "llms.txt", "sitemap.xml", "robots.txt", "404.html", "vercel.json",
                "icons/leaf.svg", "styles.css", "assets/linguistic-markers/cover.png", "google1234.html"]:
        assert (dist / rel).is_file(), rel

    article = (dist / "posts/linguistic-markers/index.html").read_text(encoding="utf-8")
    assert 'data-theme="signal"' in article and "--primary:#ff4d1c" in article and "color-scheme:dark" in article
    assert '<link rel="canonical" href="https://promptledger.example/posts/linguistic-markers">' in article
    assert 'max-image-preview:large' in article and 'og:type" content="article"' in article
    assert 'article:published_time" content="2026-09-01T21:24:29.257Z"' in article
    assert 'og:image:width" content="1462"' in article and 'og:image:height" content="1350"' in article
    assert re.search(r'<a href="https://www\.emarketer\.com/content/multi-prompt"[^>]*rel="noopener noreferrer nofollow"[^>]*target="_blank"', article)
    assert 'href="/posts/funnel-positions"' in article
    assert re.search(r'<section class="sources">.*?<a href="https://verve\.com/blog/llm-intent" target="_blank" rel="noopener noreferrer">verve\.com</a>', article, re.S)
    assert 'href="#the-distribution-problem-most-prompts-are-not-buying-signals"' in article
    assert 'src="/assets/linguistic-markers/diagram-1.png"' in article and 'loading="lazy"' in article and 'width="1462"' in article
    assert '<div class="table-wrap"><table>' in article and "Updated" in article and "min read" in article

    ld = _ld(article)
    types = [x.get("@type") for x in ld]
    assert types == [None, "BlogPosting", "BreadcrumbList"]
    assert [n["@type"] for n in ld[0]["@graph"]] == ["Organization", "WebSite"]
    bp = ld[1]
    assert bp["author"] == {"@type": "Person", "name": "Talia Kowalski", "jobTitle": "Editor at Large",
                            "url": "https://promptledger.example/authors/talia-kowalski",
                            "worksFor": {"@id": "https://promptledger.example/#organization"}}
    assert bp["articleSection"] == "Conversational Intent" and bp["dateModified"].startswith("2026-09-06")
    assert [c["url"] for c in bp["citation"]] == ["https://www.emarketer.com/content/multi-prompt", "https://verve.com/blog/llm-intent"]
    assert bp["image"][0]["url"] == "https://promptledger.example/assets/linguistic-markers/cover.png"
    assert ld[2]["itemListElement"][1]["item"] == "https://promptledger.example/sections/intent"

    home = (dist / "index.html").read_text(encoding="utf-8")
    home_ld = _ld(home)
    assert home_ld[1]["@type"] == "Blog" and len(home_ld[1]["blogPost"]) == 2
    assert "Est. 2026" in home and 'href="/feed.xml"' in home

    author_page = (dist / "authors/talia-kowalski/index.html").read_text(encoding="utf-8")
    prof = _ld(author_page)[1]
    assert prof["@type"] == "ProfilePage" and prof["mainEntity"]["@id"].endswith("/#person") and len(prof["hasPart"]) == 1

    about = (dist / "about/index.html").read_text(encoding="utf-8")
    assert _ld(about)[1]["@type"] == "AboutPage" and "Marcus Sabatini" in about and "supported by" not in about
    assert 'name="robots" content="noindex"' in (dist / "search/index.html").read_text(encoding="utf-8")


def test_feeds_sitemap_robots_and_llms(tmp_path):
    root = _make_pub(tmp_path)
    pub = pubmod.load_publication(root)
    rss = pubmod.render_rss(pub)
    assert rss.count("<item>") == 2 and "<dc:creator>Marcus Sabatini</dc:creator>" in rss
    assert "<category>Features</category>" in rss and 'rel="self"' in rss
    llms = pubmod.render_llms_txt(pub)
    assert llms.startswith("# Prompt Ledger\n\n> A research publication") and "## Posts" in llms
    assert "- [Funnel Positions](https://promptledger.example/posts/funnel-positions): Five prompt types" in llms
    sm = pubmod.render_sitemap(pub)
    assert "<loc>https://promptledger.example</loc><lastmod>2026-09-02T20:05:23.308Z</lastmod><changefreq>daily</changefreq><priority>1</priority>" in sm
    assert "sections/intent</loc><lastmod>2026-09-06T10:00:00.000Z</lastmod><changefreq>weekly</changefreq><priority>0.5</priority>" in sm
    assert "authors/talia-kowalski</loc>" in sm and "<priority>0.4</priority>" in sm
    assert "posts/linguistic-markers</loc><lastmod>2026-09-06T10:00:00.000Z</lastmod><changefreq>monthly</changefreq><priority>0.7</priority>" in sm
    assert pubmod.render_robots(pub) == "User-Agent: *\nAllow: /\n\nHost: https://promptledger.example\nSitemap: https://promptledger.example/sitemap.xml\n"


def test_disclosure_toggle_and_theme_fallback(tmp_path):
    root = _make_pub(tmp_path)
    site = dict(SITE, disclosure={"enabled": True}, theme="does-not-exist")
    (root / "site.yml").write_text(yaml.safe_dump(site), encoding="utf-8")
    pub = pubmod.load_publication(root)
    assert pub.theme_name == "classic" and pub.disclosure == "An independent publication supported by thrad."
    about = pubmod.render_about(pub, 2026)
    assert "An independent publication supported by thrad." in about


def test_helpers():
    assert pubmod.slugify("What makes AI search fundamentally different from the environment advertisers know?") == \
        "what-makes-ai-search-fundamentally-different-from-the-environment-advertisers-kn"
    assert pubmod.reading_minutes(2594) == 12 and pubmod.reading_minutes(10) == 1
    assert pubmod.display_date("2026-08-28T20:11:45.769Z") == "August 28, 2026"
    meta, body = pubmod.parse_frontmatter("---\ntitle: X\n---\n\nbody\n")
    assert meta == {"title": "X"} and body.strip() == "body"
    assert pubmod.parse_frontmatter("plain") == ({}, "plain")
    round_trip = pubmod.dump_frontmatter({"title": "X", "tags": ["a"]}, "body")
    assert pubmod.parse_frontmatter(round_trip) == ({"title": "X", "tags": ["a"]}, "body")
    assert pubmod.image_dimensions(Path("/nonexistent")) is None
