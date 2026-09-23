"""Publication model + static-site builder for the pub-* skills.

A *publication* is a transparently owned editorial site (masthead, sections,
recurring authors, posts) that the pipeline writes into and this module
renders. The rendered HTML reproduces, field for field, the anatomy the
teardown measured on Letterstory's phantom sites (see
seo-references/publication-playbook.md §2-§3): theme tokens on <html>,
robots/googlebot meta, canonical, OG/Twitter, the Organization+WebSite
graph, Blog/BlogPosting/ProfilePage/AboutPage/BreadcrumbList JSON-LD,
`citation[]` mirrored from a followed Sources block, nofollow inline
citations, an "In this article" TOC, RSS, llms.txt, a priority-weighted
sitemap, and clean URLs — plus the two things theirs lacks (image
dimensions, self-hosted indexable images).

Layout in the target repo (see common-setup.md § Publications):
  <publications_dir>/<slug>/
      site.yml                 manifest — see load_publication()
      strategy.yml             positioning (pub-strategy)
      topic-map.yml            pillars + spokes (pub-curate)
      posts/<post-slug>.md     published articles: YAML frontmatter + markdown
      drafts/<post-slug>.md    in flight — never built
      assets/<post-slug>/      cover + diagrams referenced by relative path
      static/                  copied verbatim into dist/ (verification files, og image)
      dist/                    build output — deploy this directory

Pure functions where possible; the only I/O is reading the publication
tree and writing dist/. No network.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse
from uuid import uuid4

from bs4 import BeautifulSoup

try:
    import yaml
except ImportError:
    yaml = None

try:
    import markdown as _markdown
except ImportError:
    _markdown = None

WORDS_PER_MINUTE = 220
HEADING_ID_MAX = 80
KICKER_DEFAULT = "Long read"
DEFAULT_LANGUAGE = "en"
RSS_LIMIT = 50
HOME_LIMIT = 12
RELATED_LIMIT = 3


def _theme(**tokens: Any) -> dict[str, Any]:
    base = {
        "bg": "#ffffff", "surface": "#f3f3f1", "surface_alt": "#ecebe7", "fg": "#1a1a1a",
        "muted": "#6b6b73", "border": "#e3e1db", "primary": "#111111", "primary_fg": "#ffffff",
        "secondary": "#333333", "accent": "#0ea5e9", "link": "#0f5fbd", "heading_color": "#111111",
        "kicker": "#8a3d00", "hero_from": "#111111", "hero_to": "#444444",
        "font_display": "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif",
        "font_heading": "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif",
        "font_body": "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif",
        "font_mono": "ui-monospace, Menlo, monospace",
        "radius": "0.5rem", "content_width": "44rem", "container_width": "72rem",
        "color_scheme": "light", "google_fonts": ["Inter:wght@400;500;600;700"],
    }
    base.update(tokens)
    return base


THEMES: dict[str, dict[str, Any]] = {
    "signal": _theme(
        bg="#ffffff", surface="#edeae3", surface_alt="#1b1b24", fg="#1a1a1a", muted="#9a9aa6",
        border="#2a2a34", primary="#ff4d1c", primary_fg="#ffffff", secondary="#1a1a2e", accent="#00e5b4",
        link="#d63b08", heading_color="#0f0f1a", kicker="#ff0080", hero_from="#ff4d1c", hero_to="#0f0f1a",
        font_display="'Archivo', system-ui, 'Helvetica Neue', sans-serif",
        font_heading="'Space Grotesk', system-ui, -apple-system, 'Segoe UI', sans-serif",
        font_body="'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif",
        font_mono="'Space Mono', ui-monospace, Menlo, monospace",
        radius="0.75rem", content_width="44rem", container_width="78rem", color_scheme="dark",
        google_fonts=["Archivo:wght@700;800", "Space+Grotesk:wght@500;700", "Inter:wght@400;500;600", "Space+Mono"],
    ),
    "forum": _theme(
        bg="#f7f5f0", surface="#edeae2", surface_alt="#ece9e1", fg="#1c1c1c", muted="#585c54",
        border="#dcd7cb", primary="#00b38a", primary_fg="#fbfaf7", secondary="#1a1a2e", accent="#f5c842",
        link="#00896a", heading_color="#0d0d1a", kicker="#12303d", hero_from="#0d0d1a", hero_to="#00b38a",
        font_display="'Source Sans 3', system-ui, -apple-system, 'Segoe UI', sans-serif",
        font_heading="'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif",
        font_body="'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif",
        font_mono="'IBM Plex Mono', ui-monospace, Menlo, monospace",
        radius="0rem", content_width="44rem", container_width="72rem", color_scheme="light",
        google_fonts=["Source+Sans+3:wght@600;700", "Inter:wght@400;500;600", "IBM+Plex+Mono"],
    ),
    "classic": _theme(
        bg="#faf9f7", surface="#f0ede8", surface_alt="#efe9dd", fg="#1c1917", muted="#655f52",
        border="#e6ded0", primary="#7c3aed", primary_fg="#fffdf7", secondary="#a78bfa", accent="#f59e0b",
        link="#7c3aed", heading_color="#1c1917", kicker="#9a3412", hero_from="#2e1065", hero_to="#7c3aed",
        font_mono="'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace",
        radius="0.375rem", content_width="42rem", container_width="58rem", color_scheme="light",
        google_fonts=["Inter:wght@400;500;600;700", "JetBrains+Mono"],
    ),
    "gazette": _theme(
        bg="#fbfaf6", surface="#f1eee6", surface_alt="#e9e4d8", fg="#141414", muted="#5f5b54",
        border="#dcd6c8", primary="#8b0000", primary_fg="#ffffff", secondary="#2b2b2b", accent="#b8860b",
        link="#8b0000", heading_color="#101010", kicker="#8b0000", hero_from="#2b2b2b", hero_to="#8b0000",
        font_display="'Playfair Display', Georgia, serif", font_heading="'Playfair Display', Georgia, serif",
        font_body="'Source Serif 4', Georgia, serif", radius="0rem", container_width="70rem",
        google_fonts=["Playfair+Display:wght@600;700;800", "Source+Serif+4:wght@400;600"],
    ),
    "ledger": _theme(
        bg="#f6f7f9", surface="#eceff3", surface_alt="#e1e6ec", fg="#111827", muted="#5b6472",
        border="#d5dbe3", primary="#0b3d91", primary_fg="#ffffff", secondary="#1f2937", accent="#c9a227",
        link="#0b3d91", heading_color="#0b1220", kicker="#0b3d91", hero_from="#0b1f4b", hero_to="#0b3d91",
        font_display="'IBM Plex Serif', Georgia, serif", font_heading="'IBM Plex Serif', Georgia, serif",
        font_body="'IBM Plex Sans', system-ui, sans-serif", font_mono="'IBM Plex Mono', ui-monospace, monospace",
        radius="0.25rem", google_fonts=["IBM+Plex+Serif:wght@600;700", "IBM+Plex+Sans:wght@400;500;600", "IBM+Plex+Mono"],
    ),
    "midnight": _theme(
        bg="#0f1115", surface="#171a21", surface_alt="#1f232c", fg="#e8e8ea", muted="#9aa0ad",
        border="#2a2f3a", primary="#7dd3fc", primary_fg="#0f1115", secondary="#c4b5fd", accent="#f472b6",
        link="#93c5fd", heading_color="#ffffff", kicker="#7dd3fc", hero_from="#1e293b", hero_to="#0f1115",
        radius="0.75rem", color_scheme="dark", google_fonts=["Inter:wght@400;500;600;700"],
    ),
    "minimal": _theme(
        bg="#ffffff", surface="#fafafa", surface_alt="#f2f2f2", fg="#111111", muted="#6b6b6b",
        border="#e5e5e5", primary="#111111", primary_fg="#ffffff", secondary="#444444", accent="#111111",
        link="#111111", heading_color="#000000", kicker="#666666", hero_from="#222222", hero_to="#000000",
        radius="0rem", content_width="40rem", container_width="60rem",
    ),
    "magazine": _theme(
        bg="#ffffff", surface="#f7f3f4", surface_alt="#f0e8ea", fg="#1a1416", muted="#6d5f63",
        border="#e8dcdf", primary="#e11d48", primary_fg="#ffffff", secondary="#1a1416", accent="#f59e0b",
        link="#be123c", heading_color="#1a1416", kicker="#e11d48", hero_from="#1a1416", hero_to="#e11d48",
        font_display="'DM Serif Display', Georgia, serif", font_heading="'DM Serif Display', Georgia, serif",
        font_body="'DM Sans', system-ui, sans-serif", radius="0.5rem", container_width="76rem",
        google_fonts=["DM+Serif+Display", "DM+Sans:wght@400;500;700"],
    ),
    "dispatch": _theme(
        bg="#f4f4f0", surface="#ebebe4", surface_alt="#e1e1d8", fg="#1b1f1c", muted="#5d655f",
        border="#d6d8cf", primary="#1f6f43", primary_fg="#ffffff", secondary="#1b1f1c", accent="#d97706",
        link="#1f6f43", heading_color="#101410", kicker="#1f6f43", hero_from="#0f3d24", hero_to="#1f6f43",
        font_display="'Fraunces', Georgia, serif", font_heading="'Fraunces', Georgia, serif",
        font_body="'Public Sans', system-ui, sans-serif", google_fonts=["Fraunces:wght@600;700", "Public+Sans:wght@400;500;600"],
    ),
    "atlas": _theme(
        bg="#f5f8fb", surface="#e9eff5", surface_alt="#dde6ef", fg="#0f172a", muted="#526071",
        border="#d3dde8", primary="#0e7490", primary_fg="#ffffff", secondary="#0f172a", accent="#f97316",
        link="#0e7490", heading_color="#0b1324", kicker="#0e7490", hero_from="#0c4a6e", hero_to="#0e7490",
        font_display="'Manrope', system-ui, sans-serif", font_heading="'Manrope', system-ui, sans-serif",
        font_body="'Manrope', system-ui, sans-serif", google_fonts=["Manrope:wght@400;500;600;800"],
    ),
    "verdure": _theme(
        bg="#f3f7f2", surface="#e8efe6", surface_alt="#dce7d9", fg="#14201a", muted="#55665c",
        border="#d0dccd", primary="#2f6b3a", primary_fg="#ffffff", secondary="#14201a", accent="#c2410c",
        link="#2f6b3a", heading_color="#0f1a14", kicker="#2f6b3a", hero_from="#1b3d22", hero_to="#2f6b3a",
        font_display="'Lora', Georgia, serif", font_heading="'Lora', Georgia, serif",
        font_body="'Nunito Sans', system-ui, sans-serif", google_fonts=["Lora:wght@600;700", "Nunito+Sans:wght@400;600"],
    ),
    "noir": _theme(
        bg="#0a0a0a", surface="#141414", surface_alt="#1c1c1c", fg="#f5f5f5", muted="#a3a3a3",
        border="#262626", primary="#f5f5f5", primary_fg="#0a0a0a", secondary="#d4d4d4", accent="#ffd60a",
        link="#ffd60a", heading_color="#ffffff", kicker="#ffd60a", hero_from="#262626", hero_to="#0a0a0a",
        font_display="'Bebas Neue', Impact, sans-serif", font_heading="'Inter', system-ui, sans-serif",
        radius="0rem", color_scheme="dark", google_fonts=["Bebas+Neue", "Inter:wght@400;500;600;700"],
    ),
}

ICONS: dict[str, str] = {
    "leaf": '<path d="M8 24 C10 14 18 8 24 8 C24 14 18 22 8 24 Z" fill="#fff"/><path d="M10 22 C14 18 19 12 22 10" fill="none" stroke="{c}" stroke-width="1.6" stroke-linecap="round"/>',
    "ring": '<circle cx="16" cy="16" r="8" fill="none" stroke="#fff" stroke-width="3"/><circle cx="16" cy="16" r="2.5" fill="#fff"/>',
    "spark": '<path d="M16 5 L18.5 13.5 L27 16 L18.5 18.5 L16 27 L13.5 18.5 L5 16 L13.5 13.5 Z" fill="#fff"/>',
    "bolt": '<path d="M18 5 L9 18 H15 L14 27 L23 14 H17 Z" fill="#fff"/>',
    "wave": '<path d="M5 18 C9 12 13 12 16 18 C19 24 23 24 27 18" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round"/>',
    "grid": '<rect x="7" y="7" width="7" height="7" fill="#fff"/><rect x="18" y="7" width="7" height="7" fill="#fff"/><rect x="7" y="18" width="7" height="7" fill="#fff"/><rect x="18" y="18" width="7" height="7" fill="#fff"/>',
}


def icon_svg(name: str, color: str) -> str:
    body = ICONS.get(name, ICONS["spark"]).replace("{c}", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">'
            f'<rect width="32" height="32" rx="7" fill="{color}"/>{body}</svg>\n')


def slugify(text: str, max_len: int = HEADING_ID_MAX) -> str:
    text = (text or "").lower()
    text = re.sub(r"['’]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:max_len].rstrip("-") if max_len else text


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def display_date(value: Any) -> str:
    dt = parse_iso(value)
    if not dt:
        return ""
    return f"{dt.strftime('%B')} {dt.day}, {dt.year}"


def reading_minutes(words: int) -> int:
    return max(1, -(-words // WORDS_PER_MINUTE))


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    m = re.match(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", text, flags=re.DOTALL)
    if not m:
        return {}, text
    if yaml is None:
        raise RuntimeError("PyYAML is required — python3 -m pip install -r requirements.txt")
    meta = yaml.safe_load(m.group(1)) or {}
    return (meta if isinstance(meta, dict) else {}), m.group(2)


def dump_frontmatter(meta: dict[str, Any], body: str) -> str:
    if yaml is None:
        raise RuntimeError("PyYAML is required — python3 -m pip install -r requirements.txt")
    return "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).rstrip() + "\n---\n\n" + body.lstrip("\n")


def read_post(path: Path) -> tuple[dict[str, Any], str]:
    return parse_frontmatter(path.read_text(encoding="utf-8"))


def write_post(path: Path, meta: dict[str, Any], body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    from .pubstate import atomic_text
    atomic_text(path, dump_frontmatter(meta, body))
    return path


def image_dimensions(path: Path) -> Optional[tuple[int, int]]:
    """PNG / JPEG / SVG(viewBox) dimensions without Pillow. None if unknown."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        w, h = struct.unpack(">II", data[16:24])
        return w, h
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            length = struct.unpack(">H", data[i + 2:i + 4])[0]
            i += 2 + length
        return None
    if data.lstrip()[:5].lower() in (b"<svg ", b"<?xml"):
        m = re.search(rb'viewBox="[\d.\-]+\s+[\d.\-]+\s+([\d.]+)\s+([\d.]+)"', data[:2000])
        if m:
            return int(float(m.group(1))), int(float(m.group(2)))
        mw = re.search(rb'width="(\d+)', data[:2000])
        mh = re.search(rb'height="(\d+)', data[:2000])
        if mw and mh:
            return int(mw.group(1)), int(mh.group(1))
    return None


