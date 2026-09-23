# SEO Engine — Architecture

> This document is part of the deliverable: agents working in a target repo
> read it to understand how the system fits together. The agent-operational
> contracts (paths, config, snapshot store) live in
> [shared/seo-references/common-setup.md](shared/seo-references/common-setup.md);
> this file is the human-facing overview.

## What this is

A portable folder of agent skills that turns any AI coding agent working in a
website repo into a continuous SEO + GEO (Generative Engine Optimization)
maintenance system. Copy (or install) this folder into a repo that contains a
website; the agent gains skills to audit, fix, improve, and monitor organic
search and AI-search visibility — using only long-term, sustainable,
policy-compliant strategies.

It also runs the operator's own **publications** (the `pub-*` skills): a
Next.js-free static site per publication, accurate contributor or organization attribution, a topic map, an evidence
pipeline (research → write → enhance → visuals → publish), a planner, and
monitoring — the model documented in
[publication-playbook.md](shared/seo-references/publication-playbook.md).

## Design principles

1. **Sustainable only.** Every skill encodes Google spam-policy and AI-content
   guardrails. No cloaking, no scaled thin content, no link schemes, no
   freshness-faking. A shared `red-flags.md` is the veto layer every
   content-touching skill must consult. The `pub-*` skills publish on a
   cadence by design; their guardrail is a substance floor and a verified
   paper trail per article (red-flags §1, §7), never a volume cap.
2. **Framework-agnostic.** Skills detect the stack (Next.js, Astro, Nuxt,
   SvelteKit, Hugo, plain HTML, ...) — including which directory deploys
   verbatim vs. which is wiped by builds — and adapt: fix at the source-code
   level when the repo builds the site, at the crawl/report level when it
   doesn't.
3. **Deterministic scripts + agent judgment.** Scripts (Python 3.9+, minimal
   deps) do crawling, API calls, diffing, validation — anything that must be
   exact. The agent does judgment: what to write, which fix to apply, when to
   escalate. Corollary: a finding must be trustworthy — detectors refuse to
   guess (explicit `not_checked` refusals) rather than emit plausible noise,
   because an agent will *act* on a `severity: critical`.
4. **Stateful continuity.** Skills persist config and baselines in the target
   repo under `.seo-engine/` — crawls go into one shared, provenance-tagged
   snapshot store (`state/crawls/` + `.meta.json` sidecars) so successive
   sessions and different skills build on each other's work safely, and diffs
   only ever run against *comparable* baselines (same site, same crawl bounds,
   untruncated).
5. **Degrade gracefully.** Every integration is optional. Missing API key →
   the skill says exactly which env var to set and falls back to what it can do
   without it. Google Search Console is the free backbone (property identifiers
   are auto-resolved — `sc-domain:` and URL-prefix forms — and cached); paid
   APIs (Ahrefs, DataForSEO, Firecrawl, LLM APIs) extend it.
6. **No secret can leak.** All HTTP flows through `scripts/lib/http_util.py`,
   which sanitizes credentials out of every surfaced URL and error message —
   reports may contain draft prose or private analytics and stay gitignored. Retries are idempotency-aware
   (a pay-per-call POST is never blindly re-sent after an ambiguous failure).

## Layout

The implementation lives in six physical phase directories, from `01-understand/` through
`06-learn/`. Each owns its skills, scripts and phase README. Cross-phase reference material
lives in `shared/seo-references/`; shared Python mechanics remain in `scripts/lib/`.
`skills/*` and the old workflow filenames are compatibility symlinks. Installers and internal
skill dispatch use the canonical phase locations, not those aliases.

`scripts/lib/strategy.py` validates and versions agent-authored business/research/positioning
records with parent and evidence hashes. `scripts/lib/research.py` collects real vendor API
responses under durable call allowances. `run_cycle.py` routes the host agent using current
strategy status and actual intervention learning. The host agent supplies reasoning and source
edits, using the scripts to check handoffs; no human-authored seed list or brief is required.

```text
seo-engine/
├── 01-understand/       # setup, audit, scripts/run_strategy.py
├── 02-research/         # keywords, source research, scripts/research_market.py
├── 03-position/         # positioning
├── 04-choose/           # growth coordinator and topic selection
├── 05-execute/          # copy, website code, visuals and publishing
│   └── seo-copywriting/
│       ├── SKILL.md     # actual inline human writing and editing workflow
│       ├── corpus/     # local Markdown source writing and passages
│       └── scripts/    # local sampling and LanguageTool checker
├── 06-learn/            # monitoring, analytics, cycle runner and instructions
├── shared/seo-references/
├── scripts/lib/         # common clients, state, rendering and contracts
├── scripts/dev/         # documentation checks and opt-in API smoke checks
├── tests/               # regression and integration tests
├── workflow/            # workflow index/contract and old-guide aliases
├── skills/              # compatibility symlinks only
├── research/            # research, evaluations and preserved evidence
├── install.sh           # installs phase-owned skills into host discovery paths
└── .env.example         # integration configuration
```

