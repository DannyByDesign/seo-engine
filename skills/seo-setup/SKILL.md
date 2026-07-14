---
name: seo-setup
description: Onboarding and bootstrap for seo-engine in a target repo — detects the tech stack (framework, static_source_dir, build_output_dir, sitemap) and reports which of 14 optional integrations (GSC, PSI, Ahrefs, DataForSEO, Semrush, Bing Webmaster, Firecrawl, IndexNow, LLM providers, Profound, Otterly) are configured vs. missing. Invoke first whenever seo-engine was just copied into a repo, .seo-engine/config.yml is missing/stale, or when asked to "set up SEO" / "what integrations do we have". Not for ongoing checks once configured — seo-maintain.
---

# seo-setup

The onboarding skill. Nothing else in seo-engine works reliably until `.seo-engine/config.yml`
exists with a correct `site_url` — every other skill's `Config.site_url` raises
`MissingConfigError` without it. Run this once per target repo (re-run `check_integrations.py`
any time env vars change).

## When to use this skill

- seo-engine was just copied/installed into a repo and `.seo-engine/` doesn't exist yet.
- `.seo-engine/config.yml` exists but looks incomplete (missing `site_url`, `framework`, or
  `sitemap_url`) or the repo's stack has visibly changed (e.g. a framework migration).
- The user asks to "set up SEO", "install seo-engine here", "configure SEO integrations", or asks
  what API keys are or aren't hooked up.
- `seo-maintain` is invoked in a repo where `.seo-engine/config.yml` is absent — it should call
  this skill first rather than failing.
- **Not** for ongoing checks once configured — that's `seo-maintain`'s recurring loop.

## What it checks / does

Both scripts are **strictly read-only** — neither writes anything to disk, ever. Writing
`.seo-engine/config.yml` is the calling agent's job (Step 3 below), not a script's.

1. **Detect the stack** — `scripts/detect_stack.py` scans the filesystem only (no network calls,
   no API keys) and reports a framework guess, `static_source_dir`/`build_output_dir` per
   framework, sitemap presence, and any existing `.seo-engine/config.yml`.
2. **Confirm `site_url` with the user** — agent judgment, not scriptable (Step 2 below).
3. **Write `.seo-engine/config.yml`** — the agent's job, using `detect_stack.py`'s
   `suggested_config` block plus the confirmed `site_url` (Step 3 below).
4. **Check integration status** — `scripts/check_integrations.py` reports which of 14 optional
   integrations are configured, derived directly from `config.INTEGRATION_ENV_VARS` (no
   duplicated env-var list).

### Step 1 — detect the stack

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/detect_stack.py"
python3 "${CLAUDE_SKILL_DIR}/scripts/detect_stack.py" --dir /path/to/other-repo
```

Recognized frameworks: `next.js`, `astro`, `nuxt`, `sveltekit`, `gatsby`, `hugo`, `jekyll`,
`eleventy`, `vite`, low-confidence fallbacks `react`/`vue`, and `static-html` for a bare
`index.html`. `confidence` is `high` only when both a config file and a package.json dependency
matched; `sveltekit` is claimed only when `@sveltejs/kit` is an actual package.json dependency
(a bare `svelte.config.js` alone falls through to `vite`); the generic `hugo` config names
(`config.toml`/`.yaml`/`.yml`) are claimed only when `/content` or `/layouts` exists (the
Hugo-specific `hugo.toml`/`.yaml`/`.yml` names match unconditionally). Treat `low`/`none`
confidence as a cue to ask the user to confirm rather than trusting the report.

**`sitemap.found: false` is not this skill's problem to fix** — hand it to `seo-technical-audit` /
`seo-indexing` later (seo-playbook.md §2). **If `existing_seo_engine_config.found: true`, stop and
read that file before doing anything else** (see Step 3).

### Step 2 — confirm `site_url` with the user (agent judgment, not scriptable)

The script cannot reliably determine the production `site_url` — a repo may have a local dev URL,
a staging URL, a framework-default deploy domain, and the real production domain all plausibly
present. **Never guess this from `package.json`'s `homepage`, a README, or a deploy config without
asking** — a wrong `site_url` silently breaks every GSC, sitemap, and IndexNow call downstream.

Ask directly: "What is the production URL for this site?" Normalize to scheme + host, no trailing
slash (e.g. `https://example.com`). Also confirm or leave blank: the sitemap URL (propose
`{site_url}/sitemap.xml` only if `detect_stack.py` actually found one — never invent a path that
doesn't exist yet); `target_topics`/`locales` almost never exist at onboarding — write empty
scaffolds, don't guess keywords.

