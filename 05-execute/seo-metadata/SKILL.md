---
name: seo-metadata
description: "Audits on-page metadata (title, meta description, Open Graph, Twitter Card) from a crawl snapshot, then guides source-template fixes for missing, duplicate, mismatched, or badly-sized values. Invoke to improve SERP click-through, fix duplicate titles/descriptions, add or repair social share previews, or as follow-up when seo-maintain/seo-technical-audit surfaces metadata findings. Not for structured data/JSON-LD (use seo-structured-data) or crawlability/canonical issues (use seo-technical-audit)."
---

# seo-metadata

Audits the on-page metadata layer: `<title>`, meta description, and Open Graph / Twitter Card
tags. One of the few skills expected to guide **source-code-level fixes**, not just report
findings — locating the real template source and writing real page-specific copy matters more
here than in a pure-audit skill.

## When to use this skill

- A user asks to improve titles/descriptions for SEO or social sharing.
- `seo-technical-audit` or `seo-maintain` surfaces metadata problems as part of a broader crawl.
- Recurring maintenance — metadata drifts as pages get added/edited/cloned (e.g. a new page cloned
  from a template that forgot to change the title).
- Before/after a CMS migration or redesign, a common casualty ([red-flags.md §4](../../shared/seo-references/red-flags.md)).
- **Not** for structured data / JSON-LD — use `seo-structured-data`. **Not** for crawlability,
  canonical, or noindex issues — use `seo-technical-audit`.

## What it checks / does

`scripts/audit_metadata.py`:

1. **Crawl** via the shared snapshot store — reuses any <24h snapshot for the configured site, or
   crawls fresh (`--force-recrawl` skips reuse and always crawls fresh; `--max-pages` caps a fresh
   crawl). There is no snapshot-path override flag — this script only reads from the shared store.
2. Pages are deduped by `canonical_key` of the **final destination URL** before any check — /about,
   /about/, and a www alias fold to one page, so a page is never flagged as a duplicate of itself.
3. Indexability honors both the meta robots tag AND the `X-Robots-Tag` header
   (`pagerules.is_indexable_html`) — only HTTP 200 HTML, not noindex by either signal, is audited.
4. Flags, per page:
   - **missing title** (high) / **missing meta description** (medium) — Google auto-generates a
     replacement you don't control.
   - **title too long** (>60 chars, medium) / **too short** (<30, low) — SERP truncation happens
     by rendered pixel width, so treat 60 as a heuristic risk threshold, not a hard cutoff.
   - **description too long** (>155, low) / **too short** (<70, low).
   - **missing og:title/og:description** (low) / **missing og:image** (medium — the most visible
     failure when a page is shared).
   - **missing/empty twitter:card** (low, NEW) — without it, X/Twitter falls back to OG tags where
     present, or renders a bare link.
   - **title/H1 mismatch** (medium) — a Jaccard token-overlap heuristic on stopword-stripped
     tokens. A signal to investigate, not proof — some legitimate pages have a marketing-style
     title and a more literal H1; read both before rewriting either.
   - **missing_h1** (low) — a title with no H1 at all; also blocks the mismatch check.
5. **Duplicates**: title and meta-description values shared across 2+ distinct page identities.
   **One finding per duplicated value**, carrying `affected_urls` (every raw URL sharing it) —
   not one finding per page.

## Running it

> All commands below run from the **target repo root** (the repo that contains the
> website). State and reports land in `<repo>/.seo-engine/` — running from anywhere
> else writes state to the wrong repo. Set `SKILL_DIR` to this skill's resolved absolute directory before running these commands
> (see common-setup.md); no host-specific variable is required.

```bash
python3 "${SKILL_DIR}/scripts/audit_metadata.py"

python3 "${SKILL_DIR}/scripts/audit_metadata.py" --max-pages 300

python3 "${SKILL_DIR}/scripts/audit_metadata.py" --force-recrawl
```

Flags: `--max-pages` (default 500), `--force-recrawl`. Requires `site_url` in
`.seo-engine/config.yml` (written by `seo-setup`) or `SEO_SITE_URL`. No paid API key unlocks
anything further — the crawler is unauthenticated and free.

## Expected output

Written to `.seo-engine/reports/metadata-audit-<date>.json` and printed to stdout:

```jsonc
{
  "pages_analyzed": 142,
  "pages_with_issues": 37,
  "total_issues": 61,
  "issue_counts_by_type": { "title_h1_mismatch": 12, "missing_og_image": 9, "duplicate_title": 8 },
  "pages": [
    { "url": "...", "severity": "high", "issue_count": 3,
      "issues": [ { "severity": "high", "problem": "duplicate_title", "affected_urls": ["...", "..."] } ] }
  ],
  "crawl": { "producer_skill": "...", "pages_crawled": 142, "truncated": false, "robots_status": "fetched" },
  "freshly_crawled": false,
  "empty_reason": null,
  "report_file": ".seo-engine/reports/metadata-audit-<date>.json"
}
```