def _e(text: Any) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def _jsonld(obj: Any) -> str:
    return ('<script type="application/ld+json">'
            + json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")
            + "</script>")


def asset_name(meta: dict, slug: str) -> str:
    name = str(meta.get('asset_slug') or slug)
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]*', name):
        raise ValueError('asset_slug must be a safe directory name')
    return name


def draft_assets(root: Path, slug: str, meta: dict) -> Path:
    """Fork the published asset bundle before any pending draft visual mutation."""
    name = asset_name(meta, slug)
    published = root / 'posts' / f'{slug}.md'
    if published.is_file():
        old_meta, _ = read_post(published)
        old_name = asset_name(old_meta, slug)
        if name == old_name:
            name = f'{slug}--{uuid4().hex[:12]}'
            source = root / 'assets' / old_name
            if source.is_dir(): shutil.copytree(source, root / 'assets' / name)
            meta['asset_slug'] = name
    path = root / 'assets' / name
    assert_unpublished_assets(root, path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def assert_unpublished_assets(root: Path, path: Path) -> None:
    """CLI visual operations may not overwrite any currently published asset bundle."""
    for post in (root / 'posts').glob('*.md'):
        meta, _ = read_post(post)
        used = (root / 'assets' / asset_name(meta, post.stem)).resolve()
        if path.resolve().is_relative_to(used):
            raise ValueError('published assets are immutable; prepare visuals in an isolated refresh draft')

@dataclass
class Post:
    slug: str
    meta: dict[str, Any]
    body_md: str
    path: Optional[Path] = None
    html: str = ""
    words: int = 0
    minutes: int = 0
    headings: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        return str(self.meta.get("title") or self.slug.replace("-", " ").title())

    @property
    def dek(self) -> str:
        return str(self.meta.get("dek") or self.meta.get("summary") or self.meta.get("description") or "")

    @property
    def published_at(self) -> str:
        return str(self.meta.get("published_at") or "")

    @property
    def updated_at(self) -> str:
        return str(self.meta.get("updated_at") or self.meta.get("published_at") or "")

    @property
    def tags(self) -> list[str]:
        tags = self.meta.get("tags") or []
        return [str(t) for t in tags] if isinstance(tags, list) else [str(tags)]

    @property
    def kicker(self) -> str:
        return str(self.meta.get("kicker") or KICKER_DEFAULT)

    @property
    def sources(self) -> list[dict[str, Any]]:
        out = []
        for s in self.meta.get("sources") or []:
            if isinstance(s, str):
                out.append({"url": s})
            elif isinstance(s, dict) and s.get("url"):
                out.append(s)
        return out

    @property
    def is_draft(self) -> bool:
        return str(self.meta.get("status") or "published").lower() == "draft" or not self.published_at


@dataclass
class Publication:
    root: Path
    site: dict[str, Any]
    posts: list[Post] = field(default_factory=list)
    sections: list[dict[str, Any]] = field(default_factory=list)
    authors: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return str(self.site.get("name") or self.root.name)

    @property
    def slug(self) -> str:
        return str(self.site.get("slug") or slugify(self.name))

    @property
    def tagline(self) -> str:
        return str(self.site.get("tagline") or "")

    @property
    def site_url(self) -> str:
        return str(self.site.get("site_url") or "").rstrip("/")

    @property
    def host(self) -> str:
        return urlparse(self.site_url).netloc.lower().removeprefix("www.")

    @property
    def language(self) -> str:
        return str(self.site.get("language") or DEFAULT_LANGUAGE)

    @property
    def theme_name(self) -> str:
        name = str(self.site.get("theme") or "classic")
        return name if name in THEMES else "classic"

    @property
    def theme(self) -> dict[str, Any]:
        merged = dict(THEMES[self.theme_name])
        merged.update(self.site.get("theme_overrides") or {})
        return merged

    @property
    def icon(self) -> str:
        return str(self.site.get("icon") or "spark")

    @property
    def disclosure(self) -> Optional[str]:
        d = self.site.get("disclosure") or {}
        if not isinstance(d, dict) or not d.get("enabled"):
            return None
        client = (self.site.get("client") or {}).get("name", "")
        return str(d.get("text") or "An independent publication supported by {client}.").replace("{client}", client)

    def url(self, path: str = "/") -> str:
        return self.site_url + ("/" + path.lstrip("/") if path and path != "/" else "")

    def section_for(self, post: Post) -> dict[str, Any]:
        wanted = str(post.meta.get("section") or "").strip()
        for s in self.sections:
            if wanted and (s["slug"] == wanted or s["name"].lower() == wanted.lower() or s["slug"] == slugify(wanted)):
                return s
        return self.sections[0] if self.sections else {"slug": "features", "name": "Features", "description": ""}

    def author_for(self, post: Post) -> dict[str, Any]:
        wanted = str(post.meta.get("author") or "").strip()
        if wanted:
            for a in self.authors.values():
                if a["slug"] == wanted or a["name"].lower() == wanted.lower() or a["slug"] == slugify(wanted):
                    return a
        return {"slug": slugify(wanted) or "editorial-team", "name": wanted or "Editorial Team",
                "role": "Contributor", "bio": "", "city": "", "started_at": ""}


def _norm_sections(raw: Any) -> list[dict[str, Any]]:
    out = []
    for s in raw or []:
        if isinstance(s, str):
            out.append({"slug": slugify(s), "name": s, "description": ""})
        elif isinstance(s, dict) and (s.get("name") or s.get("slug")):
            name = str(s.get("name") or s.get("slug"))
            out.append({"slug": str(s.get("slug") or slugify(name)), "name": name,
                        "description": str(s.get("description") or "")})
    return out


def _norm_authors(raw: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for a in raw or []:
        if not isinstance(a, dict) or not a.get("name"):
            continue
        slug = str(a.get("slug") or slugify(str(a["name"])))
        out[slug] = {
            "slug": slug, "name": str(a["name"]), "role": str(a.get("role") or "Staff Writer"),
            "bio": str(a.get("bio") or ""), "city": str(a.get("city") or ""),
            "started_at": str(a.get("started_at") or ""), "expertise": list(a.get("expertise") or []),
            "same_as": list(a.get("same_as") or []), "type": a.get("type") or "Person",
        }
    return out


def load_publication(root: Path, *, include_drafts: bool = False) -> Publication:
    root = Path(root)
    site_path = root / "site.yml"
    if not site_path.is_file():
        raise FileNotFoundError(f"{site_path} not found — scaffold the publication first (pub-site).")
    if yaml is None:
        raise RuntimeError("PyYAML is required — python3 -m pip install -r requirements.txt")
    site = yaml.safe_load(site_path.read_text(encoding="utf-8")) or {}
    pub = Publication(root=root, site=site, sections=_norm_sections(site.get("sections")),
                      authors=_norm_authors(site.get("authors")))
    if not pub.site_url:
        raise ValueError(f"{site_path}: site_url is required (e.g. https://example-review.com)")
    for md in sorted((root / "posts").glob("*.md")):
        meta, body = read_post(md)
        post = Post(slug=str(meta.get("slug") or md.stem), meta=meta, body_md=body, path=md)
        if post.is_draft and not include_drafts:
            pub.warnings.append(f"skipped {md.name}: draft or missing published_at")
            continue
        pub.posts.append(post)
    pub.posts.sort(key=lambda p: p.published_at, reverse=True)
    for p in pub.posts:
        a = pub.author_for(p)
        pub.authors.setdefault(a["slug"], {"expertise": [], "same_as": [], **a})
    known = {s["slug"] for s in pub.sections}
    for p in pub.posts:
        sec = str(p.meta.get("section") or "").strip()
        if sec and slugify(sec) not in known and sec not in known:
            pub.sections.append({"slug": slugify(sec), "name": sec, "description": ""})
            known.add(slugify(sec))
    return pub


def publications_root(cfg: Any) -> Path:
    """<repo>/<publications_dir> (config key `publications_dir`, default `publications`)."""
    return Path(cfg.repo_root) / str(cfg.site.get("publications_dir") or "publications")


def list_publications(cfg: Any) -> list[Path]:
    root = publications_root(cfg)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if (p / "site.yml").is_file())


def find_publication(cfg: Any, slug: Optional[str]) -> Path:
    """Resolve a publication directory by slug; with one publication and no
    slug, that one. Raises FileNotFoundError naming what exists."""
    pubs = list_publications(cfg)
    if slug:
        for p in pubs:
            if p.name == slug:
                return p
        raise FileNotFoundError(
            f"No publication {slug!r} under {publications_root(cfg)} — have: {[p.name for p in pubs] or 'none'}")
    if len(pubs) == 1:
        return pubs[0]
    raise FileNotFoundError(
        f"Pass --publication <slug>; publications under {publications_root(cfg)}: {[p.name for p in pubs] or 'none'}")


def render_markdown(body_md: str) -> str:
    if _markdown is None:
        raise RuntimeError("Markdown is required — python3 -m pip install -r requirements.txt")
    return _markdown.markdown(body_md, extensions=["extra", "sane_lists"], output_format="html5")


def process_body(pub: Publication, post: Post, asset_dir: Optional[Path]) -> None:
    """Render markdown and apply the on-page rules: heading ids, TOC list,
    nofollow on external inline links, root-relative internal links,
    resolved/lazy/dimensioned images, wrapped tables, word count."""
    soup = BeautifulSoup(render_markdown(post.body_md), "lxml")
    body = soup.body or soup
    seen_ids: set[str] = set()
    headings: list[tuple[str, str]] = []
    for h in body.find_all(["h2", "h3"]):
        text = h.get_text(" ", strip=True)
        hid = slugify(text) or "section"
        base, n = hid, 2
        while hid in seen_ids:
            hid, n = f"{base}-{n}", n + 1
        seen_ids.add(hid)
        h["id"] = hid
        if h.name == "h2":
            headings.append((hid, text))
    for a in body.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "#")):
            continue
        parsed = urlparse(href)
        if parsed.scheme in ("http", "https"):
            host = parsed.netloc.lower().removeprefix("www.")
            if host == pub.host or host.endswith("." + pub.host):
                a["href"] = parsed.path + (("?" + parsed.query) if parsed.query else "") or "/"
            else:
                a["rel"] = "noopener noreferrer nofollow"
                a["target"] = "_blank"
    for img in body.find_all("img"):
        src = (img.get("src") or "").strip()
        if not src:
            continue
        if not urlparse(src).scheme and not src.startswith("/"):
            img["src"] = f"/assets/{asset_name(post.meta, post.slug)}/{src.lstrip('./')}"
            if asset_dir is not None:
                dims = image_dimensions(asset_dir / src.lstrip("./"))
                if dims:
                    img["width"], img["height"] = str(dims[0]), str(dims[1])
        img["loading"] = "lazy"
        img["decoding"] = "async"
        if not img.has_attr("alt"):
            post.warnings.append(f"image without alt text: {src}")
    for table in body.find_all("table"):
        wrapper = soup.new_tag("div", attrs={"class": "table-wrap"})
        table.wrap(wrapper)
    post.headings = headings
    post.words = len(body.get_text(" ", strip=True).split())
    post.minutes = reading_minutes(post.words)
    post.html = "".join(str(c) for c in body.contents)


