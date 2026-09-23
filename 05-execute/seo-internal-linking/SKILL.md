---
name: seo-internal-linking
description: "Builds an alias-folded internal-link graph from a crawl snapshot to find orphan pages (evidenced against an independent sitemap/GSC URL universe, never claimed from crawl data alone), unreachable clusters, and pages more than ~4 clicks deep, then scores existing pages by topical overlap for contextual link-insertion candidates. Invoke when a page isn't indexing/refreshing despite being live, after adding pages, after an IA/navigation change, or in a seo-maintain pass. Not for crawlability/redirect/canonical issues (use seo-technical-audit)."
---

# seo-internal-linking

Per [seo-playbook.md §6](../../shared/seo-references/seo-playbook.md): internal links are how both crawlers
and readers discover a page's relative importance and topical relationships. This is a **read-only
analysis and suggestion** skill — it never edits site content. It hands the calling agent a
prioritized list of structural problems (`analyze_link_graph.py`) and, for each, a shortlist of
existing pages worth investigating for a natural link insertion (`suggest_link_opportunities.py`).

**Orphan detection requires an independent URL source (sitemap/GSC).** A link-following crawl
cannot discover an unlinked page by construction — when no independent source is available, the
report says so honestly (`orphans.checked: false`), never an empty-but-clean list.

## When to use this skill

- A specific page isn't indexing, ranking, or seems rarely crawled/refreshed, and crawlability
  (`seo-technical-audit`) has already been ruled out.
- New pages, listings, posts, or a new site section were just added — the most common source of
  fresh orphans.
- After a navigation, menu, footer, or information-architecture redesign — these frequently sever
  existing internal links without anyone noticing.
- As a recurring step dispatched by `seo-maintain`'s `not_checked.orphan_pages` note (orphan
  detection is structurally impossible from a link-following crawl alone, so `seo-maintain` never
  claims it and always dispatches here).
- A user asks to "build topical authority," "improve internal linking," or "find pages that need
  more links."
- **Not** for broken links, redirects, or canonical issues that can produce false-looking orphans —
  rule those out with `seo-technical-audit` first.

## What it checks / does

### Step 1 — `scripts/analyze_link_graph.py`

1. **Crawl** via the shared snapshot store (reuses any <24h snapshot, else crawls fresh;
   `--force-recrawl` forces a fresh crawl). There is no snapshot-path override flag.
2. Builds an **alias-folded** directed graph (`lib/linkgraph`) restricted to indexable pages
   (`pagerules.is_indexable_html`) — a page linked only through its redirecting alias or www
   variant still counts as linked.
3. **BFS from the homepage** computes shortest link-depth for every indexable page.
4. Findings:
   - **`orphan_page`** (high; low if the crawl was truncated) — in the independent URL universe
     (sitemap + GSC), crawled, indexable, but unreachable from the homepage.
   - **`orphan_candidate`** (medium) — in the universe, never seen by the crawl, and live-confirmed
     HTTP 200 from a bounded, polite 20-URL sample (min 1.0s interval). Non-200/errored sample URLs
     are noted, never flagged.
   - **`unreachable_page`** (high) — crawled, indexable, but disconnected from the homepage-rooted
     graph (an island) — a crawl-only signal, no universe needed.
   - **`deep_page`** (medium) — indexable page deeper than `--max-depth` (default 4) clicks, per
     seo-playbook.md §6's ~3-4-click guidance.
   - **`single_inbound_link`** (low) — exactly one distinct inbound internal link; one navigation
     or template change from becoming unreachable.
5. **No universe available** (sitemap fetch failed and GSC unconfigured) -> `orphans: {"checked":
   false, "reason": ...}` — this refusal is correct behavior, not a claim of a clean site, and the
   calling agent should report it as such, not as "no orphans found."

### Step 2 — `scripts/suggest_link_opportunities.py`

For a flagged page (single `--target-url`, or batch `--from-analysis` over every orphan/
unreachable/deep finding from the latest report), scores every other indexable page by weighted
keyword overlap (title/H1 weighted 3x, H2/OG weighted 1x — the only text signals the snapshot
retains; no full body text) against the target. Produces a ranked candidate shortlist, not a
specific sentence to edit and not a ranking by predicted traffic impact.

- Never crawls on its own — reuses the exact snapshot named by the analysis report's
  `snapshot_path`, or falls back to the newest <24h store snapshot.