## State kept in the target repo

```
.seo-engine/
├── config.yml        # site facts incl. static_source_dir/build_output_dir/gsc_property
├── state/
│   ├── crawls/       # crawl-<stamp>.jsonl + .meta.json provenance sidecars
│   ├── http-cache/   # transient response cache
│   └── <skill>-*.json# per-skill histories (each written & read by that skill only)
└── reports/          # dated reports, auto-pruned

publications/         # one folder per owned publication (committed)
└── <slug>/
    ├── site.yml      # name, url, theme, sections, authors, disclosure, planner
    ├── strategy.yml  # client, direction, topics, stances, targets, landings, mention policy
    ├── topic-map.yml # pillars → spokes with status open|queued|covered|dismissed
    ├── seers.yml     # trigger sources (news, regulation, social, GitHub, specs, Notion)
    ├── competitors/  # scraped competitor catalogues
    ├── drafts/ posts/ assets/<slug>/   # article lifecycle + diagrams/covers
    └── dist/         # built static site (deploy to Vercel)
```

## The continuous loop (`seo-maintain`)

1. Crawl fresh into the snapshot store; load the most recent *comparable*
   baseline (or record an explicit refusal in `not_checked`).
2. Detect regressions first (indexing drops, accidental noindex, broken links,
   canonical changes, new redirects on previously-direct pages — the "don't
   lose what you have" pass).
3. Rank improvement opportunities by impact/effort from the fresh crawl.
4. Emit one prioritized punch-list naming the skill that owns each item. This
   skill never applies fixes — fixes happen only inside the dispatched skill,
   under that skill's own auto-apply/human-review gates.
5. Write a dated report; the snapshot store gives the next run its baseline.

## The publication loop (`pub-*`)

1. `pub-site` scaffolds a publication (name never contains the client's name,
   publisher-supplied accurate contributor or organization attribution, theme) and `pub-strategy` records positioning.
2. `pub-curate` builds the topic map from positioning and competitor
   catalogues, scores suggestions (competitor coverage, GEO gaps from
   `geo-monitor`, search volume, cluster fit, authority, social conversations),
   and polls seers for time-sensitive triggers.
3. `pub-publish`'s planner materializes de-robotized slots and fills them from
   the queue; `run_pipeline.py` runs `pub-research` (every point cites a fetched
   source) → `pub-write` (kernel voice, candidate judging, mention decision) →
   `pub-enhance` (links, sources, anchors, verifier) → `pub-visuals` → the
   gate → publish → relink → build.
4. `pub-monitor` rolls up Search Console per publication and flags refresh
   candidates; `geo-monitor`'s brand-mention tracker measures whether
   assistants now name the client, and feeds gaps back to step 2.

## Environment variables (operational)

- `SEO_REPO_ROOT` — pins the target repo (recommended for cron/CI; otherwise
  discovered by walking up from cwd).
- `SEO_ENGINE_ROOT` — pins the engine location when skills were copied rather
  than symlinked (scripts otherwise self-locate through their own path).
- `SEO_SITE_URL` — fallback for `site_url` when `.seo-engine/config.yml`
  doesn't exist yet.
- `LLM_PROVIDER`, `LLM_MODEL_<PROVIDER>`, `LLM_CHEAP_MODEL_<PROVIDER>`,
  `LLM_EFFORT` — which configured text provider the `pub-*` skills prefer and
  which model ids they use (defaults in `scripts/lib/llm.py`).
- `IMAGE_PROVIDER`, `IMAGE_MODEL_OPENAI`, `IMAGE_MODEL_GEMINI` — cover
  generation provider and model ids (defaults in `scripts/lib/images.py`).

## First-party growth experiments

`seo-growth` composes the existing diagnosis/editing skills with an executable intervention
ledger in `.seo-engine/state/growth/`. Demand alternatives or diagnostic evidence precede
source edits. Repo-owned commands validate and deploy; change assertions compare a captured
baseline with production. Durable deployment intent, reconciliation and linked follow-ups
support interruption recovery. Outcome comparisons use actual analytics exports, conservative
rollout intervals and explicit decisions/costs. Inconclusive experiments remain observing.

`run_cycle.py` gives a configured agent a durable work packet. The external host scheduler
must be activated explicitly. GA4 and other normalized exports are distinct from API visibility
probes. The capability ledger records tested interfaces and missing effectiveness evidence.
