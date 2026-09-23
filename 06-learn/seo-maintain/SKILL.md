---
name: seo-maintain
description: "Runs the scheduled whole-site SEO+GEO checkup: refreshes a crawl snapshot, diffs against the last run for regressions (noindex, broken links, disappeared pages, canonical changes, GSC click drops), ranks opportunities, and emits one prioritized punch-list naming the skill that fixes each item. Invoke on a cron/schedule or for 'status check' / 'what should I work on'. Not for one known problem area: ranking drops → seo-rank-tracking; keyword opportunities → seo-keyword-research; deep crawl diagnostics → seo-technical-audit."
---

# seo-maintain

The entry point for routine, ongoing SEO+GEO upkeep: a scheduled agent (or a human asking
"what should I work on?") runs one cycle to learn what changed and what is worth doing next.
Regressions are always ordered before opportunities — not losing what you already have
outranks incremental gains, because an unnoticed regression compounds while it sits
(red-flags.md §2, §4).

**This skill never applies fixes.** It detects, ranks, and dispatches by skill name — every
finding carries a `dispatch_skill`; see § Safe to auto-apply vs. human review.

## When to use this skill

- A scheduled/cron run ("do the daily/weekly SEO maintenance pass").
- "Status check", "what's changed", "what should I work on" — no named problem area.
- Right after a deploy, redesign, or CMS migration — exactly when accidental regressions
  (stray noindex, broken canonicals) get introduced (red-flags.md §4).
- **Not** for a known problem area: ranking drops → `seo-rank-tracking`; keyword
  opportunities → `seo-keyword-research`; deep crawl diagnostics → `seo-technical-audit`;
  Core Web Vitals → `seo-performance`. Use this skill to decide *which* of those to run.

## What it checks / does

One cycle runs `scripts/run_maintenance_cycle.py`:

1. **Fresh crawl** into the shared snapshot store (always crawls, never reuses). A
   robots-blocked crawl produces a loud error report saying why and exits 1 — never a
   silently-empty "all clear".
2. **Crawl-diff regressions** against the most recent *comparable* baseline (same site,
   same `max_pages`, neither truncated). No comparable baseline → the diff refuses into
   `not_checked.crawl_diff_regressions` instead of reporting coverage artifacts as
   regressions. `page_disappeared` is additionally suppressed (and surfaced in
   `not_checked`) when either crawl was truncated. Pages are keyed by folded identity, so
   /about vs /about/ vs www variants are one page.
3. **GSC click regressions** (when configured): two adjacent fully-paginated windows of
   `--gsc-days` each. If either window hits the row cap, only pages present in *both*
   windows are compared and a `note` says so. A drop must clear prior clicks >= 10 AND an
   absolute drop >= 5 AND a relative drop >= 50%; >= 75% with prior >= 30 raises severity
   to high. Never critical — click data alone cannot distinguish seasonality from breakage.
4. **Opportunities** ranked from the fresh crawl alone (impact tier, then count).
5. **Coverage notes** — everything this cycle could not check appears in `not_checked`
   with the env var or skill that unlocks it.

### Dispatch table