def _image_placement(pub: Publication, post: Post, cover: Any, asset_dir: Optional[Path]) -> Optional[dict[str, Any]]:
    if isinstance(cover, str):
        cover = {"src": cover}
    if not isinstance(cover, dict) or not cover.get("src"):
        return None
    src = str(cover["src"])
    asset = (post.meta.get('image_assets') or {}).get(src) or {}
    width, height = cover.get('width') or asset.get('width'), cover.get('height') or asset.get('height')
    if not urlparse(src).scheme and not src.startswith("/"):
        rel = src.lstrip("./")
        if asset_dir is not None:
            dims = image_dimensions(asset_dir / rel)
            if dims:
                width, height = dims
        src = f"/assets/{asset_name(post.meta, post.slug)}/{rel}"
    absolute = src if urlparse(src).scheme else pub.url(src)
    if 'alt' not in cover and not cover.get('decorative'):
        post.warnings.append(f'image placement needs reviewed alt text: {src}')
    variants = []
    for variant in cover.get('variants') or []:
        vsrc, vwidth = variant.get('src'), variant.get('width')
        if vsrc and type(vwidth) is int and vwidth > 0:
            if not urlparse(vsrc).scheme and not vsrc.startswith('/'):
                vsrc = f"/assets/{asset_name(post.meta, post.slug)}/{vsrc.lstrip('./')}"
            variants.append(f'{vsrc} {vwidth}w')
    return {"src": src, "absolute": absolute,
            "alt": '' if cover.get('decorative') else str(cover.get('alt') or ''),
            "caption": cover.get('caption'), 'asset': asset, 'mime': asset.get('mime'),
            'srcset': ', '.join(variants), 'sizes': cover.get('sizes'),
            "credit": cover.get("credit") or asset.get('credit_text'), "width": width, "height": height}


