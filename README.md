# seo-engine

Continuous, sustainable SEO + GEO (Generative Engine Optimization) maintenance for any
website — as a portable folder of skills an AI coding agent can invoke directly in your repo.

Copy this folder into a repo that contains a website, install its skills, and any AI agent
working in that repo gains the ability to audit, fix, and continuously improve both classic
search-engine visibility (Google, Bing) and AI-answer-engine visibility (ChatGPT, Perplexity,
Claude, Gemini, Copilot, Google AI Overviews/AI Mode) — grounded in a research-verified
knowledge base, not SEO folklore.

It also builds and runs **independent publications**: topic-focused sites with their own
bylines, sections, cadence, and evidence pipeline, whose articles earn search traffic and
AI-assistant citations and mention the operator's product only where it is the honest answer.
That is the "phantom blog" model a category of vendors sells; the nine `pub-*` skills reproduce
it from measured live examples (the teardown lives in [`research/`](research/)).

## What makes this different from "an SEO checklist"

1. **Every strategy is sourced.** [seo-playbook.md](skills/seo-references/seo-playbook.md) and
   [geo-playbook.md](skills/seo-references/geo-playbook.md) cite primary sources (Google's own
   documentation, disclosed-methodology studies) and explicitly separate established fact from
   vendor speculation. The single most load-bearing negative finding — that `llms.txt` does
   **not** drive AI citation, despite being the most commonly recommended GEO tactic — is stated
   plainly, with the data behind it. So are the two most under-used positive ones: Bing's index
   is what ChatGPT search retrieves against (geo-playbook §10), and no major AI crawler executes
   JavaScript (§11) — which makes server-rendering your content the highest-leverage technical
   GEO intervention there is.
2. **Long-term only, by design.** [red-flags.md](skills/seo-references/red-flags.md) is a veto
   layer every content-touching skill consults before acting — no scaled *thin* content, no
   fabricated evidence, no freshness-faking, no doorway pages, no link schemes, no cloaking
   (including AI-crawler cloaking). Nothing in this system trades a short-term ranking bump for
   a policy risk down the line.
3. **It's real, tested software — not a prompt.** Twenty-four task skills (fifteen for a
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
[publication-playbook.md](skills/seo-references/publication-playbook.md) §1 — because the
strongest measured AI-visibility correlates (brand mentions, third-party coverage) live off the
first-party site, and a publication is the one off-site lever an operator can run honestly.
Both families are bound by [red-flags.md](skills/seo-references/red-flags.md):

- **Substance is the floor; volume is never the metric.** Publishing on a cadence is allowed
  (the planner defaults to six posts a week). Publishing thin content is not: every article
  goes through research against fetched sources, a number verifier, and a gate that refuses
  drafts under the word and source floors (red-flags §1, §7).
- **No fabricated evidence.** Every statistic is anchored to a source the pipeline actually
  read; a number it cannot verify is dropped, never invented.
- **Honest mentions.** A publication names and links its client only within the configured
  mention degree and rate, at most one client link per article, and only where the client is
  the accurate answer (playbook §6). Sponsorship disclosure is off by default and switchable
  per publication.
- **No cloaking, no freshness-faking, no doorway pages, no link schemes.** Publications never
  interlink, external citations are `nofollow`, `published_at` is set exactly once, and
  refreshes are real rewrites.
- **No link building.** `seo-backlinks` is monitoring-only, by design.

## Install

```bash
# 1. Copy this folder into the target repo (anywhere — repo root is simplest)
cp -r seo-engine /path/to/your-website-repo/

# 2. Link its skills into Claude Code's skill discovery path + scaffold .env
cd /path/to/your-website-repo/seo-engine
./install.sh

# 3. Install Python dependencies (Python 3.9+)
python3 -m pip install -r requirements.txt
```

