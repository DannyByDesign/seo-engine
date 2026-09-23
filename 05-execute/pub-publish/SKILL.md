---
name: pub-publish
description: "Plans publication slots and runs the article pipeline through research, topic interview, writing, enhancement, visuals and editorial review. Pauses for missing contribution permission, enforces current review and publication authorization, and builds approved articles. Use for publication scheduling and publishing."
---

# pub-publish

The autopilot. Slots are scheduled, drafts are created from the queue, the pipeline produces
them, and a gate decides whether they go live. Nothing here writes prose or picks topics; it
sequences the other `pub-*` skills and owns the only irreversible step (`published_at`).

## When to use this skill

- Setting up a publication's rhythm: `planner.py --configure`, then `--materialize --queue`.
- On a schedule (cron, a routine, or `seo-maintain`'s cycle): `run_pipeline.py --next`.
- Publishing a specific reviewed draft: `publish_article.py --slug … --approve --relink --build`.
- **Not** for one-off writing (`pub-write`) or fixes to a live post (`pub-enhance` in posts mode).

## What it checks / does

Pipeline source collection can return `awaiting_interview`, `awaiting_confirmation` or
`awaiting_direction`. Return control to the host immediately; do not proceed to writing or
mark the draft prepared. Follow the [interview contract](../../shared/seo-references/content-interview.md).
Publication approval is separate from permission to use interview material. Final review
covers approved attribution, contribution, disclosure limits, metadata and visuals; permission
changes invalidate the review. Public-source and word-count floors are optional policy flags,
not universal measures of usefulness; defaults are zero and editorial review stays mandatory.


### 1. `scripts/planner.py`

Reads `site.yml → planner` (`cadence_per_week` 6, `sourcing_mode` `curate_first |
topic_map | curate_only`, `approval_mode` `manual | review_window | autopilot`,
`publish_hour_utc` seeded per publication, `jitter_minutes`, `launch_burst`). `--materialize`
creates slots for `--days` ahead on spread weekdays with jittered times and the measured
first-day burst for a brand-new publication. `--queue` fills planned slots — suggestions by
score first, else open spokes from the least-covered active pillar — creating
`drafts/<slug>.md` with title, brief, angle, `spoke_id`, section and `planned_for`, and marking
the spoke/suggestion `queued`. `--due` lists what should run now.

### 2. `scripts/publish_article.py`

Gate: body, `research.status == done`, `enhanced_at`, cover, `--min-words` (default 0),
`--min-sources` (default 0), at most one client link and only when `mention.allowed`. Approval per
`planner.approval_mode`; `--approve` is the human signature. On success: `published_at` set
once (or `--at`), `updated_at` equal, byline assigned to the least-used author if missing,
file moved to `posts/`, spoke `covered`, suggestion and slot `published`. Hooks: `--relink`
(pub-enhance), `--build` (pub-site), `--indexnow` (Bing and friends, when configured).
`--skip-checks` overrides mechanical checks and records the override; it cannot bypass missing or stale editorial review. Local publication is not deployment. Slots stay `building` until validation succeeds.

### 3. `scripts/run_pipeline.py`

Runs `research → write → enhance → diagrams → cover → (shred) → publish → relink → build` as
subprocesses (`--skip` to omit steps; shred is skipped by default), stops at the first failing
step with its output, and — unless `--approve` or autopilot — stops before `publish` with the
draft ready for review. `--next` picks the next due slot; `--dry-run` prints the commands.

## Running it

> Run from the target repo root. `${CLAUDE_SKILL_DIR}` is this skill's directory.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/planner.py" --publication llm-billboard --configure \
  --cadence-per-week 6 --sourcing-mode curate_first --approval-mode manual --publish-hour 20
python3 "${CLAUDE_SKILL_DIR}/scripts/planner.py" --publication llm-billboard --materialize --days 14 --queue
python3 "${CLAUDE_SKILL_DIR}/scripts/planner.py" --publication llm-billboard --due
python3 "${CLAUDE_SKILL_DIR}/scripts/run_pipeline.py" --publication llm-billboard --next
python3 "${CLAUDE_SKILL_DIR}/scripts/run_pipeline.py" --publication llm-billboard --slug advertiser-readiness --approve --indexnow
python3 "${CLAUDE_SKILL_DIR}/scripts/publish_article.py" --publication llm-billboard --slug advertiser-readiness --approve --relink --build
```

Flags: `planner.py` `--publication`, `--configure`, `--enable`, `--disable`,
`--cadence-per-week`, `--sourcing-mode`, `--approval-mode`, `--publish-hour`, `--materialize`,
`--days`, `--queue`, `--due`, `--publications-dir`; `publish_article.py` `--publication`,
`--slug`, `--at`, `--approve`, `--min-words`, `--min-sources`, `--skip-checks`, `--relink`,
`--build`, `--indexnow`, `--publications-dir`; `run_pipeline.py` `--publication`, `--slug`,
`--next`, `--skip`, `--candidates`, `--approve`, `--indexnow`, `--dry-run`, `--publications-dir`.

Before approval, run `review_article.py --publication <publication> --slug <slug>
--review-file review.json` (also accepts `--publications-dir` and `--posts` for migration review of existing published content). Review JSON requires
`reviewer`, `reader_need`, `value_added`, `facts_checked: true`, `disclosure_checked: true`, and `claims[]` with
`claim` (exact final text), `source` (public URL or `interview:ITEM_ID`), `quote` (exact source excerpt), and
`assessment` (explain entity, metric, period and caveats). Record only actual review;
never manufacture an attestation to make the gate pass. All numeric claims need mappings,
and the reviewer checks nonnumeric factual claims too. This is accountable judgment,
not automatic semantic proof. The receipt binds text, metadata, sources, assets and policy.

Before recording that review, read the complete final article and apply the
[whole-piece editing pass](../seo-copywriting/SKILL.md#required-whole-piece-editing-pass).
Do not accept generic introductions, repeated arguments or recap-only endings because the
factual checks passed. Confirm that editing left the approved contribution, useful examples
and necessary caveats intact. Correct weak prose before reviewing the resulting final text;
successful pipeline execution alone is not evidence that this editing work happened.

## Expected output

`planner.py`: `planner` (effective config), `materialized[]`, `queued[] = {slot, scheduled_for,
headline, draft}`, `status` counts, `upcoming[]`, `due[]`.

`publish_article.py`: on refusal `{published: false, gate[], approval}` and exit 1; on success
`{published: true, url, published_at, author, hooks[], next_steps[]}`.

`run_pipeline.py`: `steps[] = {step, exit, summary}` and either `awaiting_approval` or
`stopped_at`.

## State files

| File | Role | Written by | Read by |
|---|---|---|---|
| `publications/<slug>/site.yml → planner` | cadence, sourcing, approval, hour, jitter, burst | `planner.py --configure` | `planner.py`, `publish_article.py`, `run_pipeline.py` |
| `.seo-engine/state/pub-planner-<slug>.json` | slots and their status | `planner.py`, `publish_article.py` | `run_pipeline.py --next` |
| `.seo-engine/state/pub-suggestions-<slug>.json` | queue (`queued` / `published` marks) | `planner.py`, `publish_article.py` | `pub-curate` |
| `publications/<slug>/topic-map.yml` | spoke `queued` / `covered` | `planner.py`, `publish_article.py` | `pub-curate` |
| `publications/<slug>/drafts/*.md` → `posts/*.md` | the article's lifecycle | `planner.py`, `publish_article.py` | every `pub-*` skill |

## How to interpret results

- **An empty `queued[]` with planned slots** means the queue and the map are exhausted —
  run `pub-curate` (rescore suggestions, refresh the topic map); never lower the
  gate to fill a slot.
- **A gate refusal is the system working.** Each item names the skill that clears it.
- **`awaiting_approval`** is the designed stop for `manual` mode; read the draft, then rerun
  with `--approve` after recording the review. All modes require a valid content-bound review.
- **The launch burst** exists because the measured sites opened with 4-5 posts on day one so
  sections were never empty; after that, one a day.

## Safe to auto-apply vs. human review

- **Safe without asking:** configuring the planner, materializing and queueing slots, running
  the pipeline through `cover`, `--dry-run`.
- **Ask first:** `--approve` on a manual/review-window publication is *the* human decision;
  `--skip-checks`; switching `approval_mode` to `autopilot`; `--indexnow` on a site not yet
  verified in Search Console.

## Guardrails

- A refresh retains its original URL and author. `published_at` is set once and never rewritten; `updated_at` only moves with content.
- The gate cannot be lowered from the command line below its documented floors without
  `--skip-checks`, which is recorded in the post.
- Cadence is a schedule, not a target (red-flags §1, §3): an unfillable slot stays empty.
- One client link maximum, only when the writer's mention decision allowed it (playbook §6).

## References

- [publication-playbook.md](../../shared/seo-references/publication-playbook.md) §3 (cadence and
  launch burst as measured), §4 (planner and pipeline contracts), §6 (mention policy).
- [red-flags.md](../../shared/seo-references/red-flags.md) §1, §3, §7 (volume is not a target;
  substance floor; honest mentions).
- [geo-playbook.md](../../shared/seo-references/geo-playbook.md) §10 (IndexNow reaches Bing, which
  feeds ChatGPT).
- [common-setup.md](../../shared/seo-references/common-setup.md) — publications layout and state.

## Graceful degradation

`planner.py` and `publish_article.py` need no API key. `run_pipeline.py` inherits each step's
requirements (research and write need an LLM key; cover falls back to SVG; IndexNow is skipped
with a note when unset). A failing step stops the run with its own JSON so nothing half-built
is published.
