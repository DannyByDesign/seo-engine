---
name: seo-performance
description: Audits Core Web Vitals (LCP, INP, CLS) for a site's key pages via PageSpeed Insights field + lab data, and translates failing Lighthouse audits into concrete code-level fixes (image optimization, lazy-loading, script deferral, font-loading, third-party script trimming). Invoke when asked to check page speed/Core Web Vitals, when a Lighthouse/PSI score is mentioned, after a redesign or dependency upgrade that could regress performance, or as part of a routine seo-maintain pass.
---

# seo-performance

Core Web Vitals auditing and remediation guidance for the pages that matter
most on a site.

## When to use this skill

- A human or `seo-maintain` asks to check Core Web Vitals, page speed, or a
  Lighthouse/PageSpeed score.
- After any change likely to affect load performance: new hero images, a new
  third-party script, a font change, a framework/bundler upgrade, a redesign.
- As a recurring health check — CWV can regress silently (an unoptimized image,
  a marketing tag added via a tag manager) with no code review catching it.
- When GSC or `seo-maintain` reports a "Core Web Vitals"/"page experience" drop.
- **Not** for chasing a perfect Lighthouse score at the expense of content
  quality — see "How to interpret results" below.

## What it checks / does

Runs `scripts/audit_cwv.py`, which wraps `scripts/lib/psi.py` across a set of
key pages and reports, per page:

1. **Field data** (CrUX real-user metrics, from PSI's `loadingExperience`):
   LCP, INP, CLS against Google's published "good" thresholds — one line +
   pointer: seo-playbook §3. **This is the authoritative, ranking-relevant number.**
2. **Lab diagnostics** (Lighthouse's synthetic run, from `lighthouseResult`,
   performance category only): the specific `opportunities`/`diagnostics`
   audits explaining *why* a page is slow, each with a one-line, code-level
   `fix_guidance` string (render-blocking resources, unoptimized/non-modern
   images, missing `width`/`height`, long main-thread tasks, oversized
   third-party scripts, font-display strategy, etc.).
3. **Page discovery**: homepage always included, plus (unless disabled) pages
   from the shared crawl-snapshot store (`snapshots.latest`, reusing any <24h
   snapshot from any producer skill before running its own fresh crawl) and/or
   GSC top-clicked pages (last 28 days). `--url` (repeatable) overrides
   discovery unless `--include-discovered` is also passed.
4. **History**: only successful PSI fetches are appended — an errored URL
   creates no history entry (no state pollution from a bad fetch).

## Running it

> All commands below run from the **target repo root** (the repo that contains the
> website). State and reports land in `<repo>/.seo-engine/` — running from anywhere
> else writes state to the wrong repo. `${CLAUDE_SKILL_DIR}` is set by Claude Code to
> this skill's directory and works for both the symlink and plugin install.

```bash
# Auto-discover key pages: homepage + shared crawl snapshot + GSC top-clicked (if configured)
python3 "${CLAUDE_SKILL_DIR}/scripts/audit_cwv.py"

# Audit specific URLs only (skips auto-discovery unless --include-discovered is added)
python3 "${CLAUDE_SKILL_DIR}/scripts/audit_cwv.py" \
  --url https://example.com/ --url https://example.com/pricing

# Desktop strategy, or both mobile and desktop in one run
python3 "${CLAUDE_SKILL_DIR}/scripts/audit_cwv.py" --strategy desktop
python3 "${CLAUDE_SKILL_DIR}/scripts/audit_cwv.py" --both-strategies

# Limit discovery breadth, or disable one/both discovery sources
python3 "${CLAUDE_SKILL_DIR}/scripts/audit_cwv.py" --max-pages 15 --no-gsc
python3 "${CLAUDE_SKILL_DIR}/scripts/audit_cwv.py" --no-crawl-snapshot --no-gsc
```

## Expected output

```jsonc
{
  "thresholds_ms_and_unitless": { "lcp_ms": {"good": 2500, "needs_improvement": 4000}, "inp_ms": {"...":"..."}, "cls": {"...":"..."} },
  "methodology_note": "field_data ... is the authoritative, ranking-relevant signal. lab_diagnostics ...",
  "setup_notes": ["GOOGLE_PSI_API_KEY not set -- ..."],
  "discovery_notes": ["Reusing crawl snapshot ... Added 4 page(s) ...", "Added 6 top-clicked page(s) from GSC ..."],
  "summary": {
    "pages_audited": 10, "pages_failed_to_fetch": 0, "pages_with_field_data": 8,
    "pages_passing_cwv_assessment": 6, "pages_failing_lcp": 2, "pages_failing_inp": 0, "pages_failing_cls": 1
  },
  "pages": [
    {
      "url": "...", "strategy": "mobile",
      "field_data": { "lcp_ms": {"value": 3200, "rating": "needs_improvement"}, "overall_category": "AVERAGE", "has_field_data": true },
      "lab_diagnostics": {
        "lab_performance_score": 0.62,
        "opportunities": [ {"id": "render-blocking-resources", "estimated_savings_ms": 800, "fix_guidance": "Defer or async non-critical <script>/<link rel=stylesheet> tags; ..."} ],
        "diagnostics": [ {"id": "layout-shift-elements", "fix_guidance": "Reserve explicit width/height ..."} ]
      },
      "failing_metrics": [], "needs_improvement_metrics": ["lcp_ms"],
      "passes_core_web_vitals_assessment": false
    }
  ],
  "history_file": ".seo-engine/state/cwv-history.json",
  "report_file": ".seo-engine/reports/cwv-audit-<timestamp>.json"
}
```

A page that failed to fetch carries an `"error"` field instead of a
`field_data`/`lab_diagnostics` pair, and is excluded from `summary` counts and
history.

## State files

| File (under `.seo-engine/`) | Role | Written by | Read by |
|---|---|---|---|
| `state/crawls/` (shared snapshot store) | consumes/produces | see common-setup.md § Snapshot contract | this skill + any other |
| `state/cwv-history.json` | time series per `url::strategy`, capped ~52 entries; only successful fetches recorded | `audit_cwv.py` | `audit_cwv.py` (this skill only) |
| `reports/cwv-audit-<timestamp>.json` | dated run report | `audit_cwv.py` | human/agent (terminal output) |

## How to interpret results

1. **Field data is the number you report as "the site's Core Web Vitals
   status."** If `has_field_data` is `false`, that page likely gets too
   little real-world traffic for a stable 28-day CrUX sample — fall back to
   the lab score as a rough proxy and say so explicitly.
2. **Lab diagnostics exist only to explain a failing or borderline field
   metric** — never present the Lighthouse performance score itself as what
   Google uses for ranking. Field and lab data are two different things
   bundled in one PSI response; don't assume field data might disappear.
3. **CWV is a differentiator, not a dominant ranking factor** (seo-playbook
   §3). A page with excellent CWV but thin content will not outrank a page
   with average CWV and genuinely better content — frame every recommendation
   as "fix real technical debt," never "chase a 100 Lighthouse score."
4. **Match the failing metric to the fix category** using
   `lab_diagnostics.opportunities`/`diagnostics` and their `fix_guidance`:
   - **LCP** → `prioritize-lcp-image`, `render-blocking-resources`,
     `uses-optimized-images`/`modern-image-formats`,
     `unused-css-rules`/`unused-javascript`. Check
     `largest-contentful-paint-element`/`lcp-discovery-insight` first to
     confirm *which* element is the LCP candidate before prescribing a fix.
   - **CLS** → `layout-shift-elements`/`cls-culprits-insight` (missing
     width/height/aspect-ratio, web-font swap, content injected above
     existing content) and `font-display`.
   - **INP** → `long-tasks`, `bootup-time`, `mainthread-work-breakdown`,
     `dom-size`, `third-party-summary`/`third-party-facades`,
     `non-composited-animations` — almost always reducing main-thread work or
     JS execution cost, not image optimization.
   - **Third-party scripts** (`third-party-summary`) are a common
     cross-cutting cause of both slow LCP and slow INP — a marketing/
     analytics/chat-widget tag added outside code review is one of the most
     common silent regressions this skill exists to catch.
5. A single low-traffic page failing CWV is lower priority than the homepage
   or a high-traffic template failing — weight attention using GSC-discovered
   top-clicked pages when configured, not an arbitrary crawl sample.

## Safe to auto-apply vs. human review

Safe to apply directly (mechanical, no side effect beyond the intended one):
- Adding explicit `width`/`height` (or `aspect-ratio`) to `<img>`/`<video>`/
  embed elements that lack them, when source dimensions are already known.
- Adding `loading="lazy"` to below-the-fold images without a loading strategy
  — **never the actual LCP element**, which must never be lazy-loaded (verify
  against `largest-contentful-paint-element` first).
- Adding `fetchpriority="high"` to a confirmed LCP image.
- Adding `font-display: swap` to `@font-face` declarations without one.
- Adding `defer`/`async` to genuinely independent third-party `<script>` tags
  that don't write to `document` synchronously or depend on load order
  (verify first — some legacy scripts break if deferred).
- Converting an image to a modern format (AVIF/WebP with fallback) via an
  existing build-time image pipeline already in the repo.

Must be flagged for human review, not auto-applied:
- Removing or downgrading any third-party script (analytics, ads, chat, tag
  manager) — a business/product decision, not a pure performance one.
- Code-splitting or bundler configuration changes (`unused-javascript`,
  `duplicated-javascript`, `legacy-javascript`, browserslist/target changes)
  — can change browser support matrix; needs a human decision and a build/test pass.
- Any CSS/JS minification or build-pipeline change that isn't already the
  repo's existing, tested pattern.
- Restructuring layout to fix `dom-size` or a structural `layout-shift-elements`
  cause beyond a simple missing-dimension fix.
- Any fix on a page discovered via GSC top-clicked pages should be called out
  as high-traffic before applying anything — a mistake here has outsized impact.

If in doubt whether a change is purely mechanical, treat it as a review item.

## Guardrails

- red-flags §6 (the meta-rule) — before applying any fix, state in one
  sentence why it's a legitimate improvement for real users, not just a
  score-chasing change.
- **Never lazy-load the actual LCP element** — this is the single most common
  way an auto-applied "performance fix" makes LCP worse, not better; always
  confirm the LCP candidate via `largest-contentful-paint-element` first.
- Don't let a CWV push become an excuse to strip content, collapse pages, or
  reduce genuinely useful page weight — that trades a minor, non-dominant
  ranking signal for a larger one (content helpfulness, seo-playbook §1). If
  a real trade-off like this comes up, flag it for human review.

## References

- [common-setup.md](../seo-references/common-setup.md) — paths/cwd rules,
  config/env resolution, the shared snapshot-store contract.
- [api-reference.md](../seo-references/api-reference.md) — PageSpeed Insights
  / CrUX API auth, quotas, field-vs-lab response shape.
- [seo-playbook.md](../seo-references/seo-playbook.md) §3 — Core Web Vitals
  thresholds and how CWV weighs against content quality.
- [red-flags.md](../seo-references/red-flags.md) §6 — the meta-rule.

## Graceful degradation

Generic philosophy: common-setup § Graceful degradation. Skill-specific:

- Works with **zero paid keys** using PSI's shared unauthenticated quota
  (low, shared across all unauthenticated callers, prone to throttling). Set
  `GOOGLE_PSI_API_KEY` (the script prints where to get one) for a much higher
  quota — the same key also unlocks the dedicated CrUX API for historical
  trend queries beyond this script's own history file.
- Auto-discovery beyond the homepage needs either a reusable crawl snapshot
  (any skill's, <24h old, else this script runs its own) or GSC configured
  (`GOOGLE_APPLICATION_CREDENTIALS`/`GSC_SERVICE_ACCOUNT_JSON`) for real
  top-clicked pages. With neither, the script audits the homepage only (or
  exactly the `--url` list) and says so in `discovery_notes` rather than
  silently under-covering the site. `--no-crawl-snapshot` also suppresses the
  fallback fresh crawl, not just snapshot reuse.
- A page that fails to fetch from PSI (timeout, invalid URL, PSI error)
  carries an `"error"` field instead of crashing the whole run — the rest of
  the batch still completes.
