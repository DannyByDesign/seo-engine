# seo-engine

A reusable, model-independent workspace template for growing one website through market
research, positioning, useful content, technical improvements and measured iteration.

**New here? Open your copy in an AI coding agent and say “Help me get started.”**
The agent follows [seo-setup](00-onboarding/seo-setup/SKILL.md), asks about your website and
goals, configures the relevant tools, and saves a brand brief for future sessions. You do not
need to read the skill catalog or edit environment variables yourself. If your agent doesn't
automatically read `AGENTS.md`, ask it to read `00-onboarding/seo-setup/SKILL.md` directly.

Start with **[Understand → Research → Position → Choose → Execute → Learn](workflow/README.md)**.
The installed `seo-growth` skill leads the host agent through this workflow. It derives its
own seeds and briefs from the website, calls specialized research APIs, writes in the site's
existing stack, and carries evidence and decisions between sessions. The actual skills, scripts,
writing corpus and phase instructions live under onboarding and six workflow directories:

```text
00-onboarding/  first-run interview, workspace setup and integration configuration
01-understand/  repository discovery, technical diagnosis, strategy recorder
02-research/    keyword/source research, vendor API collector and guide
03-position/    positioning skills
04-choose/      opportunity selection and growth orchestration
05-execute/     copywriting/corpus/LanguageTool, site changes, publication pipeline
06-learn/       analytics, monitoring, cycle runner and automation instructions
shared/        reference knowledge used across phases
scripts/lib/   shared Python implementation
```

`skills/` contains compatibility symlinks only; it is not a second copy of the implementation.

**[Research API guide](02-research/research-apis.md):** terminal DataForSEO SERPs, keyword ideas,
volumes and competitor rankings; Brave web discovery; Firecrawl search/scraping; existing
GSC/GA4 and optional keyword/backlink providers. Actual responses and failures are saved.

**[Topic interviews and approved contributions](shared/seo-references/content-interview.md):**
content runs research existing answers, interview the operator for this topic, and confirm
publishable material before outlining. Both writing paths bind article/page-specific permission;
new or changed input pauses for confirmation. Raw private notes stay out of writer prompts.

**[Human writing references](05-execute/seo-copywriting/SKILL.md):** 38 frozen sources, 373 excerpts,
51 passages curated for task-specific packets, and real examples inside the skill. All writing
is stored directly as local Markdown with basic metadata; no JSON catalog or live-link lookup.
LanguageTool is the standard proofreading pass for drafts and final edits, using an owned
server or authenticated API. The article
writer receives varied human references; first-party host agents use the same selection tool.

Install it in an existing website repo, then use `seo-growth` to compare opportunities, edit
actual source files, validate, verify deployment and evaluate attributable traffic. Diagnostic
skills handle focused SEO/GEO questions. Optional owned publications have reviewed content
and disclosed ownership. Neither clean audits nor generated articles establish traffic growth.

**Effectiveness is not yet demonstrated.** Tests cover software behavior, including static
and dynamic local websites. No production growth pilot or authenticated analytics result has
been supplied.

## What makes this different from "an SEO checklist"

1. **Sourced guidance with explicit limits.** The SEO/GEO playbooks link primary platform
   documentation and distinguish evidence from hypotheses. Crawl access supports eligibility;
   it does not guarantee rankings. No special AI schema or `llms.txt` is required by Google.
   Search partners and JavaScript handling vary by platform; avoid universal claims.
2. **Long-term only, by design.** [red-flags.md](shared/seo-references/red-flags.md) is a veto
   layer every content-touching skill consults before acting — no scaled *thin* content, no
   fabricated evidence, no freshness-faking, no doorway pages, no link schemes, no cloaking
   (including AI-crawler cloaking). Nothing in this system trades a short-term ranking bump for
   a policy risk down the line.
3. **It's real, tested software — not a prompt.** Twenty-six task skills (seventeen for a
   first-party site, nine `pub-*` skills for publications, plus a shared `seo-references`
   knowledge skill), each with a `SKILL.md` and working Python scripts that call real APIs
   (Google Search Console, PageSpeed Insights/CrUX, Ahrefs, DataForSEO, Semrush, Bing Webmaster
   Tools, IndexNow, Firecrawl, SociaVault, GitHub, Notion, OpenAI/Anthropic/Perplexity/Gemini)
   or crawl the live site directly. The shared library ships with an offline pytest suite, a documentation
   linter (`scripts/dev/check_docs.py` — every documented flag and state file is verified
   against the code), and an opt-in live smoke harness (`scripts/dev/smoke.py`) that exercises
   each configured integration against the real endpoints. Every integration is optional and
   degrades gracefully — the system works with zero API keys and gets more capable as you add
   them.
