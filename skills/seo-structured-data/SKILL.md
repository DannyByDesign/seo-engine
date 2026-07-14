---
name: seo-structured-data
description: Validates and helps author JSON-LD structured data (Article/BlogPosting, Product, Organization, FAQPage, HowTo, BreadcrumbList, LocalBusiness, Recipe, VideoObject, Person, WebSite) for rich-result eligibility and crawler comprehension, with error/warning/info severity tiers and a CI-safe exit code. Invoke when a page lacks schema its type warrants, when existing JSON-LD fails validation, when building a template for a recognized type, or in CI/periodic audits. Do NOT invoke believing it improves AI/LLM citation — see the caveat below.
---

# seo-structured-data

**Traditional-Search tool, not a GEO tactic.** Real, Google-documented value here is rich-result
eligibility and crawler entity comprehension (seo-playbook.md §8) — never justify or market this
work internally as "improves AI citation." The best controlled test available (geo-playbook.md
§3) found no reliable ChatGPT/AI Mode benefit and a **significant decrease** on Google AI
Overviews. Do the work for its real reasons; correct that expectation if someone asks for it for
the wrong one.

## When to use this skill

- A technical-SEO audit (`seo-technical-audit` or `seo-maintain`) surfaces structured-data errors
  or gaps.
- Building or editing a template for a recognized content type (blog post, product page, FAQ
  page, local-business location, how-to, video, author bio, homepage) and need to add/update JSON-LD.
- Existing JSON-LD is failing validation — often after a CMS field rename or template refactor.
- Periodic maintenance / CI pass to catch drift (schema correct at launch, broken silently since).

## What it checks / does

`scripts/validate_schema.py` wraps a shared validator that extracts JSON-LD via `extruct` and
checks each node's `@type` against a required/recommended property table, with three severity
tiers:

- **`error`** — a Google-*required* property is missing or empty (blocks the exit code).
- **`warning`** — a Google-*recommended* property is missing or empty (blocks the exit code only
  with `--strict`).
- **`info`** — advisory, not a defect: currently fires only for `FAQPage`/`HowTo`, whose rich
  -result visual treatment Google retired (the markup is still valid and worth having).

A node with no `@type` at all, or JSON-LD that fails to parse (`"Malformed JSON-LD"` — usually an
unescaped quote or template-interpolation bug), is always an `error`.

It also emits `missing_schema_suggestion` on pages with **zero** JSON-LD nodes where the content
type is an obvious fit, inferred conservatively from URL path first, then H1/title, then a
homepage → `Organization` fallback — carrying both `required_properties` and
`recommended_properties` for the suggested type. This is a suggestion, never an error; plenty of
legitimate pages (search results, account pages, thank-you pages) have no natural fit and that's
correct, not a gap.

See [references/jsonld-library.md](references/jsonld-library.md) for a minimal valid example of
every recognized `@type` and where to insert the tag per framework (Next.js App/Pages Router,
Astro, Hugo, plain HTML). One shape anchor below; required properties only — recommended
properties (encouraged wherever genuinely true) are in the library.

**Article / BlogPosting / NewsArticle** (all recommended-only — no required properties, so an
empty node never errors, only warns):
```json
{
  "@context": "https://schema.org",
  "@type": "BlogPosting",
  "headline": "Exact page H1, not a separately optimized headline",
  "image": "https://example.com/images/post-hero.jpg",
  "datePublished": "2026-07-05T09:00:00-07:00",
  "author": {"@type": "Person", "name": "Real, displayed byline name"}
}
```

## Running it

> All commands below run from the **target repo root** (the repo that contains the
> website). State and reports land in `<repo>/.seo-engine/` — running from anywhere
> else writes state to the wrong repo. `${CLAUDE_SKILL_DIR}` is set by Claude Code to
> this skill's directory and works for both the symlink and plugin install.

