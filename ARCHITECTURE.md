# SEO Engine — Architecture

> This document is part of the deliverable: agents working in a target repo
> read it to understand how the system fits together. The agent-operational
> contracts (paths, config, snapshot store) live in
> [skills/seo-references/common-setup.md](skills/seo-references/common-setup.md);
> this file is the human-facing overview.

## What this is

A portable folder of agent skills that turns any AI coding agent working in a
website repo into a continuous SEO + GEO (Generative Engine Optimization)
maintenance system. Copy (or install) this folder into a repo that contains a
website; the agent gains skills to audit, fix, improve, and monitor organic
search and AI-search visibility — using only long-term, sustainable,
policy-compliant strategies.

It also runs the operator's own **publications** (the `pub-*` skills): a
Next.js-free static site per publication, personas, a topic map, an evidence
pipeline (research → write → enhance → visuals → publish), a planner, and
monitoring — the model documented in
[publication-playbook.md](skills/seo-references/publication-playbook.md).

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
   reports are safe to commit by construction. Retries are idempotency-aware
   (a pay-per-call POST is never blindly re-sent after an ambiguous failure).

## Layout

```
seo-engine/
├── README.md                  # install + quickstart + testing
├── ARCHITECTURE.md            # this file
├── install.sh                 # symlinks skills/* into <target-repo>/.claude/skills/,
│                              #   writes stub .env, ensures target .gitignore
├── .claude-plugin/
│   └── plugin.json            # Claude Code plugin manifest (alt. install path)
├── .env.example               # every supported key, documented (all optional)
├── requirements.txt           # runtime Python deps (kept minimal)
├── requirements-dev.txt       # pytest
├── skills/
│   ├── seo-references/        # ← the knowledge base, installed like any skill
│   │   ├── SKILL.md           #   index + evidence-grade legend
│   │   ├── seo-playbook.md    #   sustainable classic-SEO strategy
│   │   ├── geo-playbook.md    #   AI-search evidence (incl. §10 Bing→ChatGPT,
│   │   │                      #   §11 AI crawlers don't render JS)
│   │   ├── publication-playbook.md # the measured publication model (pub-* skills)
│   │   ├── red-flags.md       #   spam policies, penalties — the veto layer (§7: publications)
│   │   ├── api-reference.md   #   endpoints, auth, quotas per integration
│   │   └── common-setup.md    #   paths/config/snapshot contracts (agent-operational)
│   ├── seo-setup/             # onboarding: detect stack, write config, key status
│   ├── seo-maintain/          # orchestrator: regression-first maintenance loop
│   ├── seo-technical-audit/   # crawl audit: status, canonicals, noindex, sitemaps
│   ├── seo-metadata/          # titles, descriptions, OG/Twitter cards
│   ├── seo-structured-data/   # JSON-LD generation + tiered validation
│   │   └── references/        #   jsonld-library.md (examples + insertion guide)
│   ├── seo-performance/       # Core Web Vitals via PSI/CrUX → code-level fixes
│   ├── seo-indexing/          # GSC coverage, sitemap discovery/submit, IndexNow
│   ├── seo-keyword-research/  # GSC + Ahrefs/DataForSEO opportunity mining
│   ├── seo-content-optimize/  # staleness signals with anti-spam guardrails
│   ├── seo-internal-linking/  # link graph, sitemap/GSC-grounded orphans
│   ├── seo-backlinks/         # profile monitoring only — never acquisition
│   ├── seo-redirects/         # config-level redirect audit, migration safety
│   ├── seo-rank-tracking/     # GSC positions, stdev-gated drop alerts
│   ├── geo-optimize/          # AI-crawler access, cloaking check, JS-visibility
│   │                          #   check, narrowly-scoped llms.txt
│   ├── geo-monitor/           # AI-citation probing (multi-sample), brand-mention
│   │                          #   tracking (Wilson intervals), log/GA4 signals
│   ├── pub-site/              # publication scaffold, static build, anatomy validator
│   ├── pub-strategy/          # positioning + competitor catalogue scraping
│   ├── pub-curate/            # topic map, scored suggestions, seers
│   ├── pub-research/          # plan → search → read → synthesize → verify outline
│   ├── pub-write/             # kernels/, templates/, write_article.py, shred.py
│   ├── pub-enhance/           # links, sources, anchors, diagrams, verify, meta, relink
│   ├── pub-visuals/           # SVG diagrams, covers (OpenAI / Gemini / SVG fallback)
│   ├── pub-publish/           # planner, gate + approval, run_pipeline
│   └── pub-monitor/           # per-publication GSC rollups, refresh triggers, GEO sync
├── research/                  # the vendor teardown the pub-* skills were built from
├── scripts/
│   ├── lib/                   # shared library (imported by every skill script)
│   │   ├── config.py          # env + .seo-engine/config resolution; INTEGRATION_ENV_VARS
│   │   ├── http_util.py       # sanitizing, idempotency-aware HTTP (the ONLY egress)
│   │   ├── urlnorm.py         # canonical URL identity (the one folding used everywhere)
│   │   ├── pagerules.py       # shared noindex/indexability predicates
│   │   ├── robots.py          # RFC 9309 parse/evaluate/fetch (crawler + geo audit)
│   │   ├── sitemaps.py        # sitemap discovery + URL extraction
│   │   ├── snapshots.py       # the crawl snapshot store (provenance, baselines, retention)
│   │   ├── crawler.py         # polite BFS crawler (schema v2 records)
│   │   ├── linkgraph.py       # alias-folded graph + honest orphan analysis
│   │   ├── redirect_analysis.py # shared redirect taxonomy (loops vs normalization)
│   │   ├── gsc_trends.py      # stdev-gated weekly drop detection
│   │   ├── gsc.py             # Search Console (property auto-resolution, pagination)
│   │   ├── psi.py             # PageSpeed Insights + CrUX (header auth)
│   │   ├── ahrefs.py          # Ahrefs v3
│   │   ├── dataforseo.py      # DataForSEO (task-status-checked)
│   │   ├── semrush.py         # Semrush domain reports
│   │   ├── bing_webmaster.py  # Bing WMT ({"d"} unwrapped, SubmitFeed)
│   │   ├── indexnow.py        # IndexNow (host-validated)
│   │   ├── firecrawl.py       # Firecrawl v2 (rendered-diff)
│   │   ├── schema_validate.py # tiered JSON-LD validation (required/recommended/info)
│   │   ├── ai_visibility.py   # LLM citation probing (error-state aware)
│   │   ├── llm.py             # BYOK text generation: Anthropic / OpenAI / Gemini
│   │   ├── images.py          # cover generation: OpenAI gpt-image / Gemini image
│   │   ├── sociavault.py      # SociaVault social-conversation search
│   │   ├── mentions.py        # deterministic brand-mention detection
│   │   ├── stats.py           # Wilson intervals for small-sample rates
│   │   ├── publication.py     # publication model, markdown → HTML, static renderer
│   │   ├── pubstate.py        # strategy / topic-map / pub-* state helpers
│   │   └── article.py         # markdown article ops: anchors, links, nothing-lost guard
│   └── dev/
│       ├── smoke.py           # opt-in LIVE per-integration harness (never in CI)
│       └── check_docs.py      # docs-vs-code contract linter (runs in CI)
├── tests/                     # offline pytest suite (fake transport, no network)
│   └── fixtures/              #   incl. a real measured publication article
└── .github/workflows/ci.yml   # pytest + check_docs on 3.9/3.12
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
   generated personas, theme) and `pub-strategy` records positioning.
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