4. **Findings you can act on.** Detectors are built to be trustworthy, not noisy: crawl diffs
   only run against comparable baselines, redirect "loops" are real loops (a slash-normalizing
   redirect is not a finding), a single failed LLM probe is never reported as "lost citations,"
   and anything a script can't verify lands in an explicit `not_checked` section instead of
   silently vanishing.

## Where the lines are

Two families of skills, one veto layer. The `seo-*`/`geo-*` skills maintain a first-party
site. The `pub-*` skills build and run publications the operator owns — the charter in
[publication-playbook.md](shared/seo-references/publication-playbook.md) §1 — because the
publications can be tested as a separate editorial channel. Owned coverage is not independent
third-party endorsement; evaluate its actual contribution separately.
Both families are bound by [red-flags.md](shared/seo-references/red-flags.md):

- **Substance is the floor; volume is never the metric.** Publishing on a cadence is allowed
  (the planner defaults to six posts a week). Publishing thin content is not: every article
  goes through research against fetched sources, a number verifier, and a gate that refuses
  drafts under the word and source floors (red-flags §1, §7).
- **No fabricated evidence.** Publication requires accountable editorial review; automated numeric matching alone cannot establish truth. Research retains sources the pipeline actually
  read. Numeric-presence checks are diagnostics; contextual factual review is required.
- **Honest mentions.** A publication names and links its client only within the configured
  mention degree and rate, at most one client link per article, and only where the client is
  the accurate answer (playbook §6). Ownership disclosure is enabled by default; factual review is required
  per publication.
- **No cloaking, no freshness-faking, no doorway pages, no link schemes.** Publications never
  interlink, external citations are `nofollow`, `published_at` is set exactly once, and
  refreshes preserve URLs and useful content while adding a substantive improvement.
- **No link building.** `seo-backlinks` is monitoring-only, by design.

## One workspace per website

This repository is the public template. Make a **separate working copy for each website**,
with a descriptive name such as `acme-seo`. Each copy keeps its own goals, brand knowledge,
research, article permissions and credentials. Don't switch a configured copy between brands.

Use the hosting provider's template feature, or clone the published repository into your
chosen directory. Open it in your AI agent and say:

> Help me get started with this SEO Engine workspace for my website.

The agent asks about the site, audience, desired outcome and constraints; investigates what
it can itself; then sets up only useful integrations. It handles local configuration. You
only provide decisions and account actions such as signing in or entering a key in a hidden
input. You can skip integrations and add them later. Interrupted setup resumes; completed
setup isn't repeated on every session.

A standalone workspace supports research, remote-site diagnosis and drafts. To edit an
existing site's source, use a dedicated engine copy **inside that website's repository**
(for example `tools/seo-engine/`) and make the website root the workspace. Source/CMS access
is needed to implement or deploy changes; a remote URL alone doesn't supply it.

The descriptive identity lives in the clone name and saved brand brief. Onboarding does not
rewrite reusable skills, change Git remotes, or rename an open directory. A future personal
remote should be chosen explicitly. Private local knowledge isn't pushed to the template.

## Agent and model support

The entry points are ordinary Markdown plus Python scripts. Any agent able to read files,
ask questions, edit files and run commands can follow them. Use a question tool when the
host has one, otherwise normal conversation. No Claude-only runtime or model is required.
`AGENTS.md` provides portable guidance; `CLAUDE.md` simply points to it.

Agent discovery adapters are optional. From a standalone clone, the agent can run:

```bash
bash install.sh                         # portable setup; default target is this clone
bash install.sh "$PWD" "$PWD" codex     # optional .agents/skills discovery
bash install.sh "$PWD" "$PWD" claude    # optional .claude/skills discovery
```

For an embedded engine, pass its absolute path and the **website root** explicitly:
`bash tools/seo-engine/install.sh /absolute/site/tools/seo-engine /absolute/site generic`.
The default no longer targets the parent directory. Skill links are relative so moving the
whole workspace preserves them. Existing files/other skill installations are preserved.
Onboarding creates a virtual environment, installs `requirements.txt`, and uses its Python.
The installer itself only handles local links/ignore rules and an empty `.env`.

Host-agent research and writing use your chosen model with no extra model API. The optional
scripted publication text client supports **OpenAI, Anthropic and Gemini**; select a provider
explicitly during onboarding. Other models can drive the host workflow, but arbitrary API
endpoints are not implemented. The Claude plugin package is an optional discovery adapter.

## After onboarding

Say **“Continue with our next SEO task”** or **“Use seo-growth to work on [goal].”** The agent
reads the saved brand brief and follows Understand → Research → Position → Choose → Execute
→ Learn, loading only the skills needed for the next step. Use `seo-maintain` for a checkup.

