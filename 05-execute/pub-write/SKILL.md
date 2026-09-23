---
name: pub-write
description: "Writes publication articles from verified research and an operator-approved contribution. Uses local human-writing examples, a voice card and a reader-led template; preserves evidence, attribution and disclosure boundaries. Includes optional sentence-level rewriting. Use after pub-research and before pub-enhance; never publishes."
---

# pub-write

The writing kernel. It never researches (that is `pub-research`) and never publishes (that is
`pub-publish`); it turns a verified outline and approved contribution into reader-led prose using human examples,
a voice card and a chosen template, with
the mention policy applied exactly once per article (§6).

## When to use this skill

- A draft has completed research and current approved `content_brief` evidence — run `write_article.py`.
  Direct invocation also refuses missing or changed permission; see the [interview contract](../../shared/seo-references/content-interview.md).
- The owner wants another voice or a stronger draft: `--kernel juniper`, `--candidates 3`, `--force`.
- A masthead with many bylines reads too uniform — run `shred.py` on drafts (or posts) to
  spread sentence-level rewriting across providers.
- **Not** for outlines (`pub-research`), links/sources/verification (`pub-enhance`), or
  scheduling (`pub-publish`).

## What it checks / does

Read the [image workflow](../../shared/seo-references/images.md). Carry `visual_plan` from the
outline into the draft and preserve sourced image placements. After drafting, use `pub-visuals`
to obtain the planned assets and review them in context; don't invent product screenshots.

Read [seo-copywriting](../seo-copywriting/SKILL.md) before drafting. The writer automatically
loads six frozen human passages across source texts and genres into its composition context and
records `writing_example_ids`. Use their techniques while grounding every claim in the outline;
the reference passages are never factual evidence for this article.

