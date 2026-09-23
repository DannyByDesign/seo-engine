---
name: pub-visuals
description: Produces a publication article's imagery in the measured house style — deterministic SVG (and PNG when a converter exists) diagrams from the JSON specs pub-enhance writes (stat callout, stepped flow, funnel, comparison, timeline; kicker title, one big idea, Source footer, theme colours), and a 16:9 cover per headline via OpenAI or Gemini image models with a theme-derived SVG fallback that needs no key. Invoke after pub-enhance, before publishing. Not for writing the diagram briefs (pub-research does) or placing them (pub-enhance does).
---

# pub-visuals

The vendor's "Canvas": covers and diagrams that are "mathematically consistent with the brand
guidelines". Here that means every diagram is drawn from a spec with the publication's theme
tokens, and every cover is minted from one house prompt per publication — so a site's imagery
reads as one hand across a hundred posts (`publication-playbook.md` §3).

## When to use this skill

- After `pub-enhance` has written `assets/<slug>/diagram-N.json` specs — render them.
- Before publishing any article: mint its cover (`gen_cover.py`); rerun with `--force` after a
  title change.
- Re-theming a publication: re-render every article's diagrams and covers.
- **Not** for deciding what a diagram shows (`pub-research` proposes, `pub-enhance` places).

## What it checks / does

### 1. `scripts/render_diagram.py`

Reads specs (`--slug` renders all of an article's, `--spec` explicit paths) and writes
`diagram-N.svg` at 2910×1350: small-caps kicker title top-left, a type-specific body, and a
`Source:` footer, coloured from the theme. Types: `stat_callout` (two big numbers with a rising
area between them, or one number), `stepped_flow` (numbered boxes with arrows), `funnel`
(narrowing bars), `comparison` (horizontal bars, max highlighted), `timeline`. `--png` also
writes a PNG when `cairosvg` (pip) or `rsvg-convert` (librsvg) is available and says which.

### 2. `scripts/gen_cover.py`

Builds the house prompt (site.yml `cover_style`, else theme palette) around the headline and
dek, generates a 16:9 image with the configured provider (`IMAGE_PROVIDER`, else OpenAI, else
Gemini; models overridable via `IMAGE_MODEL_OPENAI` / `IMAGE_MODEL_GEMINI`), writes
`assets/<slug>/cover.<ext>`, and records `cover: {src, alt, width, height, generator}` in the
frontmatter with the measured alt convention. With no key or `--provider svg`, draws a seeded
abstract SVG cover from the theme so nothing blocks.

## Running it

> Run from the target repo root. `${CLAUDE_SKILL_DIR}` is this skill's directory.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/render_diagram.py" --publication llm-billboard --slug advertiser-readiness --png
python3 "${CLAUDE_SKILL_DIR}/scripts/gen_cover.py" --publication llm-billboard --slug advertiser-readiness
python3 "${CLAUDE_SKILL_DIR}/scripts/gen_cover.py" --publication llm-billboard --slug advertiser-readiness --provider gemini --force
python3 "${CLAUDE_SKILL_DIR}/scripts/gen_cover.py" --publication llm-billboard --slug advertiser-readiness --provider svg
```

Flags: `render_diagram.py` `--publication`, `--slug`, `--spec` (repeatable), `--png`,
`--publications-dir`; `gen_cover.py` `--publication`, `--slug`, `--posts`, `--provider`,
`--model`, `--force`, `--publications-dir`.

## Expected output

`render_diagram.py`: `rendered[] = {spec, svg, type, width, height, png?, png_note?}`.
`gen_cover.py`: `cover = {src, alt, width, height, generator}` plus the `prompt` used (or a
`note` that the SVG fallback was drawn). Exit 1 when a provider was requested but failed
(hint: `--provider svg`).

## State files

| File | Role | Written by | Read by |
|---|---|---|---|
| `publications/<slug>/assets/<article>/diagram-N.svg` (+ `.png`) | rendered diagrams referenced by the markdown | `render_diagram.py` | `pub-site` builder |
| `publications/<slug>/assets/<article>/cover.<ext>` | cover image | `gen_cover.py` | `pub-site` builder (OG image, hero, cards) |
| article frontmatter `cover` | src/alt/dimensions/generator | `gen_cover.py` | `pub-site` builder |

## How to interpret results

- **A diagram whose numbers you cannot find in the article's sources is a defect upstream**:
  `pub-enhance`'s verifier checks prose, not images — check `data` in the spec against the
  paper trail before publishing a stat callout.
- **SVG-only output is fine for the web and for crawlers**; add a PNG converter only if you
  need raster for social cards or a CMS that rejects SVG.
- **Cover `generator: svg-fallback`** means no image model ran; the site still ships, and the
  cover can be regenerated later with `--force` once a key exists.
- The cover prompt forbids text and faces on purpose: text in generated images is unreliable,
  and faces invite a persona problem the measured sites avoid.

## Safe to auto-apply vs. human review

- **Safe without asking:** rendering diagrams, minting covers for drafts, the SVG fallback.
- **Ask first:** regenerating covers across a whole published publication (spends image
  credits and changes live OG images), changing `cover_style` in `site.yml`.

## Guardrails

- Diagrams render only what the spec contains — no numbers are invented in this skill.
- Covers carry no text, logos or faces; alt text always names the article.
- One house prompt per publication; per-article prompt tweaks live in `site.yml`, not in
  ad-hoc flags, so consistency survives many runs.

## References

- [publication-playbook.md](../../shared/seo-references/publication-playbook.md) §2 (images with
  dimensions, self-hosted), §3 (diagram and cover conventions), §8 (the vendor's Canvas).
- [seo-playbook.md](../../shared/seo-references/seo-playbook.md) §3 (image dimensions and lazy loading
  behind the CLS numbers the builder protects).
- [api-reference.md](../../shared/seo-references/api-reference.md) — image providers.

## Graceful degradation

`render_diagram.py` needs nothing. `gen_cover.py` uses OpenAI or Gemini when a key exists and
otherwise falls back to a theme-derived SVG cover, saying so in `note`; a failing provider
exits 1 with the fallback hint rather than writing a broken file.
