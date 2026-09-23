---
name: seo-redirects
description: "Audits redirects at the config-source level: multi-hop chains, loops, redirect-to-redirect targets, and drift between the framework's declared redirect config (next.config.js, vercel.json, _redirects, .htaccess, nginx) and live behavior; validates a pre-migration redirect map (--old-urls-file) as a launch gate. Invoke before/after URL restructures or domain moves, or when a redirect chain/loop finding needs its governing config rule located. For broad crawl health checks that only surface redirect symptoms, use seo-technical-audit."
---

# seo-redirects

Catches two distinct problems: **symptom-level breakage** (chains, loops, redirect-to-redirect —
visible from crawl data alone) and **source-level drift** (a config-declared rule the live site
doesn't honor, or vice versa — visible only by reading the actual config file). The second half is
why this skill is separate from `seo-technical-audit`, which does a basic chain/loop pass as part
of its broader crawl but never reads the config source.

**Treat missing pre-migration redirect coverage as a launch blocker, not a nice-to-have** —
lost backlink/ranking signal from an unredirected URL is often unrecoverable
([red-flags.md §2](../../shared/seo-references/red-flags.md)).

## When to use this skill

- Before a site restructure, URL-scheme change, CMS migration, or domain move — run the
  migration-safety check (`--old-urls-file`) against every URL that will stop resolving under its
  current path.
- After `seo-technical-audit` or `seo-maintain` surfaces a `redirect_chain` / `redirect_loop`
  finding and you need the full hop sequence plus the config rule responsible.
- Periodically — redirect rules accumulate over a site's life and rarely get pruned, so chains
  silently lengthen as old rules point at other old rules.
- A page that used to rank stops showing up and the URL structure changed recently.
- **Not** for a broad crawl health pass that only needs redirect symptoms alongside noindex/
  canonical/broken-link findings — use `seo-technical-audit`.

## What it checks / does

`scripts/audit_redirects.py`:

1. **Crawl** — via the shared snapshot store; `--skip-crawl` reuses any <24h snapshot (from any
   skill, including `seo-technical-audit`/`seo-metadata`); `--snapshot PATH` analyzes a specific
   file read-only (implies `--skip-crawl`, never overwrites it); default is a fresh crawl.
2. **Chain/loop taxonomy** via the shared `lib/redirect_analysis` module (identical to
   `seo-technical-audit`'s, so the two skills can never disagree about what a "loop" is):
   `redirect_loop` (critical — TooManyRedirects-based, the only launch-blocker-eligible type),
   `redirect_chain` (medium at 2 hops, high at 3+), `canonicalization_chain` (low — multi-hop but
   pure http->https->www normalization), `link_to_redirect` (an internal link points at a URL that
   itself redirects). Single-hop slash/www-normalizing redirects are a count
   (`normalizing_redirects_observed`), never a finding.
3. **Optional, `--redirect-config PATH`** — parses the framework's declared rules and cross-checks
   against what the crawl observed: `declared_rule_not_observed` (medium — source path never
   crawled, may just be unlinked), `declared_rule_not_honored` (high — source returned 200, no
   redirect active), `declared_rule_destination_mismatch` (high — redirects, but not where
   declared), `live_redirect_not_declared_in_config` (low — observed live, no matching rule; could
   be platform/CDN-level). See "Locating the real redirect source" below.
4. **Optional, `--old-urls-file PATH`** (one URL per line) — migration-safety: every listed URL
   must either still resolve 200 or have coverage from the live crawl OR the declared config
   (config coverage counts even if the crawl never reached that URL). Uncovered ->
   `missing_migration_redirect` (critical), sets top-level `launch_blocker: true`. A URL whose
   redirect loops is *worse* than no coverage — surfaced with `reason: redirect_loops`.

### Locating the real redirect source

| Framework / platform | Where redirects live |
|---|---|
| **Next.js** | `next.config.js/ts/.mjs/.cjs` — `async redirects()` returning `{source, destination, permanent}` objects. Parsed via bracket-depth array extraction (safe against nested `has:[...]` matchers). `middleware.ts` programmatic redirects are NOT parsed — flag separately if found. |
| **Vercel** | `vercel.json` `redirects` array, or a plain-text `_redirects` file. Absent `permanent` defaults to 307 (Vercel's documented default) rather than `statusCode`. |
| **Netlify** | `_redirects` file. `netlify.toml` `[[redirects]]` blocks are NOT parsed — note as a gap, don't assume zero rules. |
| **Apache** | `.htaccess` — `Redirect`/`RedirectMatch` parsed; `RewriteRule` is NOT (regex/flag complexity) and surfaces as a `parse_warnings` entry instead of being silently dropped. |
| **Nginx** | `return <status> <url>;` and `rewrite ... permanent\|redirect;` inside `location` blocks. |
| **CMS-level redirect manager** | Often no file in the repo at all — query the CMS's own redirect table/API and treat its output as the config input, or note the gap explicitly. |

If multiple candidate files exist, verify which one the hosting platform actually honors —
running `--redirect-config` against a non-live file produces misleading `declared_rule_not_honored`
findings that are really just "wrong file checked."

## Running it

> All commands below run from the **target repo root** (the repo that contains the
> website). State and reports land in `<repo>/.seo-engine/` — running from anywhere
> else writes state to the wrong repo. Set `SKILL_DIR` to this skill's resolved absolute directory before running these commands
> (see common-setup.md); no host-specific variable is required.

```bash
python3 "${SKILL_DIR}/scripts/audit_redirects.py"

python3 "${SKILL_DIR}/scripts/audit_redirects.py" --skip-crawl

python3 "${SKILL_DIR}/scripts/audit_redirects.py" --skip-crawl \
  --redirect-config /path/to/target-repo/next.config.js

python3 "${SKILL_DIR}/scripts/audit_redirects.py" --skip-crawl \
  --redirect-config /path/to/target-repo/vercel.json \
  --old-urls-file /path/to/old-urls.txt

python3 "${SKILL_DIR}/scripts/audit_redirects.py" --snapshot .seo-engine/state/crawls/crawl-<UTC-stamp>.jsonl
```

Flags: `--max-pages` (default 500), `--delay`, `--ignore-robots`, `--skip-crawl`, `--snapshot PATH`,
`--redirect-config PATH`, `--old-urls-file PATH`. Requires `site_url` in `.seo-engine/config.yml`
or `SEO_SITE_URL`. No paid API key unlocks anything further — the crawler is free and config
parsing is local/offline.

## Expected output

Written to `.seo-engine/reports/redirects-audit-<date>.json` and printed to stdout:

```jsonc
{
  "severity_counts": { "critical": 1, "medium": 3, "low": 2 },
  "redirect_loops": { "count": 1, "findings": [ { "type": "redirect_loop", "cycle": ["...", "..."] } ] },
  "redirect_chains": { "count": 2, "findings": [ { "hop_sequence": ["...", "...", "..."] } ] },
  "canonicalization_chains": { "count": 0, "findings": [] },
  "links_to_redirects": { "count": 1, "findings": [] },
  "normalizing_redirects_observed": 5,
  "config_crosscheck": {
    "checked": true, "config_format": "nextjs", "rules_found_in_config": 12,
    "parse_warnings": [],
    "crosscheck": { "confirmed_count": 10, "mismatch_count": 2, "mismatches": [], "undeclared_live_redirects": [] }
  },
  "migration_safety": { "checked": true, "old_url_count": 40, "missing_count": 2, "missing": [], "launch_blocker": true },
  "launch_blocker": true,
  "findings": [ "... pre-sorted critical -> high -> medium -> low ..." ]
}
```

## State files

| File (under `.seo-engine/`) | Role | Written by | Read by |
|---|---|---|---|
| `state/crawls/` (shared snapshot store) | consumes/produces this run's crawl | see [common-setup.md § Snapshot contract](../../shared/seo-references/common-setup.md) | this skill + any other |
| `reports/redirects-audit-<date>.json` | dated audit report | `audit_redirects.py` | calling agent |

No per-skill cross-run state file is written by this script.

## How to interpret results

- **`launch_blocker: true`** (set by any real `redirect_loop` OR `migration_safety.missing_count`
  > 0) — stop and resolve before shipping a migration or restructure. Chain hygiene alone never
  sets this flag.
- **`redirect_loop`** — always critical; `cycle` shows exactly which URLs form it.
- **`redirect_chain`** — not urgent in isolation, but avoidable technical debt
  ([seo-playbook.md §2](../../shared/seo-references/seo-playbook.md)); prioritize high-traffic URLs first.
- **`config_crosscheck.mismatches`** — `declared_rule_not_honored` /
  `declared_rule_destination_mismatch` may mean the wrong config file was checked, or rule ordering
  intercepts the same path first — verify deployment state before assuming the config is wrong.
- **`undeclared_live_redirects`** — low severity by default; frequently a benign platform/CDN-level
  redirect. Escalate only if it lands somewhere unexpected.
- **`parse_warnings`** — rules the parser could not confidently extract (most commonly Apache
  `RewriteRule`). These are coverage gaps, not confirmed-clean — read before concluding config
  coverage is complete.
- **`migration_safety.missing`** — each entry needs either a new redirect rule before launch, or
  confirmation the URL never existed/had no backlinks (verify against GSC/Ahrefs via
  `seo-technical-audit`/`seo-backlinks`, don't take the old-URLs list at face value).

## Safe to auto-apply vs. human review

**This script is read-only; every finding carries `"auto_fixable": false`.**

- **Hard stop (human sign-off):** any change to a redirect-config file or CMS redirect table —
  the correct destination encodes a business decision this script cannot infer. Resolving a
  `redirect_loop` by picking which cycle member to delete/repoint. Any
  `missing_migration_redirect` — a human who owns the migration plan chooses the target, never an
  invented one. A cross-domain redirect destination — same suspicion as a cross-domain canonical
  ([red-flags.md §4](../../shared/seo-references/red-flags.md)), escalate rather than auto-correct.
- **Reasonable to propose as a reviewable diff:** collapsing a confirmed multi-rule chain into one
  rule at the confirmed-stable final destination; adding a single-hop rule for a
  `missing_migration_redirect` once a human has specified the destination; removing a
  long-standing `declared_rule_not_observed` rule independently confirmed to have no remaining
  external references (GSC/backlink data) — "not observed by this crawl" alone is not proof.

## Guardrails

- Never consolidate content as a side effect of redirect cleanup — that's a `seo-content-optimize`
  decision, not a redirect-hygiene one.
- Never justify a redirect fix as a citation lever — neither `llms.txt` nor schema.org is proven
  ([geo-playbook.md §§1, 3](../../shared/seo-references/geo-playbook.md)) and both are out of scope here.
- Never use IndexNow submission volume as a substitute for actually fixing the redirect map
  ([red-flags.md §4](../../shared/seo-references/red-flags.md)) — Google doesn't participate in IndexNow at all.

## References

- [common-setup.md](../../shared/seo-references/common-setup.md) — paths, config resolution, snapshot
  contract, degradation philosophy.
- [red-flags.md](../../shared/seo-references/red-flags.md) §4 (redirect chains/loops as a named failure
  mode; cross-domain-as-security-incident reasoning) and §2 (migration coverage is all-or-nothing).
- [seo-playbook.md](../../shared/seo-references/seo-playbook.md) §2 (why chains/loops matter at all), §5
  (the canonical-loop reasoning this skill's redirect-loop detection mirrors).
- [geo-playbook.md](../../shared/seo-references/geo-playbook.md) §§1, 3 — redirect correctness is a
  crawlability/link-equity concern, never a GEO lever.

## Graceful degradation

Generic philosophy: [common-setup.md § Graceful degradation](../../shared/seo-references/common-setup.md).
Skill-specific unlocks:

- The core chain/loop/redirect-to-redirect audit needs only `site_url` — no API key, ever.
- `--redirect-config` and `--old-urls-file` are optional flags. Without either,
  `config_crosscheck.checked` / `migration_safety.checked` is `false` with a `reason` — the rest
  of the audit still runs and reports normally.
- An unrecognized `--redirect-config` format reports `checked: false` with the list of supported
  formats — never crashes or treats an unrecognized file as "zero rules configured."