- Targets resolved through the alias map — a page is never suggested as its own link candidate via
  a slash/www/redirect alias.
- Noindex targets and candidates are excluded on both ends. A target that is not an indexable
  crawled page (noindex, non-200, or never crawled) is skipped, not silently omitted — it appears
  in `suggestions` with `skipped: true` and a `skipped_reason`, and counts toward
  `targets_skipped`.

## Running it

> All commands below run from the **target repo root** (the repo that contains the
> website). State and reports land in `<repo>/.seo-engine/` — running from anywhere
> else writes state to the wrong repo. Set `SKILL_DIR` to this skill's resolved absolute directory before running these commands
> (see common-setup.md); no host-specific variable is required.

```bash
python3 "${SKILL_DIR}/scripts/analyze_link_graph.py"

python3 "${SKILL_DIR}/scripts/analyze_link_graph.py" --max-depth 3 --max-pages 300
python3 "${SKILL_DIR}/scripts/analyze_link_graph.py" --force-recrawl

python3 "${SKILL_DIR}/scripts/suggest_link_opportunities.py" \
  --target-url https://example.com/orphan-page

python3 "${SKILL_DIR}/scripts/suggest_link_opportunities.py" --from-analysis

python3 "${SKILL_DIR}/scripts/suggest_link_opportunities.py" \
  --from-analysis --max-candidates 8 --min-score 0.05
```

Flags — `analyze_link_graph.py`: `--max-depth` (default 4), `--max-pages` (default 500),
`--force-recrawl`. `suggest_link_opportunities.py`: `--target-url`, `--from-analysis`,
`--max-candidates` (default 5), `--min-score` (default 0.08). Both require `site_url` in
`.seo-engine/config.yml` or `SEO_SITE_URL`. No paid API key unlocks anything further — the crawler
and overlap-matching are free, local computation.

## Expected output

`analyze_link_graph.py` — written to `.seo-engine/reports/internal-linking-<date>.json`:

```jsonc
{
  "homepage_url": "https://example.com",
  "max_depth_threshold": 4,
  "pages_analyzed": 342,
  "orphans": {
    "checked": true, "sources": {"sitemap": true, "gsc": false},
    "universe_count": 350, "reachable_count": 339,
    "orphan_page_count": 3,
    "live_check": { "sampled": 5, "confirmed_200_count": 2, "other": [] }
  },
  "finding_counts_by_type": { "orphan_page": 3, "deep_page": 7, "single_inbound_link": 4 },
  "severity_counts": { "high": 4, "medium": 7, "low": 4 },
  "depth_histogram": { "0": 1, "1": 12, "2": 88 },
  "findings": [
    { "type": "orphan_page", "severity": "high", "url": "...", "depth_from_homepage": null,
      "auto_fixable": false, "human_review_reason": "..." }
  ]
}
```

`suggest_link_opportunities.py`:

```jsonc
{
  "mode": "from_analysis",
  "targets_processed": 10,
  "targets_with_candidates": 8,
  "targets_with_no_candidates": 1,
  "targets_skipped": 1,
  "suggestions": [
    { "target_url": "...", "finding_type": "orphan_page", "candidate_count": 3,
      "candidates": [ { "candidate_url": "...", "overlap_score": 0.52, "shared_terms": ["..."] } ],
      "auto_apply": false, "human_review_checklist": ["..."] },
    { "target_url": "...", "skipped": true, "skipped_reason": "target is not an indexable crawled page ..." }
  ]
}
```

`findings` is pre-sorted high -> medium -> low (orphans/unreachable are high; deep pages medium;
single-inbound-link low).

## State files

| File (under `.seo-engine/`) | Role | Written by | Read by |
|---|---|---|---|
| `state/crawls/` (shared snapshot store) | consumes/produces this run's crawl | see [common-setup.md § Snapshot contract](../../shared/seo-references/common-setup.md) | this skill + any other |
| `reports/internal-linking-<date>.json` | dated analysis report; its `snapshot_path` anchors `suggest_link_opportunities.py --from-analysis` to the same crawl | `analyze_link_graph.py` | `suggest_link_opportunities.py`, calling agent |
| `state/internal-linking-last-run.json` | compact run summary (orphans_checked, orphan_page_count, orphan_candidate_count, finding_counts_by_type) | `analyze_link_graph.py` | `analyze_link_graph.py` (this skill only — not consumed by `seo-maintain`) |

