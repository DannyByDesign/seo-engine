---
name: seo-technical-audit
description: "Crawl-based technical SEO health audit: HTTP status codes, accidental noindex, canonical correctness (cross-domain hijack, GSC declared-vs-selected drift), sitemap completeness, broken internal links, and JS-rendering gaps; reports redirect chains/loops as symptoms. Invoke as the first audit on a new site, after any deploy/redesign/migration, or when indexing or traffic looks off and the cause is unknown. To trace redirects to config rules or validate a migration map, use seo-redirects; for the recurring prioritized checkup, use seo-maintain."
---

# seo-technical-audit

The foundational, non-glamorous layer — per [seo-playbook.md §2](../../shared/seo-references/seo-playbook.md),
content that cannot be crawled cannot rank, by any engine, human-facing or AI-facing. Treat any
finding here as higher priority than content/keyword/GEO work: technical breakage silently caps
the ceiling of everything else.

## When to use this skill

- Starting work on a site for the first time (baseline audit).
- After any deploy, redesign, CMS migration, or hosting/CDN change — the most common source of
  accidental noindex, broken canonicals, and redirect regressions ([red-flags.md §4](../../shared/seo-references/red-flags.md)).
- Indexed-page count or organic traffic drops with no obvious content-quality explanation.
- Before trusting `sitemap.xml` for indexing purposes.
- **Not** for tracing a redirect finding to its governing config rule or validating a pre-migration
  redirect map — use `seo-redirects`. **Not** for the recurring prioritized whole-site checkup —
  use `seo-maintain`.

## What it checks / does

One run of `scripts/run_audit.py`:

1. **Crawl** via the shared snapshot store (fresh, or `--skip-crawl` reuses any <24h snapshot from
   any skill). Robots-blocked crawl (`all_blocked`) exits 1 with a loud error report, not an empty
   "all clear".
2. **Accidental noindex** — an evidence ladder, not a bare "has inbound links" test (every crawled
   page has inbound links by construction). A noindex page is a finding only when corroborated:
   GSC impressions in the last 90 days → `accidental_noindex` (high); sitemap-listed only →
   `noindex_sitemap_conflict` (medium). Known-intentional paths (`/login`, `/cart`, `/admin`,
   `/checkout`, `/search`, `/tag/`, ...) are suppressed. Uncorroborated noindex pages are counted
   in `noindex_pages_observed`, not reported as findings.
3. **Cross-domain canonicals** — genuinely different host only; www/apex/scheme variants are the
   same site and never trigger this. Security-shaped, never auto-fixed.
4. **Broken internal links** — link targets serving >= 400 only. Fetch errors (network blips) are
   listed separately as `linked_page_fetch_error` (low, possibly transient), never as broken links.
5. **Redirects** via the shared taxonomy in `lib/redirect_analysis` (the same module `seo-redirects`
   uses, so the two skills never disagree): `redirect_loop` (critical, TooManyRedirects-based),
   `redirect_chain` (medium/high), `canonicalization_chain` (low, pure scheme/www normalization),
   `link_to_redirect` (low). Single-hop normalizing redirects are a count
   (`normalizing_redirects_observed`), never a finding.
6. **Sitemap diff** — identity-folded on both sides (scheme/www/slash variants fold to one page).
   Discovery via robots `Sitemap:` lines plus 3 default paths (`sitemaps_read` in output).
7. **Optional, `FIRECRAWL_API_KEY`** — samples indexable HTML pages and diffs raw vs. rendered
   content for JS-dependent gaps (`js_rendering_gap`, medium). The free heuristic alternative
   (no API key) is geo-optimize's `check_js_visibility.py` — [geo-playbook.md §11](../../shared/seo-references/geo-playbook.md).
8. **Optional, Google Search Console configured** — `canonical_gsc_disagreement` (high), emitted
   ONLY when Google's selected canonical disagrees with the declared one; agreements are recorded
   in `confirmed`, not inflated into findings. Sample = cross-domain findings plus pages whose
   declared canonical differs from their own URL.

## Running it

> All commands below run from the **target repo root** (the repo that contains the
> website). State and reports land in `<repo>/.seo-engine/` — running from anywhere
> else writes state to the wrong repo. `${CLAUDE_SKILL_DIR}` is set by Claude Code to
> this skill's directory and works for both the symlink and plugin install.

```bash
# Full audit, default 500-page crawl, default samples of 5 for the optional checks
python3 "${CLAUDE_SKILL_DIR}/scripts/run_audit.py"

# Smaller crawl, larger JS-rendering sample
python3 "${CLAUDE_SKILL_DIR}/scripts/run_audit.py" --max-pages 100 --sample-js 10

# Reuse any <24h shared snapshot instead of crawling fresh
python3 "${CLAUDE_SKILL_DIR}/scripts/run_audit.py" --skip-crawl

# ONLY for your own localhost/staging build that blocks all bots
python3 "${CLAUDE_SKILL_DIR}/scripts/run_audit.py" --ignore-robots
```

Flags: `--max-pages` (default 500), `--delay`, `--sample-js` (default 5), `--sample-canonical`
(default 5), `--ignore-robots`, `--skip-crawl`. Requires `site_url` in `.seo-engine/config.yml`
(written by `seo-setup`) or `SEO_SITE_URL`.

## Expected output

Written to `.seo-engine/reports/technical-audit-<date>.json` and printed to stdout:

