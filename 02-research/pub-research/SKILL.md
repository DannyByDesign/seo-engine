---
name: pub-research
description: Researches an article topic against the live web and writes a verified, sourced outline into the draft — plan queries, gather and read sources (client landing pages included only where their context matches), pause for a topic interview and approved contribution, synthesize reader-led sections whose claims carry verbatim quotes tied to numbered sources, and drop every claim whose quote cannot be found in its source. Invoke for each draft before pub-write. Not for choosing topics (pub-curate) or writing prose (pub-write).
---

# pub-research

Writing kernels do not research; they write from the brief they are given. This skill produces
that brief as a **verified** outline: every point carries a quote that was found in the fetched
source text, the numbers the diagrams will show come from those sources, and the client is a
candidate source only through the landing pages whose "when to cite" context matches the topic.

## When to use this skill

- A draft exists in `drafts/` (from `pub-curate`'s planner or a seer) and needs its brief
  turned into an outline — run it once per article, before `pub-write`.
- The owner wants to steer the angle: `--direction-gate` pauses with three options; resume
  with `--choice N` or `--direction "..."`.
- Refreshing an old article: rerun with `--source-url` seeds pointing at newer data.
- **Not** for topic selection (`pub-curate`) or drafting prose (`pub-write`).

## What it checks / does

Before outlining, follow [Topic research and interview](../../shared/seo-references/content-interview.md).
The first run gathers web sources and returns `awaiting_interview`. The host inspects competing
answers and demand, interviews the operator using the contract's native question-tool rule,
then records proposed use and explicit article-scoped permission. Answering is not permission.
Rerun after confirmation; unchanged approved input resumes without another interview.
Use `--refresh-research` for a substantive new topic/source investigation, which invalidates
old contribution scope. Missing operator input pauses unattended runs before drafting.

Plan the cover and useful inline imagery with the outline using the shared
[image workflow](../../shared/seo-references/images.md). Record `visual_plan` in frontmatter,
including factual asset needs and diagram evidence, before handing the article to the writer.


`scripts/research_outline.py` runs the six phases in order:

1. **plan** — LLM: 4-8 search queries, must-cover subsections (merged with `--must-include`),
   likely entities.
2. **gather** — Firecrawl search per query (SociaVault Google search as fallback); seed URLs
   from `--source-url` and the draft's `source_urls`; client landings whose context overlaps
   the topic. Other client URLs are excluded on purpose (mention policy). Social/video hosts
   and binaries are skipped.
3. **read** — fetch, strip chrome, keep up to `--max-sources` with at least ~120 words
   (Firecrawl scrape rescues thin JS pages when configured). Texts are cached under
   `.seo-engine/state/pub-research/<publication>/<slug>/`.
4. **direction** — three thesis/framework options with a recommendation; `--direction-gate`
   stops here (`research.status: awaiting_direction`).
5. **synthesize** — title, dek, optional evidenced opening, reader-led sections of evidenced points,
   closing advice, optional diagram briefs with data, keywords; `--depth barebones` yields
   headings and goals only.
6. **verify** — each quote is matched exactly after normalization against its web or approved interview source; unverifiable points are removed and counted in `verification.dropped`.

The draft's frontmatter gains `research` (plan, sources, direction, outline, paper_trail,
verification) and `sources` (only sources that back a surviving quote), and `title`/`dek`
are refined.

## Running it

The host also uses `scripts/content_brief.py` for either content path. Flags: `--action`
(`prepare`, `confirm`, `status`), `--content-id`, `--file`, `--confirm-digest`, `--operator`,
`--confirmation`. See the linked interview contract for the JSON and command sequence.
Only proposed publishable material belongs in that JSON, never raw/private interview notes.


> Run from the target repo root. `${SKILL_DIR}` is this skill's directory.

```bash
python3 "${SKILL_DIR}/scripts/research_outline.py" --publication llm-billboard --slug advertiser-readiness
python3 "${SKILL_DIR}/scripts/research_outline.py" --publication llm-billboard \
  --topic "Advertiser readiness assessment for the AI search transition" --spoke-id sp-0004 \
  --source-url https://www.emarketer.com/content/ai-search-ads --must-include "measurement readiness"
python3 "${SKILL_DIR}/scripts/research_outline.py" --publication llm-billboard --slug advertiser-readiness --direction-gate
python3 "${SKILL_DIR}/scripts/research_outline.py" --publication llm-billboard --slug advertiser-readiness --choice 1
python3 "${SKILL_DIR}/scripts/research_outline.py" --publication llm-billboard --slug advertiser-readiness --no-search --depth barebones
```