| Finding `type` | Section | Severity/Impact | `dispatch_skill` |
|---|---|---|---|
| `new_noindex` | regression | critical | `seo-technical-audit` |
| `status_code_regression` | regression | critical (5xx) / high | `seo-technical-audit` |
| `cross_domain_canonical` (genuinely different host only) | regression | critical | `seo-redirects` |
| `page_disappeared` | regression | high | `seo-internal-linking` |
| `new_redirect_on_previously_direct_page` | regression | high (cross-host) / medium | `seo-redirects` |
| `gsc_clicks_drop` | regression | high/medium — never critical | `seo-rank-tracking` |
| `fetch_error` | regression | medium | `seo-technical-audit`; `seo-redirects` when `error_type` is `too_many_redirects` (a genuine loop) |
| `canonical_removed` / `canonical_changed` | regression | medium | `seo-technical-audit` |
| `new_broken_internal_links` (targets >= 400 only) | regression | medium | `seo-technical-audit` |
| `missing_title_tag` / `missing_meta_description` / `missing_h1` / `multiple_h1` | opportunity | high/medium/medium/low | `seo-metadata` |
| `no_structured_data` / `invalid_json_ld` | opportunity | medium | `seo-structured-data` |
| `thin_content` | opportunity | medium (human review required) | `seo-content-optimize` |
| `hreflang_missing_reciprocal` | opportunity | medium | `seo-technical-audit` |
| `excessive_link_depth` (>4 clicks) | opportunity | low | `seo-internal-linking` |
| `images_missing_alt_text` / `missing_html_lang` | opportunity | low | `seo-technical-audit` |
| *(coverage note, every run — never a finding here)* orphan pages | `not_checked` | — | `seo-internal-linking` |
| *(coverage notes when keys absent)* CWV / JS-rendering diff / backlink+SERP data | `not_checked` | — | `seo-performance` / `geo-optimize` / `seo-backlinks`+`seo-rank-tracking` |

Orphan detection is structurally impossible from a link-following crawl (it cannot discover
unlinked pages by construction), so this skill never claims it: `not_checked.orphan_pages`
appears every run and dispatches `seo-internal-linking`, which builds a sitemap/GSC URL
universe instead.

Worked example: a cycle reports `new_noindex` on `/pricing` (critical) alongside
`missing_meta_description` on 12 blog posts (medium opportunity). Dispatch
`seo-technical-audit` first to confirm or deny that the noindex is accidental; only after
that is resolved (or explicitly deferred with a reason) dispatch `seo-metadata`.

## Running it

> All commands below run from the **target repo root** (the repo that contains the
> website). State and reports land in `<repo>/.seo-engine/` — running from anywhere
> else writes state to the wrong repo. Set `SKILL_DIR` to this skill's resolved absolute directory before running these commands
> (see common-setup.md); no host-specific variable is required.

```bash
python3 "${SKILL_DIR}/scripts/run_maintenance_cycle.py"

python3 "${SKILL_DIR}/scripts/run_maintenance_cycle.py" --max-pages 2000

python3 "${SKILL_DIR}/scripts/run_maintenance_cycle.py" --gsc-days 14

python3 "${SKILL_DIR}/scripts/run_maintenance_cycle.py" --ignore-robots
```

Flags: `--max-pages` (default 500), `--gsc-days` (default 28), `--ignore-robots`.
Requires `site_url` in `.seo-engine/config.yml` (written by `seo-setup`) or `SEO_SITE_URL`.

## Expected output

Written to `.seo-engine/reports/maintenance-<date>.json` and printed to stdout:

```jsonc
{
  "regressions": [
    { "type": "new_noindex", "severity": "critical", "url": "...", "detail": "...",
      "dispatch_skill": "seo-technical-audit", "human_review_required": true }
  ],
  "opportunities": [
    { "type": "missing_meta_description", "impact": "medium", "effort": "low",
      "count": 12, "sample_urls": ["..."], "dispatch_skill": "seo-metadata" }
  ],
  "summary": {
    "regressions_found": 4, "regressions_critical": 2, "opportunities_found": 9,
    "checked": {
      "crawl": { "robots_status": "fetched", "truncated": false,
                 "compared_against_previous": true, "previous_snapshot": "..." },
      "google_search_console": { "checked": true, "row_cap_hit": false }
    },
    "not_checked": { "orphan_pages": "...", "core_web_vitals": "..." }
  },
  "_report_path": ".seo-engine/reports/maintenance-<date>.json"
}
```

`regressions` is sorted critical → high → medium → low (crawl and GSC findings are merged
*before* sorting); `opportunities` by impact tier, then count.

## State files