For an article, say **“Research and draft an article about [topic] for our audience.”** The
agent researches existing answers, interviews you about that topic, confirms what can be
published, studies the human writing corpus, and edits the full draft. The onboarding
interview supplies context; it never replaces per-topic disclosure permission.

An owned publication is an optional route selected during setup. Its skills scaffold the
site, plan topics, generate reviewed articles and monitor results. Existing website work
remains in its actual framework/CMS.

## Configuration and private knowledge

[.env.example](.env.example) is the annotated variable reference: what each setting unlocks,
which values go together, setup locations, and which goals need it. These are options, not
a checklist of accounts to purchase. Keys are supplied through hidden terminal input or a
user-selected credential file; the agent handles the `.env` edits and relevant checks.

| Workspace file | Purpose |
|---|---|
| `.seo-engine/onboarding.json` | Setup progress, goals, integration decisions and next action |
| `.seo-engine/knowledge.md` | Current brand brief, positioning, constraints and useful learned context |
| `.seo-engine/config.yml` | Site URL, framework, source/build paths and integration-specific site settings |
| `.env` | Local credentials/settings; process environment can override these |
| `.seo-engine/state/` and `.seo-engine/reports/` | Research, scoped article permissions, strategy and measurement records |

These files are **ignored by Git**. They persist between local sessions, but pushing the repo
is not a backup of them: arrange private backup for continuity across machines. Only reviewed,
shareable output should enter version control. Never force-add private state or credentials.
Each workspace loads its own `.env`; it does not inherit keys from the engine's other copies.
Pin `SEO_REPO_ROOT` in scheduled runs. See [common setup](shared/seo-references/common-setup.md).

## The 26 task skills

### First-party site (`seo-*`, `geo-*`)

| Skill | What it does |
|---|---|
| [`seo-setup`](00-onboarding/seo-setup/SKILL.md) | Guided, resumable onboarding — one-site identity, goals, brand brief, selective integrations and next action |
| [`seo-growth`](04-choose/seo-growth/SKILL.md) | Understand → research → position → choose → execute → learn; evidence-bound strategy, terminal APIs and durable jobs |
| [`seo-copywriting`](05-execute/seo-copywriting/SKILL.md) | Frozen human prose inside the skill, 38 frozen sources and 373 indexed passages; diverse reference packets and copying diagnostics |
| [`seo-maintain`](06-learn/seo-maintain/SKILL.md) | Orchestrator — regression-first prioritized checkup against a comparable baseline, dispatches to the rest |
| [`seo-technical-audit`](01-understand/seo-technical-audit/SKILL.md) | Crawl-based audit: status codes, canonicals, evidence-laddered noindex, sitemaps, broken links, JS-rendering gaps |
| [`seo-metadata`](05-execute/seo-metadata/SKILL.md) | Titles, descriptions, OG/Twitter cards — audit + source-level fixes |
| [`seo-structured-data`](05-execute/seo-structured-data/SKILL.md) | JSON-LD generation + tiered offline validation (traditional rich-result value, not a GEO lever) |
| [`seo-performance`](05-execute/seo-performance/SKILL.md) | Core Web Vitals (LCP/INP/CLS) via PSI + CrUX → concrete code-level fixes |
| [`seo-indexing`](05-execute/seo-indexing/SKILL.md) | Sitemap discovery/submission, GSC coverage checks, IndexNow (Bing/Yandex — not Google, but Bing feeds ChatGPT) |
| [`seo-keyword-research`](02-research/seo-keyword-research/SKILL.md) | GSC near-miss opportunities cross-referenced with Ahrefs/DataForSEO volume data |
| [`seo-content-optimize`](05-execute/seo-content-optimize/SKILL.md) | Research-backed first-party copy, new useful pages, and evidence-based refreshes |
| [`seo-internal-linking`](05-execute/seo-internal-linking/SKILL.md) | Link graph, sitemap/GSC-grounded orphan detection, contextual link suggestions |
| [`seo-backlinks`](06-learn/seo-backlinks/SKILL.md) | Backlink **monitoring only** — new/lost links with statistical guardrails, broken-backlink fixes (never acquisition) |
| [`seo-redirects`](05-execute/seo-redirects/SKILL.md) | Config-level redirect audit, honest loop detection, migration-safety validation |
| [`seo-rank-tracking`](06-learn/seo-rank-tracking/SKILL.md) | GSC position history with stdev-gated drop alerts, optional live SERP checks |
| [`geo-optimize`](05-execute/geo-optimize/SKILL.md) | AI-crawler robots.txt audit (per-vendor, RFC 9309-correct), cloaking check, free JS-visibility check, narrowly-scoped llms.txt |
| [`geo-monitor`](06-learn/geo-monitor/SKILL.md) | AI-citation probing (multi-sample, flap-damped) via OpenAI/Anthropic/Perplexity/Gemini APIs, brand-mention tracking (mention rate, share of voice, Wilson intervals), log/GA4 signals |