Flags: `--publication`, `--slug`, `--topic`, `--spoke-id`, `--source-url` (repeatable),
`--must-include` (repeatable), `--depth`, `--max-sources`, `--direction-gate`, `--direction`,
`--choice`, `--no-search`, `--publications-dir`.

## Expected output

```jsonc
{ "checked": true, "draft": "publications/llm-billboard/drafts/advertiser-readiness.md",
  "status": "done", "title": "Advertiser Readiness Assessment for the AI Search Transition",
  "sources_read": 11, "claims_verified": 23, "claims_dropped": 3, "sections": 7, "diagrams": 2,
  "direction": { "thesis": "...", "framework": "a four-dimension scorecard", "source": "recommended" },
  "plan": { "queries": ["..."], "must_cover": ["..."] }, "notes": [] }
```
With `--direction-gate`: `status: awaiting_direction`, `direction_options[]`, `recommended`,
and a `next_step`. Exit 1 when no `OPENROUTER_API_KEY` is configured or no source could be read.

## State files

| File | Role | Written by | Read by |
|---|---|---|---|
| `publications/<slug>/drafts/<article>.md` (frontmatter `research`, `sources`, `title`, `dek`) | the verified outline and paper trail | `research_outline.py` | `pub-write`, `pub-enhance`, `pub-visuals` |
| `.seo-engine/state/pub-research/<publication>/<article>/` | cached source texts (verification re-runs offline) | `research_outline.py` | `pub-enhance` verifier |
| `.seo-engine/state/http-cache/` | fetched pages (7 days) | `research_outline.py` | itself |

## How to interpret results

- **`claims_dropped` is the safety net working**, not a failure. A high ratio (more dropped
  than kept) means the sources were thin or off-topic — add `--source-url` seeds or narrow
  the topic rather than writing from what survived.
- **Source counts describe coverage**, not usefulness. Inspect whether the evidence supports
  the reader task and approved contribution; do not add citations to meet a quota.
- **Client landings** govern promotional links. Approved interviews use their own attribution
  and may be cited without a public URL or invented link.
- **The gate is cheap; use it** on the first few articles of a new publication until the
  recommended directions consistently match the owner's taste.

## Safe to auto-apply vs. human review

- **Safe without asking:** source collection and preparation. Outlining waits for the topic
  interview and the operator’s explicit confirmation of proposed use.
- **Ask first:** nothing here publishes; but when `claims_dropped` exceeds `claims_verified`,
  surface it before `pub-write` spends tokens on a weak outline.

## Guardrails

- Never invent a source: every quote is checked against fetched text; unverifiable points
  are removed, not softened.
- Client web sources use configured landings; approved interviews are a separate attributed source. The client site is read through configured landings (red-flags §7: mentions stay honest).
- Bounded network: ≤20 seed URLs, `--max-sources` pages, polite intervals, week-long cache.
- Numbers in diagram briefs must appear in the sources; `pub-enhance`'s verifier re-checks
  them in the finished prose.

## References

- [publication-playbook.md](../../shared/seo-references/publication-playbook.md) §3 (article
  quality: reader need, original contribution and contextual review), §4 (the research phases).
- [geo-playbook.md](../../shared/seo-references/geo-playbook.md) §5 (cited statistics, quotations and
  specificity are the one evidence-backed content lever for AI citation).
- [red-flags.md](../../shared/seo-references/red-flags.md) §7 (substance floor and honest mentions).
- [api-reference.md](../../shared/seo-references/api-reference.md) — Firecrawl search/scrape, SociaVault.

## Graceful degradation

Requires `OPENROUTER_API_KEY`. Without a search provider it reads only `--source-url` seeds and matching
landings (`--no-search` makes that explicit); without Firecrawl, thin JavaScript pages may be
dropped for lack of text. Every skipped capability is named in `notes`.