def cover_of(pub: Publication, post: Post, asset_dir: Optional[Path]) -> Optional[dict[str, Any]]:
    placement = post.meta.get('cover')
    cover = _image_placement(pub, post, placement, asset_dir)
    if cover and isinstance(placement, dict) and placement.get('social'):
        cover['social'] = _image_placement(pub, post, placement['social'], asset_dir)
    return cover


def _responsive_attrs(cover: dict) -> str:
    if not cover.get('srcset'):
        return ''
    return f' srcset="{_e(cover["srcset"])}" sizes="{_e(cover.get("sizes") or "100vw")}"'


def graph_ld(pub: Publication) -> dict[str, Any]:
    org: dict[str, Any] = {
        "@type": "Organization", "@id": pub.url("/#organization"), "name": pub.name, "url": pub.site_url,
        "description": pub.tagline, "logo": pub.url(f"/icons/{pub.icon}.svg"),
    }
    same_as = pub.site.get("same_as") or []
    if same_as:
        org["sameAs"] = list(same_as)
    return {"@context": "https://schema.org", "@graph": [
        org,
        {"@type": "WebSite", "@id": pub.url("/#website"), "url": pub.site_url, "name": pub.name,
         "description": pub.tagline, "inLanguage": pub.language, "publisher": {"@id": pub.url("/#organization")}},
    ]}


def _post_stub(pub: Publication, post: Post) -> dict[str, Any]:
    url = pub.url(f"/posts/{post.slug}")
    return {"@type": "BlogPosting", "@id": url + "/#article", "url": url, "headline": post.title,
            "datePublished": post.published_at}


def blog_ld(pub: Publication) -> dict[str, Any]:
    return {"@context": "https://schema.org", "@type": "Blog", "@id": pub.url("/#blog"), "url": pub.site_url,
            "name": pub.name, "description": pub.tagline, "publisher": {"@id": pub.url("/#organization")},
            "inLanguage": pub.language, "blogPost": [_post_stub(pub, p) for p in pub.posts[:20]]}


def person_ld(pub: Publication, author: dict[str, Any], *, with_id: bool = False) -> dict[str, Any]:
    person: dict[str, Any] = {"@type": author.get("type") or "Person", "name": author["name"], "jobTitle": author.get("role") or "Staff Writer",
                              "url": pub.url(f"/authors/{author['slug']}"), "worksFor": {"@id": pub.url("/#organization")}}
    if with_id:
        person["@id"] = pub.url(f"/authors/{author['slug']}/#person")
        if author.get("bio"):
            person["description"] = author["bio"]
    if author.get("same_as"):
        person["sameAs"] = list(author["same_as"])
    return person


def post_ld(pub: Publication, post: Post, cover: Optional[dict[str, Any]]) -> dict[str, Any]:
    url = pub.url(f"/posts/{post.slug}")
    section = pub.section_for(post)
    ld: dict[str, Any] = {
        "@context": "https://schema.org", "@type": "BlogPosting", "@id": url + "/#article",
        "mainEntityOfPage": {"@type": "WebPage", "@id": url}, "url": url, "headline": post.title,
        "description": post.dek,
    }
    if cover:
        image = {"@type": "ImageObject", "url": cover["absolute"], 'contentUrl': cover['absolute']}
        for key in ('caption', 'width', 'height'):
            if cover.get(key): image[key] = cover[key]
        asset = cover.get('asset') or {}
        for source, field in [('credit_text', 'creditText'), ('license_url', 'license'),
                              ('copyright_notice', 'copyrightNotice'), ('mime', 'encodingFormat')]:
            if asset.get(source): image[field] = asset[source]
        creator = asset.get('creator') or {}
        if isinstance(creator, dict) and creator.get('name') and creator.get('type') in ('Person', 'Organization'):
            image['creator'] = {'@type': creator['type'], 'name': creator['name']}
        ld["image"] = [image]
    ld.update({
        "datePublished": post.published_at, "dateModified": post.updated_at,
        "author": person_ld(pub, pub.author_for(post)), "publisher": {"@id": pub.url("/#organization")},
        "isPartOf": {"@id": pub.url("/#website")}, "articleSection": section["name"],
        "keywords": ", ".join(post.tags or [section["name"]]), "inLanguage": pub.language, "wordCount": post.words,
    })
    if post.sources:
        ld["citation"] = [{"@type": "CreativeWork", "name": s.get("title") or s["url"], "url": s["url"]} for s in post.sources]
    return ld


def breadcrumb_ld(items: list[tuple[str, Optional[str]]]) -> dict[str, Any]:
    elements = []
    for i, (name, url) in enumerate(items, start=1):
        el: dict[str, Any] = {"@type": "ListItem", "position": i, "name": name}
        if url:
            el["item"] = url
        elements.append(el)
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": elements}


def profile_ld(pub: Publication, author: dict[str, Any], posts: list[Post]) -> dict[str, Any]:
    return {"@context": "https://schema.org", "@type": "ProfilePage", "@id": pub.url(f"/authors/{author['slug']}/#profile"),
            "url": pub.url(f"/authors/{author['slug']}"), "isPartOf": {"@id": pub.url("/#website")},
            "mainEntity": person_ld(pub, author, with_id=True), "hasPart": [_post_stub(pub, p) for p in posts]}


def about_ld(pub: Publication) -> dict[str, Any]:
    return {"@context": "https://schema.org", "@type": "AboutPage", "@id": pub.url("/about/#about"), "url": pub.url("/about"),
            "name": f"About {pub.name}", "isPartOf": {"@id": pub.url("/#website")},
            "mainEntity": {"@id": pub.url("/#organization")}, "description": pub.tagline}