### Step 3 — write `.seo-engine/config.yml`

```yaml
site_url: "https://example.com"                  # required, no trailing slash
sitemap_url: "https://example.com/sitemap.xml"    # optional but recommended
framework: "next.js"                              # from detect_stack.py's suggested_config
static_source_dir: "public"                       # from suggested_config — deploys verbatim
build_output_dir: ".next"                         # from suggested_config — wiped every build
target_topics: []                                 # empty scaffold; fill in later
locales: []                                       # empty scaffold; fill in later
```

`static_source_dir` is the only safe place for a later skill to write a file that must ship
(IndexNow key, llms.txt); `build_output_dir` is wiped every build and scripts refuse to write
there — see common-setup.md. `sitemap_url`/`framework`/`static_source_dir`/`build_output_dir`/
`target_topics`/`locales` aren't read via a dedicated `Config` property (only `site_url` has one)
but other skills read them directly off `cfg.site` — keep the key names exactly as shown.
`gsc_property` is never written here; it's resolved and cached automatically on first GSC call.

**If `.seo-engine/config.yml` already exists:** show a diff between what exists and what you're
about to write; only overwrite fields the user confirms. Never silently clobber a populated
`target_topics`/`locales` with an empty one.

### Step 4 — check integration status

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/check_integrations.py"
python3 "${CLAUDE_SKILL_DIR}/scripts/check_integrations.py" --format table
```

Rows are derived by iterating `config.INTEGRATION_ENV_VARS` directly (never a separately
maintained list), so this script can't drift out of sync with what other skills actually check.
Each row: `configured`, `env_vars`, `env_var_rule` (`any one of these suffices` /
`all of these are required together` / `required`), `how_to_configure`, `unlocks`, `cost`.
Covers all 14 tracked integrations, including a per-vendor `unlocks` line for `profound` and
`otterly` (cross-validation of `geo-monitor`'s citation tracking against each commercial
dashboard).

Once keys are configured, GSC property resolution (`sc-domain:` vs. URL-prefix) happens
automatically on the first GSC call and is cached in `config.yml` as `gsc_property` — no separate
setup step. For cron/scheduled runs, set `SEO_REPO_ROOT` so state always lands in the right repo.

## Running it

> All commands below run from the **target repo root** (the repo that contains the
> website). State and reports land in `<repo>/.seo-engine/` — running from anywhere
> else writes state to the wrong repo. `${CLAUDE_SKILL_DIR}` is set by Claude Code to
> this skill's directory and works for both the symlink and plugin install.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/detect_stack.py"
python3 "${CLAUDE_SKILL_DIR}/scripts/check_integrations.py" --format table
```

Flags: `detect_stack.py --dir <path>` (default cwd); `check_integrations.py --format
{json,table}` (default json).

## Expected output

`detect_stack.py` (printed to stdout only — nothing written to disk):

```jsonc
{
  "scanned_dir": "/path/to/target-repo",
  "framework": {
    "framework": "next.js", "confidence": "high",
    "evidence": ["config file: next.config.js", "package.json dependency: next"],
    "static_source_dir": { "path": "public", "exists": true },
    "build_output_dir": { "path": ".next", "exists": false },
    "notes": "..."
  },
  "sitemap": { "found": true, "kind": "static_file", "path": "public/sitemap.xml", "notes": "..." },
  "existing_seo_engine_config": { "found": false, "path": null, "notes": "..." },
  "suggested_config": { "framework": "next.js", "static_source_dir": "public", "build_output_dir": ".next" },
  "next_step": "Do NOT auto-write .seo-engine/config.yml from this report alone. ..."
}
```

