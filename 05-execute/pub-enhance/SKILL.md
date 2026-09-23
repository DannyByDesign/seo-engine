---
name: pub-enhance
description: "Edits publication drafts before they ship. Requires a whole-article clarity and brevity pass, then supports internal links, source lists, numeric anchors, diagrams, keyword suggestions, numeric-presence checks, metadata and proofreading. Relink proposes reviewed refresh drafts for older posts. Use after pub-write and before publication review."
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

Start by checking that the host completed the [whole-piece editing pass](../seo-copywriting/SKILL.md#required-whole-piece-editing-pass).
If not, perform it on the complete draft now. Remove repetition and unnecessary explanation
before adding links and visuals to prose that may be cut. After enhancement, read the final
piece once more for duplicated explanations in captions, summaries and body text.

The optional `voice` stage is a local rewrite aid, not this editorial pass. Its preservation
guard can reject a useful large cut or heading change as well as a harmful rewrite. Inspect
the reported reason. For warranted structural edits, edit the draft directly, check retained
claims against their evidence, update affected outline/visual instructions, then rerun the
relevant enhancement and proofreading stages and obtain a fresh editorial review. Do not
disable safeguards, edit live posts, or restore padding merely to satisfy a rewrite ratio.

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
`language` is a default stage: LanguageTool checks the final prose after all editing passes,
saves a report and records its hash/path in draft metadata. It never rewrites the draft.
Read and resolve suggestions through [seo-copywriting](../seo-copywriting/SKILL.md), then
rerun `language` before editorial review. Dry runs make no LanguageTool request. An unavailable
service leaves an explicit `not_checked` result while preserving the draft.
This automatic pass covers the body; separately check visible title, dek and description as
plain text through the same checker before final review.

### 2. `scripts/relink.py`

For the newest (or `--new-slug`) post, scans up to `--max-posts` older posts, inserts at most
`--max-per-post` contextual links in proposed refresh drafts. Original posts and dates stay unchanged until the proposals are reviewed and published.

Relinking writes proposed refresh drafts and preserves live posts. Existing drafts are never overwritten. Review the proposal with `pub-publish` before publishing. Numeric matches require contextual claim review before publication.

## Running it

> Run from the target repo root. `${SKILL_DIR}` is this skill's directory.

```bash
python3 "${SKILL_DIR}/scripts/enhance_article.py" --publication llm-billboard --slug advertiser-readiness
python3 "${SKILL_DIR}/scripts/enhance_article.py" --publication llm-billboard --slug advertiser-readiness \
  --stages verify --check-links --strict-verify
python3 "${SKILL_DIR}/scripts/enhance_article.py" --publication llm-billboard --slug advertiser-readiness --voice --dry-run
python3 "${SKILL_DIR}/scripts/relink.py" --publication llm-billboard --new-slug advertiser-readiness
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
- **A rejected `voice` pass** (guard non-empty) means a preservation check failed, which may
  include length or heading changes; inspect the reason. Nothing was written.

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

- [publication-playbook.md](../../shared/seo-references/publication-playbook.md) §3 (citations,
  Sources block, numeric anchors, retro-linking), §4 (Enhance stages).
- [seo-playbook.md](../../shared/seo-references/seo-playbook.md) §6 (internal linking as a natural
  property of comprehensive coverage).
- [red-flags.md](../../shared/seo-references/red-flags.md) §3 (freshness is earned), §7 (substance
  floor: the verifier is what enforces it).
- [geo-playbook.md](../../shared/seo-references/geo-playbook.md) §5 (cited statistics and quotations).

## Graceful degradation

`links`, `sources`, `anchors`, `diagrams`, `verify`, `meta` and `relink.py` need no API key.
`keywords` and `voice` need `OPENROUTER_API_KEY` and skip with a note otherwise. `--check-links` uses
the network; without it the verifier reads only the research cache.
