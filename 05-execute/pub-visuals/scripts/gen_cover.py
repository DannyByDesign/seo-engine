"""pub-visuals: mint an article's cover image from its headline in the
publication's house style, and record it in the frontmatter.

Providers (scripts/lib/images.py): OpenAI Images or Gemini image models,
BYOK. With no image key — or `--provider svg` — a deterministic SVG cover is
drawn from the theme (hero gradient + abstract geometry, no text), so the
pipeline never blocks on a missing key. Covers are 16:9 (the measured phantoms
declare 1200x675 for OG and serve the hero at 1600 px).

House prompt: site.yml `cover_style` when set, else derived from the theme
palette: flat vector editorial illustration, geometric, two accent colours
on the theme surface, no text, no logos, no people's faces.

Alt text convention (measured): `Cover illustration for “<title>”`.

Usage:
    python3 gen_cover.py --publication llm-billboard --slug advertiser-readiness
    python3 gen_cover.py --publication llm-billboard --slug advertiser-readiness --provider svg
    python3 gen_cover.py --publication llm-billboard --slug advertiser-readiness --posts --force --provider gemini
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
import hashlib
import json
import random
from typing import Any

from scripts.lib import images, publication, pubstate

COVER_W, COVER_H = 1600, 900


def house_prompt(pub: publication.Publication, title: str, dek: str) -> str:
    theme = pub.theme
    style = str(pub.site.get("cover_style") or "").strip() or (
        f"flat vector editorial illustration, clean geometric shapes, generous negative space, palette limited to "
        f"{theme['primary']}, {theme['accent']} and {theme['secondary']} on {theme['surface']}, subtle grain")
    return (f"{style}. Concept: an abstract visual metaphor for \"{title}\" ({dek}). No text, no letters, no numbers, no logos, "
            f"no human faces, no watermarks. Landscape 16:9 composition with the subject weighted to the right third.")


def svg_cover(pub: publication.Publication, seed_text: str) -> str:
    theme = pub.theme
    rng = random.Random(int(hashlib.sha256(seed_text.encode()).hexdigest(), 16) % (2 ** 32))
    shapes = []
    palette = [theme["primary"], theme["accent"], theme["secondary"], theme["fg"]]
    for i in range(9):
        color = palette[i % len(palette)]
        kind = rng.choice(["circle", "ring", "bar", "tri"])
        x, y = rng.randint(820, 1500), rng.randint(100, 800)
        if kind == "circle":
            shapes.append(f'<circle cx="{x}" cy="{y}" r="{rng.randint(20, 140)}" fill="{color}" fill-opacity="{rng.uniform(0.5, 0.95):.2f}"/>')
        elif kind == "ring":
            shapes.append(f'<circle cx="{x}" cy="{y}" r="{rng.randint(80, 260)}" fill="none" stroke="{color}" stroke-width="{rng.randint(10, 40)}"/>')
        elif kind == "bar":
            shapes.append(f'<rect x="{x}" y="{y}" width="{rng.randint(30, 90)}" height="{rng.randint(120, 420)}" rx="14" fill="{color}" transform="rotate({rng.randint(-30, 30)} {x} {y})"/>')
        else:
            shapes.append(f'<path d="M{x},{y} l{rng.randint(80, 220)},{rng.randint(-60, 60)} l{rng.randint(-120, 40)},{rng.randint(90, 220)} z" fill="{color}" fill-opacity="0.9"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {COVER_W} {COVER_H}" width="{COVER_W}" height="{COVER_H}" role="img">'
            f'<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{theme["surface"]}"/>'
            f'<stop offset="1" stop-color="{theme["surface_alt"]}"/></linearGradient></defs>'
            f'<rect width="{COVER_W}" height="{COVER_H}" fill="url(#bg)"/>{"".join(shapes)}</svg>\n')


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an article cover in the house style.")
    parser.add_argument("--publication", help="Publication slug")
    parser.add_argument("--slug", required=True, help="Article slug")
    parser.add_argument("--posts", action="store_true", help="Article lives in posts/ (default drafts/)")
    parser.add_argument("--provider", choices=["openai", "gemini", "svg"], help="Image provider (default: configured key, else svg)")
    parser.add_argument("--model", help="Override the image model id")
    parser.add_argument("--force", action="store_true", help="Regenerate even if a cover exists")
    parser.add_argument("--publications-dir", help="Override the publications directory")
    args = parser.parse_args()

    cfg = config_module.load()
    if args.publications_dir:
        cfg.site["publications_dir"] = args.publications_dir
    root = publication.find_publication(cfg, args.publication)
    pub = publication.load_publication(root, include_drafts=True)
    path = root / ("posts" if args.posts else "drafts") / f"{args.slug}.md"
    if not path.is_file():
        print(json.dumps({"checked": False, "error": f"{path} not found"}, indent=2))
        return 1
    meta, body = publication.read_post(path)
    if args.posts:
        print(json.dumps({'checked': False, 'error': 'generate visuals on an isolated refresh draft, not a published post'})); return 1
    existing = meta.get("cover") if isinstance(meta.get("cover"), dict) else None
    if existing and existing.get("src") and not args.force:
        print(json.dumps({"checked": True, "skipped": True, "reason": "cover exists (pass --force)", "cover": existing}, indent=2))
        return 0
    title = str(meta.get("title") or args.slug)
    asset_dir = publication.draft_assets(root, args.slug, meta)
    result: dict[str, Any] = {"checked": True, "file": str(path), "title": title}
    provider = args.provider
    if provider is None:
        provider = images.configured_image_providers(cfg)[0] if images.configured_image_providers(cfg) else "svg"
    if provider == "svg":
        out = asset_dir / "cover.svg"
        out.write_text(svg_cover(pub, args.slug), encoding="utf-8")
        cover = {"src": "cover.svg", "alt": f"Cover illustration for “{title}”", "width": COVER_W, "height": COVER_H, "generator": "svg-fallback"}
        result["note"] = "SVG fallback cover (no image key or --provider svg)"
    else:
        prompt = house_prompt(pub, title, str(meta.get("dek") or ""))
        try:
            gen = images.generate_image(cfg, prompt, provider=provider, model=args.model)
        except images.ImageError as exc:
            print(json.dumps({"checked": False, "error": str(exc), "hint": "rerun with --provider svg for the offline fallback"}, indent=2))
            return 1
        ext = "jpg" if "jpeg" in gen["mime"] else "png" if "png" in gen["mime"] else "webp"
        out = asset_dir / f"cover.{ext}"
        out.write_bytes(gen["bytes"])
        dims = publication.image_dimensions(out) or (None, None)
        cover = {"src": out.name, "alt": f"Cover illustration for “{title}”", "width": dims[0], "height": dims[1],
                 "generator": f"{gen['provider']}/{gen['model']}"}
        result["prompt"] = prompt
    meta["cover"] = cover
    meta["cover_generated_at"] = pubstate.now_iso()
    publication.write_post(path, meta, body)
    result["cover"] = cover
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