Treat the script's section-by-section output as a first draft. Before handing it to
`pub-enhance`, perform the [required whole-piece editing pass](../seo-copywriting/SKILL.md#required-whole-piece-editing-pass).
Read all sections together; remove repeated explanations, generic framing and recap endings,
merge overlapping sections, and rewrite weak prose. Preserve the approved contribution and
its evidence and limits. A candidate judge or sentence-level Shredder cannot establish that
the complete article is concise. Do this edit even when every script reports success.

The writer runs LanguageTool on the composed draft and records `languagetool` with its report
path and text hash. Read the suggestions, fix actual errors while preserving facts and voice,
and rerun on revised prose. `pub-enhance` checks the final text again after editing. Missing
configuration or API failure is explicitly `not_checked`, never a clean grammar result.
The automatic pass covers the body. Check visible title/dek text separately using
`seo-copywriting`'s checker in plain-text mode before final review.

### 1. `scripts/write_article.py`

Loads `kernels/<name>.md` (from `--kernel`, else `strategy.brand_voice.kernel`, default
`editorial`) and `templates/<key>.yml` (default `reader-led`: an opening, evidenced sections and practical ending sized to the task;
`long-read` remains an explicit format option). For the opening and each section it sends the
voice card, house rules, article context and **only the verified evidence points** (claim +
verbatim quote + source), asks for `--candidates` versions in one call, and a cheap judge picks
the winner (skipped when `--candidates 1`). Then it anchors every number from a verified point
to its source URL in the prose and applies the mention decision: the client may be cited only
when `mention.degree` is not `off`, the publication's running mention share stays under
`mention.rate`, and a client landing survived research as a verified source — otherwise the
kernel is told not to name the client and any client link is stripped and logged. Writes the
body into the draft and records `kernel`, `word_count`, `mention` and the judge log.

### 2. `scripts/shred.py`

Splits the body into blocks; only prose sentences are candidates (headings, lists, code,
images, quotes, links untouched). Attempts `--coverage` of sentences (seeded), each with a
provider other than the writer's, keeps a rewrite only if numbers, links, proper nouns and
length survive, enforces `--max-share` per provider and `--max-run` consecutive rewrites, and
rejects the whole pass if the article-level guard (numbers, links, headings, length) fails.
Telemetry per sentence is logged. This is a voice-diversity tool, not a detector-evasion
tool (red-flags §3).

## Running it

> Run from the target repo root. `${SKILL_DIR}` is this skill's directory.

```bash
python3 "${SKILL_DIR}/scripts/write_article.py" --publication llm-billboard --slug advertiser-readiness
python3 "${SKILL_DIR}/scripts/write_article.py" --publication llm-billboard --slug advertiser-readiness \
  --kernel sequoia --candidates 3 --force
python3 "${SKILL_DIR}/scripts/shred.py" --publication llm-billboard --slug advertiser-readiness --dry-run
python3 "${SKILL_DIR}/scripts/shred.py" --publication llm-billboard --slug advertiser-readiness --coverage 0.4
```

Flags: `write_article.py` `--publication`, `--slug`, `--kernel`, `--template`, `--candidates`,
`--force`, `--publications-dir`; `shred.py` `--publication`, `--slug`, `--posts`, `--coverage`,
`--attempts`, `--max-share`, `--max-run`, `--seed`, `--dry-run`, `--publications-dir`.

## Expected output

`write_article.py`:
```jsonc
{ "checked": true, "draft": "publications/llm-billboard/drafts/advertiser-readiness.md",
  "kernel": "editorial", "words": 2431, "sections": 7, "numeric_anchors": 19,
  "mention": { "allowed": true, "degree": "subtle", "applied": true, "landing_url": "https://www.thrad.ai/content/…", "reasons": [], "stripped": 0 },
  "judge": [ { "heading": "…", "candidates": 2, "winner": 1, "notes": "…" } ], "notes": [] }
```
`shred.py`: `status` (`shredded | kept_original | rejected`), `summary.shredded`,
`summary.share_report.{by_provider, over_ceiling, longest_run, window_risk}`, `guard[]`.

## State files

| File | Role | Written by | Read by |
|---|---|---|---|
| `publications/<slug>/drafts/<article>.md` | body + frontmatter (`kernel`, `word_count`, `mention`, `composition`, `shred`) | `write_article.py`, `shred.py` | `pub-enhance`, `pub-publish` |
| `kernels/*.md`, `templates/*.yml` (in this skill) | voice cards and shape templates | maintainers | `write_article.py` |
| `.seo-engine/state/pub-shred-<slug>.json` | shredder telemetry per run | `shred.py` | audits |

## How to interpret results

- **`mention.reasons` explains a non-mention** — most articles legitimately carry none
  (the measured rate was 1 in 31); an article with `allowed: false` is not a failure.
- **`numeric_anchors` counts supported numbers**, not quality. Use the amount of quantitative
  evidence the reader's task warrants; never manufacture statistics to meet a quota.
- **Judge notes** name why a candidate lost; recurring notes ("hedging", "invented figure")
  are a signal to switch kernels or lower `--candidates`.
- **Shredder `rejected`** means a rewrite would have lost facts; nothing was written — safe.

## Safe to auto-apply vs. human review

- **Safe without asking:** writing into `drafts/`, `--force` on a draft, shredding a draft.
- **Ask first:** shredding a published post (`--posts`; it changes live prose), switching a
  publication's default kernel in `strategy.yml`.

## Guardrails

- The kernel receives only verified evidence and is told it may not extend it; numbers are
  written as sourced and anchored to the source.
- Promotional client links remain subject to the mention policy. Interview attribution uses
  the operator-approved wording, without inventing links or implying independent endorsement.
- First person requires an approved speaker. Structure, length and headings follow the reader
  task; evidence and disclosure constraints override generic voice-card preferences.
- The Shredder keeps every number, link, proper noun and heading or keeps the original.

## References

- [publication-playbook.md](../../shared/seo-references/publication-playbook.md) §3 (article
  anatomy), §5 (bylines), §6 (mention policy), §8 (writing kernels and the shredder).
- [red-flags.md](../../shared/seo-references/red-flags.md) §3 (no AI-content penalty; the shredder's
  purpose), §7 (honest mentions).
- [geo-playbook.md](../../shared/seo-references/geo-playbook.md) §5 (why sourced statistics and
  named sources are the content lever).

## Graceful degradation

Both scripts require an LLM key; with one provider the Shredder alternates that provider's
quality and cheap models instead of rotating vendors and says so in the share report. If
the judge call fails, the first candidate is kept and noted. Missing kernels or templates fail
loudly with the list of available ones.