def collection_ld(pub: Publication, section: dict[str, Any], posts: list[Post]) -> dict[str, Any]:
    return {"@context": "https://schema.org", "@type": "CollectionPage", "@id": pub.url(f"/sections/{section['slug']}/#collection"),
            "url": pub.url(f"/sections/{section['slug']}"), "name": section["name"], "isPartOf": {"@id": pub.url("/#website")},
            "hasPart": [_post_stub(pub, p) for p in posts]}


def theme_style_attr(theme: dict[str, Any]) -> str:
    keys = ["bg", "surface", "surface_alt", "fg", "muted", "border", "primary", "primary_fg", "secondary", "accent",
            "link", "heading_color", "kicker", "hero_from", "hero_to", "font_display", "font_heading", "font_body",
            "font_mono", "radius", "content_width", "container_width"]
    parts = [f"--{k.replace('_', '-')}:{theme[k]}" for k in keys]
    parts.append(f"color-scheme:{theme['color_scheme']}")
    return ";".join(parts)


def google_fonts_href(theme: dict[str, Any]) -> str:
    families = "&".join(f"family={f}" for f in theme.get("google_fonts") or [])
    return f"https://fonts.googleapis.com/css2?{families}&display=swap" if families else ""


STYLESHEET = """
*,*::before,*::after{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font-family:var(--font-body);line-height:1.6;font-size:1.0625rem}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}img{max-width:100%;height:auto;display:block}
.skip{position:absolute;left:-999px}.skip:focus{left:1rem;top:1rem;background:var(--primary);color:var(--primary-fg);padding:.5rem 1rem;z-index:10}
.container{max-width:var(--container-width);margin:0 auto;padding:0 1.25rem}.content{max-width:var(--content-width);margin:0 auto}
header.site{border-bottom:1px solid var(--border);background:var(--bg)}header.site .row{display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:.9rem 0}
.brand{display:flex;align-items:center;gap:.6rem;font-family:var(--font-display);font-weight:800;font-size:1.35rem;color:var(--heading-color);letter-spacing:-.01em}
.brand img{width:28px;height:28px;border-radius:7px}nav.sections a{font-family:var(--font-heading);font-size:.78rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-left:1.1rem;font-weight:600}
nav.sections a:hover,nav.sections a[aria-current]{color:var(--primary);text-decoration:none}.dateline{font-family:var(--font-mono);font-size:.72rem;color:var(--muted);text-align:center;margin:.6rem 0 0;letter-spacing:.06em;text-transform:uppercase}
.kicker{font-family:var(--font-heading);font-size:.74rem;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:var(--kicker);margin:0 0 .6rem}
.rule-label{font-family:var(--font-heading);font-size:.74rem;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);border-top:1px solid var(--border);padding-top:.8rem;margin:2.5rem 0 1rem}
h1,h2,h3{font-family:var(--font-heading);color:var(--heading-color);line-height:1.15;letter-spacing:-.02em;margin:0 0 .6rem}
h1{font-family:var(--font-display);font-size:clamp(2rem,4.5vw,3.25rem);font-weight:800}h2{font-size:1.55rem;font-weight:700;margin-top:2.4rem}h3{font-size:1.15rem;font-weight:700}
.dek{font-size:1.25rem;color:var(--muted);margin:0 0 1.2rem;line-height:1.45}
.byline{display:flex;align-items:center;gap:.7rem;font-size:.9rem;color:var(--muted);margin:1rem 0}.byline a{color:var(--fg);font-weight:600}
.avatar{width:36px;height:36px;border-radius:50%;background:var(--primary);color:var(--primary-fg);display:inline-flex;align-items:center;justify-content:center;font-weight:700;font-size:.8rem;font-family:var(--font-heading);flex:none}
.share{display:flex;gap:.6rem;margin:.6rem 0 1.4rem}.share a{font-size:.75rem;font-weight:600;border:1px solid var(--border);border-radius:999px;padding:.3rem .7rem;color:var(--muted)}
figure.cover{margin:1.5rem 0}figure.cover img{width:100%;border-radius:var(--radius);background:var(--surface)}figure.cover figcaption{font-size:.8rem;color:var(--muted);margin-top:.5rem}
.toc{background:var(--surface);border-radius:var(--radius);padding:1rem 1.25rem;margin:1.5rem 0}.toc .rule-label{border:0;margin:0 0 .5rem;padding:0}.toc ol{margin:0;padding-left:1.2rem}.toc li{margin:.3rem 0;font-size:.95rem}
.prose>p{margin:0 0 1.2rem}.prose>ul,.prose>ol{margin:0 0 1.2rem;padding-left:1.4rem}.prose li{margin:.35rem 0}.prose img{margin:1.8rem auto;border-radius:var(--radius)}
.prose blockquote{margin:1.5rem 0;padding:.2rem 1.2rem;border-left:3px solid var(--primary);color:var(--muted)}.table-wrap{overflow-x:auto;margin:1.5rem 0}
table{border-collapse:collapse;width:100%;font-size:.95rem}th,td{border:1px solid var(--border);padding:.6rem .8rem;text-align:left;vertical-align:top}th{background:var(--surface);font-family:var(--font-heading)}
code,pre{font-family:var(--font-mono);font-size:.9em}pre{background:var(--surface);padding:1rem;border-radius:var(--radius);overflow-x:auto}
.sources ol{list-style:none;padding:0;margin:0}.sources li{display:flex;gap:.8rem;font-size:.92rem;margin:.5rem 0}.sources li span{font-family:var(--font-mono);color:var(--muted);flex:none}
.filed{margin:2rem 0 1rem;font-size:.9rem;color:var(--muted)}.author-box{display:flex;gap:1rem;border-top:1px solid var(--border);border-bottom:1px solid var(--border);padding:1.4rem 0;margin:2rem 0}
.author-box h2{margin:0 0 .3rem;font-size:1.15rem}.author-box p{margin:0 0 .4rem;font-size:.95rem;color:var(--muted)}
.next{margin:1.4rem 0;font-size:.95rem}.disclosure{font-size:.85rem;color:var(--muted);margin:1.5rem 0 0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:1.4rem;margin:1.5rem 0 2.5rem}
.card{display:flex;flex-direction:column;gap:.5rem}.card img{aspect-ratio:16/9;object-fit:cover;width:100%;border-radius:var(--radius);background:var(--surface)}
.card h3{margin:.2rem 0}.card h3 a{color:var(--heading-color)}.card p{margin:0;color:var(--muted);font-size:.95rem}.card .meta{font-size:.8rem}
.hero{display:grid;grid-template-columns:1.2fr 1fr;gap:2rem;align-items:center;padding:2rem 0;border-bottom:1px solid var(--border)}.hero img{border-radius:var(--radius);width:100%}
@media(max-width:800px){.hero{grid-template-columns:1fr}nav.sections{display:none}}
footer.site{border-top:1px solid var(--border);margin-top:3rem;padding:2.5rem 0;color:var(--muted);font-size:.9rem;background:var(--surface)}
footer.site .cols{display:grid;grid-template-columns:2fr 1fr 1fr;gap:2rem}footer.site h2{font-size:.78rem;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin:0 0 .6rem}
footer.site ul{list-style:none;padding:0;margin:0}footer.site li{margin:.3rem 0}@media(max-width:700px){footer.site .cols{grid-template-columns:1fr}}
.search input{width:100%;padding:.8rem 1rem;font-size:1rem;border:1px solid var(--border);border-radius:var(--radius);background:var(--bg);color:var(--fg)}
"""