```bash
# Live crawl of the whole configured site
python3 "${CLAUDE_SKILL_DIR}/scripts/validate_schema.py" --live --max-pages 200

# Live check of one URL (e.g. right after editing one page template)
python3 "${CLAUDE_SKILL_DIR}/scripts/validate_schema.py" --live --url https://example.com/blog/my-post

# Local HTML files -- e.g. a pre-deploy CI check against a static build output dir
python3 "${CLAUDE_SKILL_DIR}/scripts/validate_schema.py" --files-dir ./dist --pattern ".html"
python3 "${CLAUDE_SKILL_DIR}/scripts/validate_schema.py" --files dist/index.html dist/blog/post.html

# CI gate: also block on missing-recommended-property warnings, skip writing reports
python3 "${CLAUDE_SKILL_DIR}/scripts/validate_schema.py" --live --strict --no-report
```

Flags: `--live` / `--files` / `--files-dir` (mutually exclusive, one required); `--url` (with
`--live`, check exactly one URL); `--max-pages` (default 200); `--pattern` (with `--files-dir`,
default `*.html`); `--strict` (promote warnings to exit-blocking); `--no-report` (skip writing
under `.seo-engine/`). `--live` with no `--url` needs `site_url` in config or `SEO_SITE_URL` —
otherwise a clean JSON `error`+`hint`, exit 1. No paid API key required for any mode.

## Expected output

```jsonc
{
  "mode": "live", "strict": false, "checked_at": "...",
  "summary": {
    "pages_checked": 42, "pages_skipped_robots": 1, "pages_with_structured_data": 30,
    "pages_with_validation_errors": 3, "pages_with_warnings": 5,
    "pages_missing_natural_fit_schema": 5,
    "issue_counts": {"error": 4, "warning": 6, "info": 1},
    "types_found_counts": {"BlogPosting": 12, "Organization": 1}
  },
  "pages": [
    {
      "url": "https://example.com/blog/my-post", "ok": false, "node_count": 1,
      "types_found": ["BlogPosting"],
      "issues": [{"type": "BlogPosting", "severity": "warning",
                   "message": "BlogPosting is missing recommended properties: datePublished, author"}],
      "missing_schema_suggestion": {"suggested_type": "BlogPosting", "reason": "...",
        "required_properties": [], "recommended_properties": ["headline", "image", "datePublished", "dateModified", "author"]}
    }
  ],
  "report_written_to": ".seo-engine/reports/schema-validation-<stamp>.json",
  "state_written_to": ".seo-engine/state/schema-validation.json"
}
```

Exit `0` unless `issue_counts.error > 0` (or, with `--strict`, `error + warning > 0`); exit `2`
otherwise — safe to wire into CI as build-blocking or warning-only depending on `--strict`. Exit
`1` is reserved for setup problems (missing `site_url`, missing the `extruct` dependency).

## State files

| File (under `.seo-engine/`) | Role | Written by | Read by |
|---|---|---|---|
| `state/crawls/` (shared snapshot store) | consumes (live mode URL discovery) | see [common-setup.md § Snapshot contract](../seo-references/common-setup.md) | this skill + any other |
| `reports/schema-validation-<stamp>.json` | full dated report (pages + summary) | `validate_schema.py` | calling agent |
| `state/schema-validation.json` | rolling summary only (cheap diffing between runs) | `validate_schema.py` | `validate_schema.py`, `seo-maintain` |

Live mode re-fetches each page politely (`min_interval` >= 1.0s, raised further by a
robots.txt `Crawl-delay`) rather than trusting stored HTML, since snapshots don't persist page
bodies. Pages disallowed by robots.txt are skipped, not fetched, and surfaced in
`pages_skipped_robots` — never silently dropped.

## How to interpret results

- `issues` with `severity: "error"` on a page that already ships JSON-LD = a real defect, fix it.
- `severity: "warning"` = a Google-recommended property is missing — worth fixing, not launch-blocking
  unless you've opted into `--strict`.
