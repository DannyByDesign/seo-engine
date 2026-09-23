# Common setup & conventions (read once, applies to every seo-engine skill)

## Paths & working directory

- **Run every script from the target repo root** (the repo that contains the
  website, or its dedicated SEO workspace). Config and state discovery walk **up from the current working
  directory** to the nearest `.git`/`.seo-engine`/`package.json` marker, and all
  state lands in `<repo>/.seo-engine/` — running from the wrong cwd writes state
  to the wrong repo. For cron/CI, pin it explicitly with `SEO_REPO_ROOT=/path/to/repo`.
- **Host-neutral commands:** set `SKILL_DIR` to the resolved absolute directory containing
  the skill's `SKILL.md`, then run `python3 "$SKILL_DIR/scripts/<script>.py" [flags]`
  using the workspace's Python environment. No agent-specific environment variable is assumed.
- References in each `SKILL.md` are relative to its physical phase directory. Shared
  references are under `<engine>/shared/seo-references/`. Cross-phase scripts use their
  actual phase paths; sibling shortcuts are not valid across phases.
- Resolve symlinks before selecting a script path. An agent may substitute the absolute
  script path directly rather than set a shell variable. Skill discovery via `.agents/skills`
  or `.claude/skills` is optional; any host can read the same Markdown instructions directly.
- Scripts locate the engine's shared library by walking up from their own
  **resolved** file location; if skills were *copied* rather than symlinked, set
  `SEO_ENGINE_ROOT=/path/to/seo-engine` (scripts fail loudly with this remediation).

## Configuration resolution

- **`.env` at the target repo root** (never committed — install.sh gitignores it)
  holds API keys. Resolution order, later wins: workspace `.env` → process environment.
  Engine-adjacent credentials from another workspace are never loaded. Every key is optional.
  See the annotated root `.env.example` for purposes and setup locations.
- **`.seo-engine/config.yml`** (private/ignored by default) holds site facts: `site_url`,
  `sitemap_url`, `framework`, `static_source_dir`, `build_output_dir`,
  `target_topics`, `locales`, and the resolved `gsc_property`. Written by the
  seo-setup skill; read by everything else. `site_url` may also come from the
  `SEO_SITE_URL` env var; a missing/placeholder value raises `MissingConfigError`
  naming exactly what to set.
- **`static_source_dir` vs `build_output_dir`**: the former deploys verbatim to
  the site root (the ONLY safe place to write files that must ship — IndexNow
  key, llms.txt); the latter is wiped every build (scripts refuse to write there).

## Integration availability

`config.INTEGRATION_ENV_VARS` is the single source of truth mapping each
integration to its env var(s) — Google Search Console (either
`GOOGLE_APPLICATION_CREDENTIALS` or `GSC_SERVICE_ACCOUNT_JSON`), PageSpeed/CrUX
(`GOOGLE_PSI_API_KEY`), Ahrefs, DataForSEO (login **and** password), Firecrawl,
IndexNow, Semrush, Bing Webmaster, OpenAI, Anthropic, Perplexity, Gemini,
Profound, Otterly. See [api-reference.md](api-reference.md) for setup per
integration. Skills report exactly which env var unlocks a skipped capability —
`seo-setup`'s `check_integrations.py --format table` shows the full status.

GSC note: the API identifies properties as `sc-domain:example.com` or
URL-prefix-with-trailing-slash — never the bare site URL. Scripts resolve and
cache the right identifier automatically (`gsc_property` in config.yml); if GSC
calls fail with a property error, the message lists every property the service
account can see and what to fix.

## The `.seo-engine/` state contract

```
.seo-engine/
├── config.yml
├── onboarding.json   # goals, setup progress, integration decisions
├── knowledge.md      # current brand brief, read before strategy/content work
├── state/
│   ├── crawls/
│   ├── http-cache/
│   └── <skill>-*.json
└── reports/
```

### Snapshot contract (the one crawl store)