## How to interpret results

- **`orphan_page` / `unreachable_page` (high)** — undiscoverable by any crawler or reader following
  normal `<a href>` navigation from the homepage. Caps indexing/refresh regardless of content
  quality. Higher priority than `deep_page`.
- **`deep_page` (medium)** — reachable but past the ~3-4-click threshold; a cluster of many on one
  topic suggests the hub/category structure needs a stronger mid-tier linking layer.
- **`depth_from_homepage: null`** appears for both true orphans and unreachable-cluster pages —
  check `type` to distinguish them.
- **`orphans.checked: false`** — not a clean bill of health, a refusal. Read `reason`: it names
  what's missing (sitemap fetch failed, GSC not configured) — report the coverage gap honestly
  rather than "no orphans found."
- **`shared_terms` in a suggestion are a starting point, not proof** — a high `overlap_score` means
  title/heading vocabulary overlaps, not that a paragraph on the candidate page actually discusses
  the shared topic. Always open the real candidate page's source content before acting.
- **`targets_with_no_candidates`** — either a genuinely standalone topic (may need a new hub page)
  or related content exists but isn't titled/headed in overlapping language yet. Don't force a link
  onto an unrelated page just to clear the finding.

## Safe to auto-apply vs. human review

**Nothing here is ever auto-applied.** Both scripts are read-only; `suggest_link_opportunities.py`
always sets `"auto_apply": false` and ships a `human_review_checklist`. Careless automated
anchor-text insertion reads as manipulative link building even when the underlying intent (fixing
an orphan) is legitimate ([red-flags.md §1](../../shared/seo-references/red-flags.md)).

**Before inserting any suggested link, the calling agent must:**
1. Open the actual source content of the candidate page (not just the snapshot's title/H1/H2
   signals) and confirm a real, already-existing sentence genuinely discusses the shared topic.
2. Write descriptive anchor text naming the destination's actual subject — never "click here".
3. Insert the link into that existing sentence/paragraph — never append a "Related pages"
   boilerplate block or bare link list purely to host the connection.
4. Confirm the candidate page is itself reachable from the homepage (cross-check
   `link_graph_depths`) — a link added to another orphan/unreachable page doesn't fix
   discoverability for anyone.
5. If no genuinely fitting sentence exists on any candidate, report that back rather than
   fabricating a paragraph or forcing an unnatural insertion.

## Guardrails

- Never auto-generate a "Related Articles" block as a blanket fix for orphans at scale — the
  injected-boilerplate pattern seo-playbook.md §6 rules out.
- Never treat "this page has no inbound links" as license to add reciprocal links indiscriminately
  across many pages in one templated pass — each insertion needs genuine topical fit
  ([red-flags.md §1](../../shared/seo-references/red-flags.md)).
- Never fabricate or embellish a candidate page's content to manufacture a plausible sentence.
- Never claim schema.org/JSON-LD or `llms.txt` help internal-linking goals — out of scope; see
  [geo-playbook.md §§1, 3](../../shared/seo-references/geo-playbook.md) and redirect to `geo-optimize`.
- Never increase publishing volume to "fix" orphans by auto-generating new hub pages — a genuinely
  new hub page is a human/agent content decision with its own justification.

## References

- [common-setup.md](../../shared/seo-references/common-setup.md) — paths, config resolution, snapshot
  contract, degradation philosophy.
- [seo-playbook.md](../../shared/seo-references/seo-playbook.md) §6 — this skill's entire scope: no-orphans
  rule, ~3-4-click depth guidance, contextual-over-boilerplate linking, descriptive anchor text.
  §2 — crawlable internal link graph as part of the non-negotiable technical layer.
- [red-flags.md](../../shared/seo-references/red-flags.md) §1 (link spam / link schemes — why nothing here
  auto-inserts), §6 (the meta-rule every suggested insertion must pass).

## Graceful degradation

Generic philosophy: [common-setup.md § Graceful degradation](../../shared/seo-references/common-setup.md).
No API keys required — the crawler is unauthenticated and the overlap-matching logic is pure local
computation. If no crawl snapshot exists yet, `analyze_link_graph.py` crawls `site_url` itself and
stores it for reuse. `suggest_link_opportunities.py` requires that snapshot (or the store's latest)
to already exist — it never crawls on its own; run `analyze_link_graph.py` first.