`install.sh` symlinks each `skills/*` directory (the 24 task skills plus `seo-references`)
into `<your-repo>/.claude/skills/`, writes an inert stub `.env` (never placeholder values —
add only keys you actually have), and makes sure `.env` and `.seo-engine/` are gitignored in
the target repo. Scripts self-locate the engine through the symlinks; if you copy skills
instead of symlinking, set `SEO_ENGINE_ROOT=/path/to/seo-engine`.

This also works as a Claude Code plugin (see `.claude-plugin/plugin.json`) — `skills/` at the
folder root is discoverable either way. All skill commands run from the **target repo root**
(state lands in `<repo>/.seo-engine/`); pin it with `SEO_REPO_ROOT` for cron/CI. See
[common-setup.md](skills/seo-references/common-setup.md) for the full path/state contract.

## Quickstart

In an agent session inside your website repo:

1. Invoke **`seo-setup`** — detects your framework (Next.js, Astro, Nuxt, SvelteKit, Hugo,
   plain HTML, ...) including where static files must live vs. where builds are wiped, confirms
   your production `site_url` with you, writes `.seo-engine/config.yml`, and reports which
   optional integrations are configured vs. what unlocks with which env var.
2. Invoke **`seo-maintain`** any time you want a checkup — it refreshes a crawl snapshot,
   flags regressions first (broken links, accidental noindex, indexing issues), ranks
   opportunities, and tells you which specific skill to invoke for each item.
3. Invoke any of the other skills directly when you know what you want to work on.
4. To run a publication: **`pub-site`** scaffolds, builds and validates it; **`pub-strategy`**
   records positioning; **`pub-curate`** builds the topic map and the queue; **`pub-publish`**
   runs the pipeline on a cadence; **`pub-monitor`** and **`geo-monitor`** report whether it is
   working. The [publication-playbook](skills/seo-references/publication-playbook.md) explains
   the model and the measured anatomy the skills reproduce.

## Configuration

- **`.env`** (git-ignored, never commit) — API keys, all optional. See
  [.env.example](.env.example) for the complete list with setup instructions for each.
- **`.seo-engine/config.yml`** (safe to commit) — site URL, sitemap, detected framework,
  static-source/build-output dirs, resolved GSC property, target topics/locales. Written by
  `seo-setup`, read by every other skill.