`pages` is pre-sorted: highest severity first, then by issue count within a severity tier.
`empty_reason` is present (and non-null) only when `pages_analyzed == 0` — distinguishes a
robots-blocked crawl from a genuinely empty indexable set; absence of issues elsewhere is never
silently equated with a clean audit.

## State files

| File (under `.seo-engine/`) | Role | Written by | Read by |
|---|---|---|---|
| `state/crawls/` (shared snapshot store) | consumes/produces this run's crawl | see [common-setup.md § Snapshot contract](../../shared/seo-references/common-setup.md) | this skill + any other |
| `reports/metadata-audit-<date>.json` | dated audit report | `audit_metadata.py` | calling agent |

No per-skill cross-run state file is written by this script.

## How to interpret results

**This script never edits anything.** It only reads a crawl snapshot and reports. All fixes are
made by the calling agent, at the source-code level.

### Step 1 — locate the actual template source, not rendered HTML

Editing a `dist/`, `.next/`, `build/`, or `public/` directory accomplishes nothing — it regenerates
on the next build.

| Stack | Where to look |
|---|---|
| **Next.js (App Router)** | `export const metadata` / `generateMetadata()` in the route's `page.tsx`/`layout.tsx`, or a shared helper it calls. |
| **Next.js (Pages Router)** | `next/head` in the page component, or `_document.tsx` for site-wide defaults. |
| **Astro** | Frontmatter of the `.astro` page, or props flowing into a shared `<Layout>`/`<SEO>` component. |
| **Hugo** | Front matter consumed by a `<head>` partial in `layouts/partials/`. |
| **Nuxt** | `useHead()` / `useSeoMeta()` / `definePageMeta()`, or a global default in `nuxt.config.ts`. |
| **Gatsby** | `<Seo>`/`<SEO>` component reading page/frontmatter props. |
| **Plain HTML** | The literal `<head>` block — confirm it isn't generated by a build step first. |
| **CMS-driven** | Metadata may live in CMS content fields, not the repo — say so explicitly rather than inventing a template file. |

If a shared layout sets a default several flagged pages inherit unchanged (usually the root cause
of duplicates), fix the per-page override, not the shared default.

### Step 2 — write real, page-specific copy

Justified by this page's actual content — read the page/frontmatter before writing its metadata.
Never use a structurally-identical fill-in-the-blank template across many pages (scaled-content /
doorway pattern — [red-flags.md §1](../../shared/seo-references/red-flags.md)); a shared structural pattern
is fine, a shared sentence with one word swapped is not. No keyword-density targets
([seo-playbook.md §9](../../shared/seo-references/seo-playbook.md)). Keep within the checked length bounds
as a starting constraint, never truncate a real detail to hit a number. `og:image` must point at
an image that actually represents the page — flag a missing page-specific image as a content gap
rather than inventing a placeholder.

## Safe to auto-apply vs. human review

- **Safe to fix directly:** adding a missing `og:title`/`og:description` mirroring an already-good
  title/description; shortening an over-length title by removing genuinely redundant words;
  writing distinct copy for an exact-duplicate pair from each page's own content; adding a missing
  `og:image` when a page-specific image already exists in source/CMS content.
- **Must be flagged for human review:** any fix requiring a factual claim not verifiable from the
  page's own content; a title/H1 mismatch that might be intentional; metadata in a CMS the agent
  lacks write access to; bulk rewrites across many pages without a differentiation check — write
  each one individually from that page's content, never from one prompt template producing
  near-identical output; a missing `og:image` with no page-specific image anywhere in the page's
  content (sourcing one is a human/design decision).

## Guardrails

Do not justify any metadata fix as an AI-citation (GEO) lever — OG tags and title/meta description
have no evidenced connection to whether ChatGPT, Perplexity, or Google AI Overviews cite a page
([geo-playbook.md §3](../../shared/seo-references/geo-playbook.md); [red-flags.md §5](../../shared/seo-references/red-flags.md)).
Redirect GEO requests to `geo-optimize`/`geo-monitor`; schema.org/JSON-LD authorship belongs to
`seo-structured-data`, not here.

## References

- [common-setup.md](../../shared/seo-references/common-setup.md) — paths, config resolution, snapshot
  contract, degradation philosophy.
- [seo-playbook.md](../../shared/seo-references/seo-playbook.md) §1 (people-first — the test every rewritten
  title/description must pass), §9 (no keyword-density targets).
- [red-flags.md](../../shared/seo-references/red-flags.md) §1 (scaled content / doorway pages), §4
  (accidental noindex and post-migration regressions — why noindex pages are filtered out here).
- [geo-playbook.md](../../shared/seo-references/geo-playbook.md) §3 — no proven AI-citation benefit for
  structured/OG data; the same anti-hype discipline applies to this skill's fixes.

## Graceful degradation

Generic philosophy: [common-setup.md § Graceful degradation](../../shared/seo-references/common-setup.md).
No API keys are used by this skill at all — the crawler is unauthenticated and free, and the
audit logic is pure local computation over the crawl snapshot.