def _initials(name: str) -> str:
    parts = [p for p in re.split(r"\s+", name.strip()) if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


def _nav(pub: Publication, current: Optional[str] = None) -> str:
    links = []
    for section in pub.sections:
        active = ' aria-current="page"' if current == section['slug'] else ''
        links.append(f'<a href="/sections/{_e(section["slug"])}"{active}>{_e(section["name"])}</a>')
    links = ''.join(links)
    return (f'<header class="site"><div class="container"><div class="row">'
            f'<a class="brand" href="/"><img src="/icons/{_e(pub.icon)}.svg" alt="" width="28" height="28">{_e(pub.name)}</a>'
            f'<nav class="sections" aria-label="Sections">{links}<a href="/search">Search</a></nav></div></div></header>')


def _footer(pub: Publication, build_year: int) -> str:
    sections = "".join(f'<li><a href="/sections/{_e(s["slug"])}">{_e(s["name"])}</a></li>' for s in pub.sections)
    disclosure = f'<p class="disclosure">{_e(pub.disclosure)}</p>' if pub.disclosure else ""
    return (f'<footer class="site"><div class="container"><div class="cols">'
            f'<div><h2>{_e(pub.name)}</h2><p>{_e(pub.tagline)}</p>{disclosure}</div>'
            f'<div><h2>Sections</h2><ul>{sections}</ul></div>'
            f'<div><h2>{_e(pub.name)}</h2><ul><li><a href="/">Latest</a></li><li><a href="/about">About</a></li>'
            f'<li><a href="/feed.xml">RSS Feed</a></li></ul></div></div>'
            f'<p>© {build_year} {_e(pub.name)}. All rights reserved.</p></div></footer>')


def _page(pub: Publication, *, title: str, description: str, canonical_path: str, body: str, ld: list[dict[str, Any]],
          og: dict[str, str], build_year: int, noindex: bool = False, current_section: Optional[str] = None,
          extra_head: str = "") -> str:
    theme = pub.theme
    fonts = google_fonts_href(theme)
    robots = ('<meta name="robots" content="noindex">' if noindex else
              '<meta name="robots" content="index, follow">'
              '<meta name="googlebot" content="index, follow, max-video-preview:-1, max-image-preview:large, max-snippet:-1">')
    og_tags = "".join(f'<meta property="{_e(k)}" content="{_e(v)}">' for k, v in og.items() if v and k.startswith(("og:", "article:")))
    tw_tags = "".join(f'<meta name="{_e(k)}" content="{_e(v)}">' for k, v in og.items() if v and k.startswith("twitter:"))
    head = (
        f'<!DOCTYPE html><html lang="{_e(pub.language)}" data-theme="{_e(pub.theme_name)}" style="{_e(theme_style_attr(theme))}">'
        f'<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{_e(title)}</title><meta name="description" content="{_e(description)}">'
        f'<meta name="application-name" content="{_e(pub.name)}">{robots}'
        f'<link rel="canonical" href="{_e(pub.url(canonical_path))}">'
        f'<link rel="alternate" type="application/rss+xml" title="{_e(pub.name)}" href="{_e(pub.url("/feed.xml"))}">'
        f'<link rel="icon" href="/icons/{_e(pub.icon)}.svg" type="image/svg+xml">'
        + (f'<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
           f'<link rel="stylesheet" href="{_e(fonts)}">' if fonts else "")
        + f'<link rel="stylesheet" href="/styles.css">{og_tags}{tw_tags}{extra_head}'
        + "".join(_jsonld(x) for x in ld) + "</head>"
    )
    return (head + f'<body><a class="skip" href="#main">Skip to content</a>{_nav(pub, current_section)}'
            f'<main id="main" class="container">{body}</main>{_footer(pub, build_year)}</body></html>')


def _card(pub: Publication, post: Post, cover: Optional[dict[str, Any]], *, heading: str = "h3") -> str:
    section = pub.section_for(post)
    author = pub.author_for(post)
    img = ""
    if cover:
        dims = f' width="{_e(cover["width"])}" height="{_e(cover["height"])}"' if cover.get("width") and cover.get("height") else ""
        img = f'<a href="/posts/{_e(post.slug)}" aria-label="{_e(post.title)}"><img src="{_e(cover["src"])}" alt="{_e(cover["alt"])}" loading="lazy" decoding="async"{dims}{_responsive_attrs(cover)}></a>'
    return (f'<article class="card">{img}<p class="kicker"><a href="/sections/{_e(section["slug"])}">{_e(section["name"])}</a></p>'
            f'<{heading}><a href="/posts/{_e(post.slug)}">{_e(post.title)}</a></{heading}><p>{_e(post.dek)}</p>'
            f'<p class="meta"><a href="/authors/{_e(author["slug"])}">{_e(author["name"])}</a> · '
            f'<time datetime="{_e(post.published_at)}">{_e(display_date(post.published_at))}</time></p></article>')


def _share(pub: Publication, post: Post) -> str:
    from urllib.parse import quote
    url = quote(pub.url(f"/posts/{post.slug}"), safe="")
    title = quote(post.title, safe="")
    return (f'<div class="share">'
            f'<a href="https://twitter.com/intent/tweet?text={title}&amp;url={url}" rel="noopener noreferrer" target="_blank">Share on X</a>'
            f'<a href="https://www.linkedin.com/sharing/share-offsite/?url={url}" rel="noopener noreferrer" target="_blank">LinkedIn</a>'
            f'<a href="https://www.facebook.com/sharer/sharer.php?u={url}" rel="noopener noreferrer" target="_blank">Facebook</a>'
            f'<a href="mailto:?subject={title}&amp;body={url}">Email</a></div>')


def render_post_page(pub: Publication, post: Post, cover: Optional[dict[str, Any]], covers: dict[str, Optional[dict[str, Any]]],
                     build_year: int) -> str:
    section = pub.section_for(post)
    author = pub.author_for(post)
    url_path = f"/posts/{post.slug}"
    toc = ""
    if post.headings:
        items = "".join(f'<li><a href="#{_e(hid)}">{_e(text)}</a></li>' for hid, text in post.headings)
        toc = f'<nav class="toc" aria-label="In this article"><p class="rule-label">In this article</p><ol>{items}</ol></nav>'
    cover_html = ""
    if cover:
        dims = f' width="{_e(cover["width"])}" height="{_e(cover["height"])}"' if cover.get("width") and cover.get("height") else ""
        credit = f" · {_e(cover['credit'])}" if cover.get("credit") else ""
        caption = f'<span>{_e(cover["caption"])}</span> · ' if cover.get('caption') else ''
        cover_html = (f'<figure class="cover"><img src="{_e(cover["src"])}" alt="{_e(cover["alt"])}" fetchpriority="high" decoding="async"{dims}{_responsive_attrs(cover)}>'
                      f'<figcaption>{caption}{_e(section["name"])} · {_e(display_date(post.published_at))} · {post.minutes} min read · {post.words:,} words{credit}</figcaption></figure>')
    sources_html = ""
    if post.sources:
        lis = "".join(
            f'<li><span>{i:02d}</span><a href="{_e(s["url"])}" target="_blank" rel="noopener noreferrer">'
            f'{_e(s.get("title") or urlparse(s["url"]).netloc.removeprefix("www."))}</a></li>'
            for i, s in enumerate(post.sources, start=1))
        sources_html = f'<section class="sources"><h2 id="sources-heading" class="rule-label">Sources</h2><ol>{lis}</ol></section>'
    updated = (f' · Updated <time datetime="{_e(post.updated_at)}">{_e(display_date(post.updated_at))}</time>'
               if post.updated_at and post.updated_at[:10] != post.published_at[:10] else "")
    related = [p for p in pub.posts if p.slug != post.slug and pub.section_for(p)["slug"] == section["slug"]][:RELATED_LIMIT]
    if len(related) < RELATED_LIMIT:
        related += [p for p in pub.posts if p.slug != post.slug and p not in related][:RELATED_LIMIT - len(related)]
    newer = [p for p in pub.posts if p.published_at > post.published_at]
    next_post = newer[-1] if newer else None
    author_meta = " · ".join(x for x in [author.get("role"), author.get("city")] if x)
    body = (
        f'<article><nav aria-label="Breadcrumb" class="kicker"><a href="/">Home</a> / <a href="/sections/{_e(section["slug"])}">{_e(section["name"])}</a></nav>'
        f'<div class="content"><p class="kicker">{_e(section["name"])} · {_e(post.kicker)}</p><h1>{_e(post.title)}</h1><p class="dek">{_e(post.dek)}</p>'
        f'<div class="byline"><span class="avatar" aria-hidden="true">{_e(_initials(author["name"]))}</span>'
        f'<span><a href="/authors/{_e(author["slug"])}">{_e(author["name"])}</a> · {_e(author.get("role") or "")} · '
        f'<time datetime="{_e(post.published_at)}">{_e(display_date(post.published_at))}</time> · {post.minutes} min read{updated}</span></div>'
        f'{_share(pub, post)}{cover_html}{toc}<div class="prose">{post.html}</div>{sources_html}'
        f'<p class="filed">Filed under <a href="/sections/{_e(section["slug"])}">{_e(section["name"])}</a></p>{_share(pub, post)}'
        f'<aside class="author-box"><span class="avatar" aria-hidden="true">{_e(_initials(author["name"]))}</span><div>'
        f'<p class="kicker">Written by</p><h2><a href="/authors/{_e(author["slug"])}">{_e(author["name"])}</a></h2>'
        f'<p>{_e(author_meta)}</p><p>{_e(author.get("bio") or "")}</p><a href="/authors/{_e(author["slug"])}">View all stories →</a></div></aside>'
        + (f'<p class="next">Next story: <a href="/posts/{_e(next_post.slug)}">{_e(next_post.title)}</a></p>' if next_post else "")
        + "</div></article>"
        + (f'<section><h2 class="rule-label">More in {_e(section["name"])}</h2><div class="grid">'
           + "".join(_card(pub, p, covers.get(p.slug)) for p in related) + "</div></section>" if related else "")
    )
    og = {
        "og:title": post.title, "og:description": post.dek, "og:url": pub.url(url_path), "og:site_name": pub.name,
        "og:locale": "en_US" if pub.language.startswith("en") else pub.language, "og:type": "article",
        "article:published_time": post.published_at, "article:modified_time": post.updated_at,
        "article:author": author["name"], "article:section": section["name"], "article:tag": ", ".join(post.tags or [section["name"]]),
        "twitter:card": "summary_large_image", "twitter:title": post.title, "twitter:description": post.dek,
    }
    if cover:
        social = cover.get('social') or cover
        og.update({"og:image": social["absolute"], "og:image:alt": social["alt"], "twitter:image": social["absolute"], 'twitter:image:alt': social['alt']})
        if social.get("width") and social.get("height"):
            og.update({"og:image:width": str(social["width"]), "og:image:height": str(social["height"])})
        if social.get('mime'): og['og:image:type'] = social['mime']
    seo = post.meta.get("seo") or {}
    ld = [graph_ld(pub), post_ld(pub, post, cover),
          breadcrumb_ld([("Home", pub.site_url), (section["name"], pub.url(f"/sections/{section['slug']}")), (post.title, None)])]
    extra_head = f'<link rel="preload" as="image" href="{_e(cover["src"])}" fetchpriority="high">' if cover and not cover.get('srcset') else ""
    return _page(pub, title=str(seo.get("title") or f"{post.title} · {pub.name}"), description=str(seo.get("description") or post.dek),
                 canonical_path=url_path, body=body, ld=ld, og=og, build_year=build_year, current_section=section["slug"],
                 extra_head=extra_head)


def render_home(pub: Publication, covers: dict[str, Optional[dict[str, Any]]], build_time: datetime) -> str:
    latest = pub.posts[:HOME_LIMIT]
    hero = ""
    if latest:
        p = latest[0]
        c = covers.get(p.slug)
        img = f'<a href="/posts/{_e(p.slug)}"><img src="{_e(c["src"])}" alt="{_e(c["alt"])}" fetchpriority="high" decoding="async"></a>' if c else ""
        hero = (f'<section class="hero"><div><p class="kicker">{_e(pub.section_for(p)["name"])} · Latest</p><h2><a href="/posts/{_e(p.slug)}">{_e(p.title)}</a></h2>'
                f'<p class="dek">{_e(p.dek)}</p><p class="meta">{_e(pub.author_for(p)["name"])} · {_e(display_date(p.published_at))} · {p.minutes} min read</p></div><div>{img}</div></section>')
    established = pub.site.get("established") or (parse_iso(pub.posts[-1].published_at).year if pub.posts and parse_iso(pub.posts[-1].published_at) else build_time.year)
    body = (f'<p class="dateline">{_e(build_time.strftime("%A, %B ") + str(build_time.day) + build_time.strftime(", %Y"))} · Est. {_e(established)}</p>'
            f'<h1 class="brand" style="justify-content:center;font-size:2.4rem;margin:.4rem 0 .2rem">{_e(pub.name)}</h1><p class="dek" style="text-align:center">{_e(pub.tagline)}</p>'
            + hero + '<h2 class="rule-label">Latest</h2><div class="grid">'
            + "".join(_card(pub, p, covers.get(p.slug)) for p in latest[1:]) + "</div>")
    og = {"og:title": pub.name, "og:description": pub.tagline, "og:url": pub.site_url, "og:site_name": pub.name, "og:type": "website",
          "twitter:card": "summary_large_image", "twitter:title": pub.name, "twitter:description": pub.tagline}
    og_image = pub.url("/og-default.png") if (pub.root / "static" / "og-default.png").is_file() else (covers.get(latest[0].slug) or {}).get("absolute") if latest else None
    if og_image:
        og.update({"og:image": og_image, "twitter:image": og_image, "og:image:alt": pub.name})
    return _page(pub, title=pub.name, description=pub.tagline, canonical_path="/", body=body,
                 ld=[graph_ld(pub), blog_ld(pub)], og=og, build_year=build_time.year)


def render_section(pub: Publication, section: dict[str, Any], posts: list[Post], covers: dict[str, Optional[dict[str, Any]]], build_year: int) -> str:
    count = f"{len(posts)} {'story' if len(posts) == 1 else 'stories'} in {section['name']}."
    body = (f'<p class="kicker">Section</p><h1>{_e(section["name"])}</h1><p class="dek">{_e(section.get("description") or count)}</p>'
            f'<div class="grid">' + "".join(_card(pub, p, covers.get(p.slug)) for p in posts) + "</div>")
    og = {"og:title": f"{section['name']} · {pub.name}", "og:description": section.get("description") or count,
          "og:url": pub.url(f"/sections/{section['slug']}"), "og:site_name": pub.name, "og:type": "website",
          "twitter:card": "summary_large_image", "twitter:title": f"{section['name']} · {pub.name}"}
    return _page(pub, title=f"{section['name']} · {pub.name}", description=section.get("description") or count,
                 canonical_path=f"/sections/{section['slug']}", body=body, ld=[graph_ld(pub), collection_ld(pub, section, posts)],
                 og=og, build_year=build_year, current_section=section["slug"])


def render_author(pub: Publication, author: dict[str, Any], posts: list[Post], covers: dict[str, Optional[dict[str, Any]]], build_year: int) -> str:
    n = len(posts)
    meta_line = " · ".join(x for x in [f"{n} {'story' if n == 1 else 'stories'}", author.get("city")] if x)
    body = (f'<div class="byline"><span class="avatar" aria-hidden="true">{_e(_initials(author["name"]))}</span><span class="kicker">{_e(author.get("role") or "")}</span></div>'
            f'<h1>{_e(author["name"])}</h1><p class="dek">{_e(author.get("bio") or "")}</p><p class="meta">{_e(meta_line)}</p>'
            f'<div class="grid">' + "".join(_card(pub, p, covers.get(p.slug)) for p in posts) + "</div>")
    description = author.get("bio") or f"{author['name']} writes for {pub.name}."
    og = {"og:title": f"{author['name']} · {pub.name}", "og:description": description, "og:url": pub.url(f"/authors/{author['slug']}"),
          "og:type": "profile", "twitter:card": "summary_large_image", "twitter:title": f"{author['name']} · {pub.name}"}
    return _page(pub, title=f"{author['name']} · {pub.name}", description=description, canonical_path=f"/authors/{author['slug']}",
                 body=body, ld=[graph_ld(pub), profile_ld(pub, author, posts)], og=og, build_year=build_year)


def render_about(pub: Publication, build_year: int) -> str:
    sections = "".join(f'<li><a href="/sections/{_e(s["slug"])}">{_e(s["name"])}</a>{(" — " + _e(s["description"])) if s.get("description") else ""}</li>' for s in pub.sections)
    contributors = "".join(f'<li><a href="/authors/{_e(a["slug"])}">{_e(a["name"])}</a> · {_e(a.get("role") or "")}</li>' for a in pub.authors.values())
    disclosure = f'<p class="disclosure">{_e(pub.disclosure)}</p>' if pub.disclosure else ""
    body = (f'<p class="kicker">About</p><h1>{_e(pub.name)}</h1><p class="dek">{_e(pub.tagline)}</p>{disclosure}'
            f'<h2 class="rule-label">What we cover</h2><ul>{sections}</ul><h2 class="rule-label">Contributors</h2><ul>{contributors}</ul>')
    og = {"og:title": f"About {pub.name}", "og:description": pub.tagline, "og:url": pub.url("/about"), "og:site_name": pub.name,
          "og:type": "website", "twitter:card": "summary_large_image", "twitter:title": pub.name}
    return _page(pub, title=f"About · {pub.name}", description=pub.tagline, canonical_path="/about", body=body,
                 ld=[graph_ld(pub), about_ld(pub)], og=og, build_year=build_year)


def render_search(pub: Publication, build_year: int) -> str:
    index = [{"t": p.title, "u": f"/posts/{p.slug}", "d": p.dek, "s": pub.section_for(p)["name"], "a": pub.author_for(p)["name"],
              "p": display_date(p.published_at)} for p in pub.posts]
    serialized_index = json.dumps(index, ensure_ascii=False).replace("</", "<\\/")
    script = ('<script>(function(){var d=JSON.parse(document.getElementById("search-index").textContent),q=document.getElementById("q"),r=document.getElementById("results");'
              'function go(){var v=q.value.trim().toLowerCase();r.innerHTML="";if(!v)return;d.filter(function(p){return (p.t+" "+p.d+" "+p.s).toLowerCase().indexOf(v)>-1}).slice(0,30).forEach(function(p){'
              'var a=document.createElement("article");a.className="card";a.innerHTML="<p class=kicker>"+p.s+"</p><h3><a href=\\""+p.u+"\\"></a></h3><p></p><p class=meta>"+p.a+" · "+p.p+"</p>";'
              'a.querySelector("h3 a").textContent=p.t;a.querySelectorAll("p")[1].textContent=p.d;r.appendChild(a)})}q.addEventListener("input",go)})();</script>')
    body = (f'<p class="kicker">Search</p><h1>Search</h1><p class="dek">Find any article across the publication. Start typing to search.</p>'
            f'<div class="search"><label class="skip" for="q">Search articles</label><input id="q" type="search" placeholder="Search articles…" autocomplete="off"></div>'
            f'<div id="results" class="grid"></div><script type="application/json" id="search-index">{serialized_index}</script>{script}')
    og = {"og:title": pub.name, "og:description": pub.tagline, "og:url": pub.site_url, "og:site_name": pub.name, "og:type": "website",
          "twitter:card": "summary_large_image", "twitter:title": pub.name}
    return _page(pub, title=f"Search · {pub.name}", description=pub.tagline, canonical_path="/search", body=body,
                 ld=[graph_ld(pub)], og=og, build_year=build_year, noindex=True)


def render_rss(pub: Publication) -> str:
    items = []
    for p in pub.posts[:RSS_LIMIT]:
        dt = parse_iso(p.published_at)
        items.append(
            f"    <item>\n      <title>{_e(p.title)}</title>\n      <link>{_e(pub.url(f'/posts/{p.slug}'))}</link>\n"
            f"      <guid isPermaLink=\"true\">{_e(pub.url(f'/posts/{p.slug}'))}</guid>\n      <description>{_e(p.dek)}</description>\n"
            f"      <dc:creator>{_e(pub.author_for(p)['name'])}</dc:creator>\n      <category>{_e(pub.section_for(p)['name'])}</category>\n"
            + (f"      <pubDate>{format_datetime(dt)}</pubDate>\n" if dt else "") + "    </item>")
    newest = parse_iso(pub.posts[0].published_at) if pub.posts else None
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:atom="http://www.w3.org/2005/Atom">\n  <channel>\n'
            f"    <title>{_e(pub.name)}</title>\n    <link>{_e(pub.site_url)}</link>\n    <description>{_e(pub.tagline)}</description>\n"
            f"    <language>{_e(pub.language)}</language>\n" + (f"    <lastBuildDate>{format_datetime(newest)}</lastBuildDate>\n" if newest else "")
            + f'    <atom:link href="{_e(pub.url("/feed.xml"))}" rel="self" type="application/rss+xml"/>\n'
            + "\n".join(items) + ("\n" if items else "") + "  </channel>\n</rss>\n")