### Publications (`pub-*`)

| Skill | What it does |
|---|---|
| [`pub-site`](05-execute/pub-site/SKILL.md) | Scaffold a publication (theme, sections, real contributor or organization attribution), build the static site (posts, sections, authors, RSS, `llms.txt`, sitemap, JSON-LD) for Vercel, validate it against the measured anatomy |
| [`pub-strategy`](03-position/pub-strategy/SKILL.md) | Positioning — client, direction, priority topics, stances, ranking targets, landings, competitors — plus competitor catalogue scraping |
| [`pub-curate`](04-choose/pub-curate/SKILL.md) | Topic map (pillars → spokes), scored suggestions (competitor, GEO gap, SEO volume, cluster, authority, social conversations via SociaVault), seers (news, regulation, social trends, GitHub, specs, Notion) |
| [`pub-research`](02-research/pub-research/SKILL.md) | Plan → search → read → synthesize → verify: an outline whose every point cites a fetched source, with an optional direction gate |
| [`pub-write`](05-execute/pub-write/SKILL.md) | Long-read drafting under a voice kernel with candidate judging, the mention decision, and the Shredder (sentence-level voice diversity across providers) |
| [`pub-enhance`](05-execute/pub-enhance/SKILL.md) | Internal links, Sources list, numeric anchors, diagram placement, number verifier, metadata; retro-relink of older posts |
| [`pub-visuals`](05-execute/pub-visuals/SKILL.md) | Diagram renderer (stat callout, flow, funnel, comparison, timeline) and cover generation (OpenAI or Gemini, SVG fallback) |
| [`pub-publish`](05-execute/pub-publish/SKILL.md) | Planner (cadence, sourcing, approval posture), the quality gate, and the one-command article pipeline |
| [`pub-monitor`](06-learn/pub-monitor/SKILL.md) | Per-publication Search Console rollups, awaiting/receiving indexing proxy, refresh triggers, GEO-gap sync from brand-mention runs |

## Reference knowledge base

Lives in [`shared/seo-references/`](shared/seo-references/SKILL.md) (installed alongside the
task skills): `seo-playbook.md`, `geo-playbook.md`, `publication-playbook.md` (the measured
publication model the `pub-*` skills reproduce), `red-flags.md` (the veto layer),
`api-reference.md`, and `common-setup.md` (paths, config, snapshot and publication contracts).

## Testing

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
python3 -m pytest tests/
python3 scripts/dev/check_docs.py
python3 scripts/dev/smoke.py --site https://your-site.example
```

CI (`.github/workflows/ci.yml`) runs the offline suite + the docs linter on Python 3.9 and
3.12. The smoke harness is local-only by design — it spends real quota against real APIs.

## Updating the knowledge base

The reference playbooks are dated research — SEO/GEO (especially the GEO side) moves fast.
Re-verify on this cadence, and run `python3 scripts/dev/check_docs.py` after any docs edit:

| What | Where | Re-verify |
|---|---|---|
| AI-crawler table (names, purposes, blocking effects) | geo-playbook §4 | Quarterly |
| Bing→ChatGPT index dependency | geo-playbook §10 | Quarterly (one OpenAI announcement can invalidate it) |
| AI crawlers don't render JS | geo-playbook §11 | Semi-annually |
| llms.txt non-effect | geo-playbook §1 | Semi-annually |
| Spam-policy enforcement mechanics | red-flags.md preamble/§1 | Quarterly |
| API endpoints/quotas/pricing | api-reference.md | On any new 4xx pattern, or via `smoke.py` |
| Publication anatomy (routes, schema, article shape, cadence) | publication-playbook §2–§4 | Quarterly — re-measure the live examples listed in its Sources |
| LLM / image model ids | `scripts/lib/llm.py`, `scripts/lib/images.py` (env-overridable) | On any deprecation notice |
| CWV thresholds | seo-playbook §3 | Annually |

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system design, directory layout, and the
shared Python library (`scripts/lib/`) every skill script builds on.

## Evidence and limits

This toolkit has not yet demonstrated traffic lift on a live pilot. Local builds and API citation probes do not establish organic visits. Use the existing website first; optional publications require transparent attribution, ownership disclosure and review of final claims.

Start first-party growth work with [`seo-growth`](04-choose/seo-growth/SKILL.md). It connects website improvements to real analytics exports; the GA4 adapter needs a numeric `GA4_PROPERTY_ID` and service-account Viewer access.

For recurring operation, configure the target host's scheduler with the
[growth-cycle prompt](shared/seo-references/growth-cycle.md). `seo-growth/scripts/run_cycle.py` generates
a resumable work packet; `--execute-agent` calls an explicitly configured agent wrapper.
The installer does not silently activate paid runs or a scheduler.