| File (under `.seo-engine/`) | Role | Written by | Read by |
|---|---|---|---|
| `state/crawls/` (shared snapshot store) | produces this cycle's crawl; consumes the prior comparable snapshot as diff baseline | see [common-setup.md § Snapshot contract](../../shared/seo-references/common-setup.md) | this skill + any other |
| `reports/maintenance-<date>.json` | the prioritized punch-list | `run_maintenance_cycle.py` | calling agent |

## How to interpret results

- **Read `regressions` first, critical first.** A non-empty `regressions_critical` is the
  headline of any summary you give a human.
- **`human_review_required: true` is not optional** — the script deliberately did not
  resolve ambiguity (a new noindex might be an intentional retirement). Hand off to the
  named `dispatch_skill` and let its own review gate decide.
- **`compared_against_previous: false`** = first run or no comparable baseline
  (`not_checked.crawl_diff_regressions` gives the refusal reason). That is not a clean bill
  of health — run again next cycle with the same `--max-pages`.
- **`not_checked` is a coverage statement, not a failure list.** "Everything *checked* is
  fine" and "everything is fine" are different claims — read it before saying either.
  `orphan_pages` is always present by design; `page_disappeared` appears there when the
  crawl was truncated.
- **`gsc_clicks_drop`** may be seasonality or a SERP-feature change — diagnose via
  `seo-rank-tracking` before acting. A capped GSC window narrows the comparison to pages
  present in both windows (the `note` says how many were excluded).

## Safe to auto-apply vs. human review

This skill applies nothing, ever: read-only against the live site, write-only to
`.seo-engine/`. Findings pre-classify the *next* skill's caution level:

- **Hard stop (human sign-off before any fix):** `new_noindex`, `cross_domain_canonical`,
  `new_redirect_on_previously_direct_page`, `thin_content`, `gsc_clicks_drop` — each is
  ambiguous in a way only human/business context resolves.
- **Mechanical gaps** the dispatched skill may fix under its own gates: missing
  titles/descriptions/H1s/alt text, invalid JSON-LD, missing `html lang`.

## Guardrails

- Detect-and-dispatch only; no same-run fixes, no publishing-volume recommendations.
- No thin-content padding — the fix must add genuine value, never filler to clear a
  word count (seo-playbook.md §1, red-flags.md §1).
- No time-since-edit "staleness" check, by design — cosmetic freshness signals are the
  anti-pattern (seo-playbook.md §7, red-flags.md §3); evidence-based staleness belongs to
  `seo-content-optimize`.
- `no_structured_data` is justified by rich-result eligibility only, never as an
  AI-citation lever — geo-playbook.md §3.
- Cross-domain canonical = escalate, never auto-correct (red-flags.md §4); www/apex/scheme
  variants of the same site never trigger it.

## References

- [common-setup.md](../../shared/seo-references/common-setup.md) — paths, config resolution, the
  snapshot contract, degradation philosophy.
- [seo-playbook.md](../../shared/seo-references/seo-playbook.md) §2 (technical foundation), §5
  (canonicalization), §6 (link depth), §7 (freshness — deliberately not checked here), §8
  (structured data's real value).
- [red-flags.md](../../shared/seo-references/red-flags.md) §2 (why regressions compound), §4 (the
  technical mistakes this diff is built to catch).
- [geo-playbook.md](../../shared/seo-references/geo-playbook.md) §3 — structured data is not a GEO
  lever; AI-crawler access and citation tracking live in `geo-optimize` / `geo-monitor`.

## Graceful degradation

Generic philosophy: [common-setup.md § Graceful degradation](../../shared/seo-references/common-setup.md).
Skill-specific unlocks:

- Zero API keys: the crawl-diff regressions and opportunity ranking still run in full.
- `GOOGLE_APPLICATION_CREDENTIALS` or `GSC_SERVICE_ACCOUNT_JSON` unlocks the click-drop check.
- Missing `GOOGLE_PSI_API_KEY` / `FIRECRAWL_API_KEY` / Ahrefs / DataForSEO keys appear as
  named `not_checked` entries; geo-optimize's `check_js_visibility.py` is the free
  alternative to the Firecrawl rendered diff.