def render_llms_txt(pub: Publication) -> str:
    lines = [f"# {pub.name}", "", f"> {pub.tagline}", "", "## Posts", ""]
    for p in pub.posts:
        lines.append(f"- [{p.title}]({pub.url(f'/posts/{p.slug}')}): {p.dek}")
    return "\n".join(lines) + "\n"


def render_sitemap(pub: Publication) -> str:
    def entry(loc: str, lastmod: str, changefreq: str, priority: str) -> str:
        lm = f"<lastmod>{_e(lastmod)}</lastmod>" if lastmod else ""
        return f"<url><loc>{_e(loc)}</loc>{lm}<changefreq>{changefreq}</changefreq><priority>{priority}</priority></url>"

    newest = pub.posts[0].updated_at if pub.posts else ""
    rows = [entry(pub.site_url, newest, "daily", "1")]
    for s in pub.sections:
        in_sec = [p for p in pub.posts if pub.section_for(p)["slug"] == s["slug"]]
        rows.append(entry(pub.url(f"/sections/{s['slug']}"), in_sec[0].updated_at if in_sec else newest, "weekly", "0.5"))
    for a in pub.authors.values():
        by = [p for p in pub.posts if pub.author_for(p)["slug"] == a["slug"]]
        rows.append(entry(pub.url(f"/authors/{a['slug']}"), by[0].updated_at if by else newest, "weekly", "0.4"))
    rows.append(entry(pub.url("/about"), newest, "monthly", "0.3"))
    for p in pub.posts:
        rows.append(entry(pub.url(f"/posts/{p.slug}"), p.updated_at, "monthly", "0.7"))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(rows) + "\n</urlset>\n")