- `severity: "info"` = advisory only (retired rich-result type) — informational, not a task.
- `missing_schema_suggestion` on a `node_count: 0` page = an opportunity, not a defect. The
  heuristic is conservative but not perfect (e.g. a `/blog/` URL that's actually a listing page,
  not a single post, shouldn't get `BlogPosting`) — use judgment.
- `"Malformed JSON-LD"` always needs a code fix; never auto-correct by guessing the intended value.

## Safe to auto-apply vs. human review

**Safe to auto-apply** (mechanical, low-ambiguity): a missing required/recommended property whose
correct value is unambiguously already on the page (a visible publish date → `datePublished`; the
page's own `<h1>` → `headline`/`name`; an existing `og:image` → `image`/`thumbnailUrl`); fixing
malformed JSON-LD syntax when the intended value is unambiguous; `Organization`/`WebSite` on a
homepage from the site's own header/footer/config; `BreadcrumbList` generated mechanically from
the actual rendered navigation.

**Must be flagged for human review:** adding a *new* schema type to a page — confirm the
content-type inference and (for `Product`) that price/availability/SKU data is accurate; any
`author` value — inventing one is an E-E-A-T/trust problem (seo-playbook.md §4), only wire in a
value that's already the page's real, displayed byline; `LocalBusiness` address/geo data — must
match the verifiable real address; `Recipe`/`HowTo` steps and `VideoObject` duration/upload date —
factual claims that risk a Search Console structured-data warning if wrong. **If the correct value
would need to be invented rather than sourced from something already true and displayed, stop and
ask a human** (red-flags.md §6).

## Guardrails

- Never generate `FAQPage`/`HowTo`/`Recipe` content that doesn't visibly exist on the page —
  schema must describe real, rendered content, a Google spam/structured-data policy violation
  otherwise, not just bad practice.
- Never fabricate `author`, `address`, `aggregateRating`, price/availability, or any other factual
  claim to satisfy a property check.
- Never present this work as "improving AI/GEO visibility" — traditional-SEO/entity-clarity value
  only (geo-playbook.md §3).
- Never serve different JSON-LD to a crawler than what a human visitor's browser renders — cloaking
  (red-flags.md §1).

## References

- [common-setup.md](../seo-references/common-setup.md) — paths, config resolution, snapshot contract.
- [references/jsonld-library.md](references/jsonld-library.md) — full example library + per-
  framework insertion guide.
- [seo-playbook.md](../seo-references/seo-playbook.md) §4 (E-E-A-T — governs the author-value
  guardrail), §8 (structured data's real, traditional-SEO value).
- [geo-playbook.md](../seo-references/geo-playbook.md) §3 — why this skill must never be sold as
  a GEO lever.
- [red-flags.md](../seo-references/red-flags.md) §1 (Cloaking), §6 (the meta-rule for any
  ambiguous "would this read as a legitimate improvement or a fabrication" call).

## Ceiling of this validator

This is a **CI-safe floor**, not a substitute for Google's own verdict — it's a required-property
presence check, not full schema.org type validation. There is no public Rich Results Test API
(the old Structured Data Testing Tool API was deprecated with no replacement); the only
programmatic path to Google's actual verdict is GSC's URL Inspection `richResultsResult`, and
that only works for URLs already indexed on an already-verified property. Before shipping a new
schema type to production, manually check
[search.google.com/test/rich-results](https://search.google.com/test/rich-results) — it surfaces
Google-specific eligibility nuances (minimum image resolution, tightened `FAQPage` eligibility)
this presence check cannot know about. A clean `validate_schema.py` run means "no obvious
defects," not "confirmed eligible."

## Graceful degradation

Generic philosophy: [common-setup.md § Graceful degradation](../seo-references/common-setup.md).
No paid API key required for any mode — only the built-in crawler and offline `extruct`-based
extraction. If `extruct` isn't installed, the script prints a clean JSON error + remediation
(`pip install -r requirements.txt`) and exits 1 rather than a traceback.