```jsonc
{
  "severity_counts": { "critical": 1, "high": 2, "medium": 5 },
  "noindex_pages_observed": 4,
  "normalizing_redirects_observed": 2,
  "sitemap": { "checked": true, "missing_from_sitemap_count": 2, "should_not_be_in_sitemap_count": 1 },
  "js_rendering_check": { "checked": false, "reason": "FIRECRAWL_API_KEY not set — ..." },
  "canonical_gsc_crosscheck": { "checked": true, "sample_size_actual": 3, "confirmed": [], "errors": [] },
  "findings": [
    { "type": "accidental_noindex", "severity": "high", "url": "...", "evidence": "...",
      "auto_fixable": false, "human_review_reason": "..." }
  ],
  "_report_path": ".seo-engine/reports/technical-audit-<date>.json"
}
```

`findings` is pre-sorted critical -> high -> medium -> low.

## State files

| File (under `.seo-engine/`) | Role | Written by | Read by |
|---|---|---|---|
| `state/crawls/` (shared snapshot store) | consumes/produces this run's crawl | see [common-setup.md § Snapshot contract](../../shared/seo-references/common-setup.md) | this skill + any other |
| `reports/technical-audit-<date>.json` | dated audit report | `run_audit.py` | calling agent |

No per-skill state file is written for cross-run diffing — `seo-maintain` runs its own independent
crawl-diff, not a consumer of this report.

## How to interpret results

- **`severity_counts.critical` or `.high` > 0** — stop and address before content/keyword/GEO work.
- **`noindex_pages_observed`** vs actual noindex findings: the gap is pages this audit judged
  probably intentional (no corroborating evidence) — not a clean bill of health, just unproven.
- **`sitemap.missing_from_sitemap`** — safe to add once confirmed genuinely intended to be
  indexable. **`should_not_be_in_sitemap`** — wastes crawl budget; confirm the underlying cause
  (404, noindex, canonicalized away) is intentional before removing.
- **`js_rendering_gap` findings** — a gap ratio near 1.0 across the sample is a strong SSR/SSG
  signal, not automatic proof (some frameworks handle this correctly and the sample may have hit
  an edge case).
- **`canonical_gsc_disagreement`** — Google is treating a different URL as canonical than declared;
  a legitimate integrity check ([seo-playbook.md §5](../../shared/seo-references/seo-playbook.md)), not an
  automatic bug. Cross-reference before changing anything.
- If `js_rendering_check.checked` or `canonical_gsc_crosscheck.checked` is `false`, read `reason` —
  it names the exact env var that unlocks it. The rest of the audit still ran in full.

## Safe to auto-apply vs. human review

**Every finding has `"auto_fixable": false`.** This script is read-only diagnosis; the calling
agent decides what to change in the target repo.

- **Hard stop (human sign-off):** `cross_domain_canonical` — security-shaped, escalate, never
  auto-correct ([red-flags.md §4](../../shared/seo-references/red-flags.md)). `accidental_noindex` /
  `noindex_sitemap_conflict` — removing noindex could itself be wrong if intentional; flag, don't
  guess. Any sitemap change until the underlying cause is understood.
- **Reasonable to propose as a reviewable diff:** adding a confirmed-indexable URL to sitemap
  generation logic; removing a confirmed-404/noindexed/duplicate URL from it; fixing an internal
  `<a href>` that points at a known-renamed URL when the correct destination is unambiguous.

## Guardrails

- Never treat "publish more pages" or "increase crawl frequency" as a fix for any finding here.
- Never recommend `llms.txt` or schema.org markup in response to a finding in this audit — this
  skill's scope is crawlability, not citation strategy ([geo-playbook.md §§1, 3](../../shared/seo-references/geo-playbook.md)).
- Never "fix" a JS-rendering gap by serving different content to specific crawlers — that is
  cloaking ([red-flags.md §1](../../shared/seo-references/red-flags.md)); the fix is SSR/SSG/prerendering
  serving the same content to everyone.

## References

- [common-setup.md](../../shared/seo-references/common-setup.md) — paths, config resolution, snapshot
  contract, degradation philosophy.
- [seo-playbook.md](../../shared/seo-references/seo-playbook.md) §2 (technical foundation), §5
  (canonicalization and the GSC cross-check rationale).
- [red-flags.md](../../shared/seo-references/red-flags.md) §4 — the authoritative source for every
  escalate-vs-auto-fix decision in this skill.
- [geo-playbook.md](../../shared/seo-references/geo-playbook.md) §3 (no schema.org citation benefit), §11
  (AI crawlers don't render JS — the free `check_js_visibility.py` alternative).
- [api-reference.md](../../shared/seo-references/api-reference.md) — Firecrawl and Google Search Console
  auth/quota notes for the two optional integrations.

## Graceful degradation

Generic philosophy: [common-setup.md § Graceful degradation](../../shared/seo-references/common-setup.md).
Skill-specific unlocks:

- No API keys required for the core audit (crawl, sitemap diff, noindex/canonical/redirect/
  broken-link analysis) — only `site_url`.
- `FIRECRAWL_API_KEY` unlocks the rendered-diff JS check; without it use geo-optimize's free
  `check_js_visibility.py`.
- `GOOGLE_APPLICATION_CREDENTIALS` / `GSC_SERVICE_ACCOUNT_JSON` unlocks the GSC noindex-evidence
  tier and the canonical cross-check.
- If `sitemap.xml` doesn't exist or fails to parse, `sitemap.checked` is `false` with a `reason` —
  the rest of the audit still runs and reports normally.