def render_robots(pub: Publication) -> str:
    return f"User-Agent: *\nAllow: /\n\nHost: {pub.site_url}\nSitemap: {pub.url('/sitemap.xml')}\n"


def build_site(pub: Publication, out_dir: Optional[Path] = None, *, build_time: Optional[datetime] = None) -> dict[str, Any]:
    """Render the whole publication into dist/ (or out_dir). Returns a
    manifest {out_dir, pages, posts, warnings}. Idempotent: the output
    directory is cleared first so removed posts do not linger."""
    build_time = build_time or datetime.now(timezone.utc)
    out = Path(out_dir) if out_dir else pub.root / "dist"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    pages: list[str] = []

    def write(rel: str, content: str) -> None:
        path = out / rel.lstrip("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        pages.append("/" + rel.lstrip("/"))

    covers: dict[str, Optional[dict[str, Any]]] = {}
    for post in pub.posts:
        asset_dir = pub.root / "assets" / asset_name(post.meta, post.slug)
        process_body(pub, post, asset_dir if asset_dir.is_dir() else None)
        covers[post.slug] = cover_of(pub, post, asset_dir if asset_dir.is_dir() else None)
        if asset_dir.is_dir():
            shutil.copytree(asset_dir, out / "assets" / asset_name(post.meta, post.slug), dirs_exist_ok=True)
    static = pub.root / "static"
    if static.is_dir():
        shutil.copytree(static, out, dirs_exist_ok=True)

    write("styles.css", STYLESHEET.strip() + "\n")
    write(f"icons/{pub.icon}.svg", icon_svg(pub.icon, pub.theme["primary"]))
    write("index.html", render_home(pub, covers, build_time))
    for post in pub.posts:
        write(f"posts/{post.slug}/index.html", render_post_page(pub, post, covers[post.slug], covers, build_time.year))
    for section in pub.sections:
        in_sec = [p for p in pub.posts if pub.section_for(p)["slug"] == section["slug"]]
        write(f"sections/{section['slug']}/index.html", render_section(pub, section, in_sec, covers, build_time.year))
    for author in pub.authors.values():
        by = [p for p in pub.posts if pub.author_for(p)["slug"] == author["slug"]]
        write(f"authors/{author['slug']}/index.html", render_author(pub, author, by, covers, build_time.year))
    write("about/index.html", render_about(pub, build_time.year))
    write("search/index.html", render_search(pub, build_time.year))
    write("feed.xml", render_rss(pub))
    write("llms.txt", render_llms_txt(pub))
    write("sitemap.xml", render_sitemap(pub))
    write("robots.txt", render_robots(pub))
    write("404.html", _page(pub, title=f"Not found · {pub.name}", description=pub.tagline, canonical_path="/404",
                            body='<h1>Page not found</h1><p class="dek">That story is not here. <a href="/">Back to the latest.</a></p>',
                            ld=[graph_ld(pub)], og={}, build_year=build_time.year, noindex=True))
    write("vercel.json", json.dumps({"cleanUrls": True, "trailingSlash": False,
                                     "headers": [{"source": "/assets/(.*)", "headers": [{"key": "Cache-Control", "value": "public, max-age=31536000, immutable"}]}]}, indent=2))
    warnings = list(pub.warnings)
    for post in pub.posts:
        warnings.extend(f"{post.slug}: {w}" for w in post.warnings)
    return {"out_dir": str(out), "pages": pages, "posts": len(pub.posts), "warnings": warnings}