- **`.seo-engine/state/`** and **`.seo-engine/reports/`** (git-ignored) — the shared crawl
  snapshot store (with provenance sidecars so skills reuse each other's crawls safely),
  per-skill history, and dated reports. Retention is pruned automatically.

## The 24 task skills

### First-party site (`seo-*`, `geo-*`)

| Skill | What it does |
|---|---|
| [`seo-setup`](skills/seo-setup/SKILL.md) | Onboarding — detect stack (incl. static-source vs build-output dirs), write config, report integration status |
| [`seo-maintain`](skills/seo-maintain/SKILL.md) | Orchestrator — regression-first prioritized checkup against a comparable baseline, dispatches to the rest |
| [`seo-technical-audit`](skills/seo-technical-audit/SKILL.md) | Crawl-based audit: status codes, canonicals, evidence-laddered noindex, sitemaps, broken links, JS-rendering gaps |
| [`seo-metadata`](skills/seo-metadata/SKILL.md) | Titles, descriptions, OG/Twitter cards — audit + source-level fixes |
| [`seo-structured-data`](skills/seo-structured-data/SKILL.md) | JSON-LD generation + tiered offline validation (traditional rich-result value, not a GEO lever) |
| [`seo-performance`](skills/seo-performance/SKILL.md) | Core Web Vitals (LCP/INP/CLS) via PSI + CrUX → concrete code-level fixes |
| [`seo-indexing`](skills/seo-indexing/SKILL.md) | Sitemap discovery/submission, GSC coverage checks, IndexNow (Bing/Yandex — not Google, but Bing feeds ChatGPT) |
| [`seo-keyword-research`](skills/seo-keyword-research/SKILL.md) | GSC near-miss opportunities cross-referenced with Ahrefs/DataForSEO volume data |
| [`seo-content-optimize`](skills/seo-content-optimize/SKILL.md) | On-page improvement guided by real staleness signals + the one evidence-backed GEO content tactic |
| [`seo-internal-linking`](skills/seo-internal-linking/SKILL.md) | Link graph, sitemap/GSC-grounded orphan detection, contextual link suggestions |
| [`seo-backlinks`](skills/seo-backlinks/SKILL.md) | Backlink **monitoring only** — new/lost links with statistical guardrails, broken-backlink fixes (never acquisition) |
| [`seo-redirects`](skills/seo-redirects/SKILL.md) | Config-level redirect audit, honest loop detection, migration-safety validation |
| [`seo-rank-tracking`](skills/seo-rank-tracking/SKILL.md) | GSC position history with stdev-gated drop alerts, optional live SERP checks |
| [`geo-optimize`](skills/geo-optimize/SKILL.md) | AI-crawler robots.txt audit (per-vendor, RFC 9309-correct), cloaking check, free JS-visibility check, narrowly-scoped llms.txt |
| [`geo-monitor`](skills/geo-monitor/SKILL.md) | AI-citation probing (multi-sample, flap-damped) via OpenAI/Anthropic/Perplexity/Gemini APIs, brand-mention tracking (mention rate, share of voice, Wilson intervals), log/GA4 signals |

### Publications (`pub-*`)

| Skill | What it does |
|---|---|
| [`pub-site`](skills/pub-site/SKILL.md) | Scaffold a publication (theme, sections, generated personas), build the static site (posts, sections, authors, RSS, `llms.txt`, sitemap, JSON-LD) for Vercel, validate it against the measured anatomy |
| [`pub-strategy`](skills/pub-strategy/SKILL.md) | Positioning — client, direction, priority topics, stances, ranking targets, landings, competitors — plus competitor catalogue scraping |
| [`pub-curate`](skills/pub-curate/SKILL.md) | Topic map (pillars → spokes), scored suggestions (competitor, GEO gap, SEO volume, cluster, authority, social conversations via SociaVault), seers (news, regulation, social trends, GitHub, specs, Notion) |
| [`pub-research`](skills/pub-research/SKILL.md) | Plan → search → read → synthesize → verify: an outline whose every point cites a fetched source, with an optional direction gate |
| [`pub-write`](skills/pub-write/SKILL.md) | Long-read drafting under a voice kernel with candidate judging, the mention decision, and the Shredder (sentence-level voice diversity across providers) |
| [`pub-enhance`](skills/pub-enhance/SKILL.md) | Internal links, Sources list, numeric anchors, diagram placement, number verifier, metadata; retro-relink of older posts |
| [`pub-visuals`](skills/pub-visuals/SKILL.md) | Diagram renderer (stat callout, flow, funnel, comparison, timeline) and cover generation (OpenAI or Gemini, SVG fallback) |
| [`pub-publish`](skills/pub-publish/SKILL.md) | Planner (cadence, sourcing, approval posture), the quality gate, and the one-command article pipeline |
| [`pub-monitor`](skills/pub-monitor/SKILL.md) | Per-publication Search Console rollups, awaiting/receiving indexing proxy, refresh triggers, GEO-gap sync from brand-mention runs |

## Reference knowledge base

Lives in [`skills/seo-references/`](skills/seo-references/SKILL.md) (installed alongside the
task skills): `seo-playbook.md`, `geo-playbook.md`, `publication-playbook.md` (the measured
publication model the `pub-*` skills reproduce), `red-flags.md` (the veto layer),
`api-reference.md`, and `common-setup.md` (paths, config, snapshot and publication contracts).
The research behind the publication playbook — a teardown of a live vendor's phantom
publications and its open-source monitor — is in [`research/`](research/).

## Testing

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
python3 -m pytest tests/                 # offline unit suite (no network, sub-second)
python3 scripts/dev/check_docs.py        # docs-vs-code contract linter
python3 scripts/dev/smoke.py --site https://your-site.example   # opt-in LIVE harness:
                                         # one cheapest real call per configured integration
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