Every crawl lives in `state/crawls/` as `crawl-<UTCstamp>.jsonl` plus a
`crawl-<UTCstamp>.meta.json` **provenance sidecar** (producer skill, site_url,
max_pages, pages_crawled, `truncated`, `robots_status`, schema_version: 2).
Skills access it ONLY through `scripts/lib/snapshots.py`:

- `latest(cfg, max_age_hours=24)` — reuse a recent crawl from ANY skill instead
  of re-crawling (this is how runs build on each other).
- `new_crawl(cfg, "<skill>", max_pages=N)` — crawl fresh into the store.
- `find_baseline(cfg, current)` — the most recent **comparable** prior snapshot
  (same site, same max_pages, neither truncated). When nothing comparable
  exists it returns a machine-readable refusal that belongs in the report's
  `not_checked` section — diffing incomparable crawls reports coverage
  artifacts as regressions, so the store refuses instead.
- `prune(cfg)` — retention (10 crawls / 90 days; 30 reports per family / 180
  days), called by every script.

A crawl summary always carries `robots_status` and `all_blocked` — an empty
crawl states WHY (e.g. a WAF 403 on robots.txt) instead of producing a
silently-empty report.

## Publications (the `pub-*` skills)

A publication is content, so it lives in the target repo, committable, at
`<publications_dir>/<slug>/` (config key `publications_dir`, default `publications/`):

```
publications/<slug>/
├── site.yml
├── strategy.yml
├── topic-map.yml
├── seers.yml
├── competitors/
├── drafts/*.md
├── posts/*.md
├── assets/<post>/
├── static/
└── dist/
```

`.seo-engine/config.yml → publications` is the registry (`[{slug, site_url, name}]`) the
validator uses as the sibling set. Per-publication machine state is transient and lives under
`.seo-engine/state/` with a `pub-<name>-<slug>.json` naming family:
`pub-suggestions-<slug>.json` (headline queue), `pub-seers-<slug>.json` (seer cursors),
`pub-social-cache-<slug>.json` (SociaVault signal cache), `pub-geo-opportunities-<slug>.json`
(GEO gaps from monitoring), `pub-planner-<slug>.json` (publish slots), `pub-shred-<slug>.json`
(shredder telemetry), `pub-mentions-<slug>.json` (GEO mention history),
`pub-performance-<slug>.json` (Search Console history), `pub-refresh-<slug>.json` (refresh
checks), plus
`pub-research/<slug>/<article>/` (cached source texts). Reports use
`.seo-engine/reports/pub-<name>-<slug>-<stamp>.json`.

## Graceful degradation (report, don't gate)

Zero API keys is a supported configuration. A missing integration never crashes
a script and never silently narrows a report: every skipped capability appears
as `"checked": false` with the exact env var and remediation. When summarizing
results for a human, read `not_checked` first — "everything *checked* is fine"
and "everything is fine" are different claims.

Per-topic research and operator permissions live in the target's ignored
`.seo-engine/state/content/` as JSON records managed by `content_brief.py`.
They contain proposed publishable material and scoped confirmation, never raw private notes.
Article metadata and growth briefs carry a path/digest reference, not a company-wide approval.

Onboarding records and brand knowledge are local persistent context, not template content.
They are ignored by Git along with other private state; back them up privately for continuity.
A completed onboarding record is reused across sessions. Topic disclosure permissions remain
separate. Use each website's own repository; never switch domains over another site's state.

The agent may use `.seo-engine/onboarding-input.json` as ignored, non-secret working input
for the onboarding helper; it is not a second source of saved onboarding state.

## Installed code and website state

Prefer the existing website repository as the workspace. Native plugins keep reusable code
in their host's cache; direct installs keep it in `.seo-engine/engine/`. Neither location
owns the website's state. Run from the website root and use its `.seo-engine/venv/` Python
for requirements; never put brand knowledge or dependencies in a shared plugin cache.
The direct installer records its downloaded commit in `engine/.installed-by-bootstrap`.
Re-running it preserves the installed revision unless an update is requested; updates replace
only engine code and leave onboarding, knowledge, state, reports, credentials and the venv alone.
After updating, let the agent refresh dependencies in the website's environment if needed.