`check_integrations.py`:

```jsonc
{
  "site_url": "https://example.com",
  "summary": "3/14 optional integrations configured (zero are required ...)",
  "integrations": [
    { "integration": "Google Search Console", "key": "google_search_console",
      "configured": false, "env_vars": ["GOOGLE_APPLICATION_CREDENTIALS", "GSC_SERVICE_ACCOUNT_JSON"],
      "env_var_rule": "any one of these suffices", "how_to_configure": "...",
      "unlocks": "Search Analytics, sitemap submission, URL Inspection ...", "cost": "free" }
  ],
  "note": "..."
}
```

## State files

Neither script writes to `.seo-engine/` — both are read-only. `.seo-engine/config.yml` is written
by the **calling agent** in Step 3, not by any script in this skill.

| File (under `.seo-engine/`) | Role | Written by | Read by |
|---|---|---|---|
| `config.yml` | site facts: `site_url`, `sitemap_url`, `framework`, `static_source_dir`, `build_output_dir`, `target_topics`, `locales`, `gsc_property` | the calling agent (Step 3) | every other skill |

## How to interpret results

- **Report, don't gate.** Zero integrations are required — `google_search_console` and
  `pagespeed_insights` (both free) are the highest-value first configurations since most other
  skills build on them, but every skill degrades gracefully without any given key.
- **Prioritize free before paid**: Google Search Console and PageSpeed Insights first, then
  IndexNow (free), then paid APIs only if budget/scale justifies them.
- If `dataforseo.configured: false` but the user believes it's set up, check both
  `DATAFORSEO_LOGIN` and `DATAFORSEO_PASSWORD` are present — that row's `env_var_rule` is "all of
  these are required together" (HTTP Basic Auth pair); having only one reports as not-configured.
- `confidence: "low"` or `"none"` on the framework guess is a cue to ask the user, not to proceed
  as if the report were certain.

## Safe to auto-apply vs. human review

**Safe without asking:** running `detect_stack.py` and `check_integrations.py` (both read-only,
zero side effects); writing a brand-new `.seo-engine/config.yml` when
`existing_seo_engine_config.found` is `false` **and** `site_url` was explicitly confirmed by the
user this session.

**Requires explicit human confirmation:** overwriting an existing `config.yml` (show the diff
first); the `site_url` value itself — always ask, never infer; any `framework` mismatch between
`detect_stack.py`'s report and what the user says is actually deployed — flag, don't pick one.

This skill never touches page content, schema, redirects, or any site-behavior-affecting file —
the red-flags.md content/manipulation guardrails become relevant starting with the skills this one
hands off to, not this skill's own actions.

## Guardrails

- Never write `site_url` without explicit user confirmation this session, even if a plausible
  value exists in `package.json` or a deploy config.
- Never invent a `sitemap_url` path that `detect_stack.py` didn't actually find.
- Never silently overwrite a populated `target_topics`/`locales` list with an empty scaffold.

## References

- [common-setup.md](../seo-references/common-setup.md) — paths, config resolution, the
  `static_source_dir` vs. `build_output_dir` distinction, the full `.seo-engine/` state contract.
- [seo-playbook.md](../seo-references/seo-playbook.md) §2 — why sitemap presence matters,
  referenced when reporting `sitemap.found: false`.
- [red-flags.md](../seo-references/red-flags.md) §6 — the meta-rule that still applies to any
  judgment call this skill makes, e.g. never silently overwrite a prior human's config.

## Graceful degradation

Generic philosophy: [common-setup.md § Graceful degradation](../seo-references/common-setup.md).
Skill-specific: both scripts need zero API keys and zero prior config to run at all —
`detect_stack.py` never even instantiates `Config`, and `check_integrations.py`'s entire purpose
is reporting what's missing without gating on it. After this skill runs, hand off to
`seo-technical-audit` for the first real audit pass, or to `seo-maintain` for the full continuous
loop.
