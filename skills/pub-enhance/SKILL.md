---
name: pub-enhance
description: The editing passes before a publication article ships: contextual internal links from the publication's own catalogue, the Sources list from the paper trail and links actually used, numeric anchors to sources, diagram specs and placement, semantic-keyword gaps (report only), a number verifier that checks every figure against cached source text, metadata hygiene, an opt-in voice pass with a nothing-lost guard, and relink, which links older posts to a new one and bumps dateModified only on real change.
---

# pub-enhance

"AI is a bad writer but a great editor" is the vendor's founding observation; this skill is
the editor. It never adds facts: it links, cites, anchors, verifies and tidies what
`pub-write` produced, and it keeps the back catalogue's links current as the publication
grows (`publication-playbook.md` §3, §4).

## When to use this skill

- After `write_article.py` writes a draft: `enhance_article.py` (default stages).
- Right after `pub-publish` publishes a post: `relink.py` so older posts point at it, then
  rebuild with `pub-site`.
- Before publishing anything with numbers you did not watch being sourced:
  `--stages verify --check-links --strict-verify`.
- **Not** for writing prose (`pub-write`) or creating diagrams' images (`pub-visuals`
  renders the specs this skill writes).

## What it checks / does

### 1. `scripts/enhance_article.py` — stages

`links` ranks published posts by term overlap with each paragraph and inserts a link whose
anchor is a phrase of the target's title already present in the paragraph (one per paragraph,
`--max-internal-links` per article). `sources` sets frontmatter `sources` to every external
URL linked in the body plus paper-trail sources that back a surviving quote, in body order —
the site builder renders it as the followed Sources list and `citation[]`. `anchors` links any
still-unlinked verified number to its source. `diagrams` writes `assets/<slug>/diagram-N.json`
from the outline's diagram briefs and places `![Diagram: … Visualizes: …](diagram-N.svg)` after
the most relevant section. `keywords` reports 3-6 semantically related phrases the text lacks
(never inserts). `verify` extracts every number in the prose and checks it against cached
source texts (and, with `--check-links`, fetched linked pages); `--strict-verify` fails the run
on any unverified number. `meta` bounds the dek, sets tags/kicker/reading time and
`seo.description`. `voice` (opt-in, `--voice`) asks the model to fix voice-card violations and
accepts the result only if numbers, links, headings and length are unchanged.

### 2. `scripts/relink.py`

For the newest (or `--new-slug`) post, scans up to `--max-posts` older posts, inserts at most
`--max-per-post` contextual links, bumps `updated_at` only where the body changed. Nothing is
rebuilt here — run `pub-site`'s `build_site.py` next.

## Running it

> Run from the target repo root. `${CLAUDE_SKILL_DIR}` is this skill's directory.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/enhance_article.py" --publication llm-billboard --slug advertiser-readiness
python3 "${CLAUDE_SKILL_DIR}/scripts/enhance_article.py" --publication llm-billboard --slug advertiser-readiness \
  --stages verify --check-links --strict-verify
python3 "${CLAUDE_SKILL_DIR}/scripts/enhance_article.py" --publication llm-billboard --slug advertiser-readiness --voice --dry-run
python3 "${CLAUDE_SKILL_DIR}/scripts/relink.py" --publication llm-billboard --new-slug advertiser-readiness
```

Flags: `enhance_article.py` `--publication`, `--slug`, `--posts`, `--stages`,
`--max-internal-links`, `--check-links`, `--strict-verify`, `--voice`, `--dry-run`,
`--publications-dir`; `relink.py` `--publication`, `--new-slug`, `--max-per-post`,
`--max-posts`, `--dry-run`, `--publications-dir`.

## Expected output

```jsonc
{ "checked": true, "file": "publications/llm-billboard/drafts/advertiser-readiness.md",
  "links": { "inserted": [ { "target": "keyword-to-prompt-translation", "anchor": "intent-topic frameworks", "overlap": 0.31 } ] },
  "anchors": { "added": 2 }, "diagrams": { "specs_written": ["…/assets/advertiser-readiness/diagram-1.json"] },
  "sources": { "count": 11 }, "keywords": { "missing_phrases": ["conversion tracking", "view-through window"] },
  "verify": { "numbers_in_prose": 24, "verified": 23, "unverified": ["19.7%"], "sources_available": 11 },
  "meta": { "notes": [] }, "guard": [], "changed": true, "written": true }
```
`relink.py`: `changes[] = {post, inserted[{anchor, overlap}], updated_at_bumped}` and a
`next_step` to rebuild.

## State files

| File | Role | Written by | Read by |
|---|---|---|---|
| `publications/<slug>/drafts/<article>.md` or `posts/<article>.md` | body + `sources`, `seo`, `tags`, `enhanced_at`, `updated_at` | `enhance_article.py`, `relink.py` | `pub-site` builder, `pub-publish` |
| `publications/<slug>/assets/<article>/diagram-N.json` | diagram specs | `enhance_article.py` | `pub-visuals` |
| `.seo-engine/state/pub-research/<publication>/<article>/` | cached source texts the verifier reads | `pub-research` | `enhance_article.py` |
| `.seo-engine/state/http-cache/` | pages fetched by `--check-links` | `enhance_article.py` | itself |

## How to interpret results

- **An `unverified` number is a stop sign**, not a style note: either the kernel drifted from
  its evidence or the source text was not cached. Fix the prose or re-run research; never
  publish an unverified figure.
- **Zero internal links on a young publication is normal** — the catalogue is small; `relink`
  fills the graph in both directions as posts accumulate.
- **`keywords.missing_phrases` are suggestions for a human edit**; stuffing them in is the
  failure mode this stage avoids by not inserting.
- **A rejected `voice` pass** (guard non-empty) means the model changed a fact or a link;
  nothing was written.

## Safe to auto-apply vs. human review

- **Safe without asking:** links, sources, anchors, diagrams, meta, verify, relink on drafts
  and posts (all deterministic, all reversible in git).
- **Ask first:** `--voice` on a published post, and publishing while `verify.unverified` is
  non-empty.

## Guardrails

- This skill adds no facts and no numbers; it links, cites, verifies.
- One internal link per paragraph, capped per article; anchors are phrases that already exist
  in the text (seo-playbook §6 — links a comprehensive resource would naturally have).
- `dateModified` moves only with a real content change (red-flags §3).
- Internal links only to published posts of the same publication — never to siblings.

## References

- [publication-playbook.md](../seo-references/publication-playbook.md) §3 (citations,
  Sources block, numeric anchors, retro-linking), §4 (Enhance stages).
- [seo-playbook.md](../seo-references/seo-playbook.md) §6 (internal linking as a natural
  property of comprehensive coverage).
- [red-flags.md](../seo-references/red-flags.md) §3 (freshness is earned), §7 (substance
  floor: the verifier is what enforces it).
- [geo-playbook.md](../seo-references/geo-playbook.md) §5 (cited statistics and quotations).

## Graceful degradation

`links`, `sources`, `anchors`, `diagrams`, `verify`, `meta` and `relink.py` need no API key.
`keywords` and `voice` need an LLM key and skip with a note otherwise. `--check-links` uses
the network; without it the verifier reads only the research cache.
