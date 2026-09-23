---
name: seo-keyword-research
description: Mines Google Search Console for near-miss keyword opportunities — queries already earning impressions that rank outside the top 10 or under-convert on CTR — and enriches them with DataForSEO/Ahrefs volume and difficulty data to prioritize what content to improve next. Invoke for 'find keyword opportunities', 'what should we optimize next', or why impressions aren't becoming clicks. Not for tracking whether positions dropped over time (use seo-rank-tracking) or a full status checkup (use seo-maintain).
---

# seo-keyword-research

Opportunity mining: find realistic, valuable keyword/topic opportunities using a
site's own Search Console signal as the primary filter, and paid keyword-volume/
difficulty data as prioritization context — never the other way around.

## When to use this skill

- A human or `seo-maintain` asks to find keyword opportunities, decide what to
  optimize next, or do "keyword research."
- A specific page's impressions look healthy in GSC but clicks/rankings don't
  match — this skill explains *which queries* are underperforming and by how much.
- Before `seo-content-optimize` starts a content-improvement pass — this skill's
  output tells that skill *where* to focus, never *what to write*.
- On a recurring cadence (monthly is reasonable; GSC data itself only meaningfully
  changes over weeks) to refresh the opportunity backlog.
- **Not** for: tracking whether positions dropped over time → `seo-rank-tracking`;
  a full whole-site status checkup → `seo-maintain`; finding "new keywords to
  cover with a new page" — that is explicitly not this skill's purpose, see below.

## What it checks / does

1. **`find_opportunities.py`** — calls GSC `search_analytics_query_all` with
   `dimensions=["query","page"]` over a recent window (default 90 days, ending
   3 days before GSC's "today" to respect its reporting lag; GSC windows use
   Pacific-time dates — common-setup § Integration availability). Rows are fully
   paginated up to `--row-limit` (default 100000; `summary.gsc_row_cap_hit`
   flags truncation). `--country`/`--device` add those GSC dimensions and filter
   client-side (noted in `setup_notes`) — equivalent granularity to a
   server-side filter.
2. Flags a query+page row as a **near-miss opportunity** when it already has
   real impressions (`--min-impressions`, default 10) and either **ranks
   outside the top 10** (`position > --min-position`, default 10.0) or **ranks
   near/at the top 10 but converts worse than that position typically should**
   (CTR below `--ctr-ratio-threshold` × the expected CTR for that position
   band, from a widely-replicated organic CTR-by-position curve — a rough
   reference, not a precise per-SERP model).
3. Groups flagged rows by query, computes **estimated headroom in clicks** per
   query, and ranks opportunities by that headroom — search volume is only a
   secondary tie-breaker.
4. Attaches keyword context for the flagged queries: DataForSEO `search_volume`
   (preferred by default — no subscription-tier gate, cheaper per call) if
   configured, else Ahrefs `keywords_overview`; `--prefer-ahrefs` flips the
   preference. Either integration is optional and additive; DataForSEO
   task-level errors degrade gracefully (dropped from context, noted, run
   continues) rather than failing the whole run.

### Why "near-miss" is the right thing to mine

A query where a page already gets impressions is one Google's own ranking
systems already consider that page relevant for. Improving that page for that
query is almost always cheaper and more realistic than creating new content and
waiting for it to build authority from zero — the same compounding logic
seo-playbook §6 applies to internal linking, and the most defensible,
non-speculative prioritization heuristic available from free data.

## Running it

> All commands below run from the **target repo root** (the repo that contains the
> website). State and reports land in `<repo>/.seo-engine/` — running from anywhere
> else writes state to the wrong repo. `${CLAUDE_SKILL_DIR}` is set by Claude Code to
> this skill's directory and works for both the symlink and plugin install.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/find_opportunities.py"

python3 "${CLAUDE_SKILL_DIR}/scripts/find_opportunities.py" --days 28 --min-impressions 25

python3 "${CLAUDE_SKILL_DIR}/scripts/find_opportunities.py" --min-position 15

python3 "${CLAUDE_SKILL_DIR}/scripts/find_opportunities.py" --no-keyword-data

python3 "${CLAUDE_SKILL_DIR}/scripts/find_opportunities.py" --country usa --device MOBILE

python3 "${CLAUDE_SKILL_DIR}/scripts/find_opportunities.py" --prefer-ahrefs --row-limit 200000
```

## Expected output

Structured JSON to stdout, trimmed to the load-bearing fields:

```jsonc
{
  "lookback_days": 90,
  "thresholds": { "min_impressions": 10, "min_position_for_outside_target_flag": 10.0,
                  "ctr_ratio_threshold_for_underperforming_position": 0.6 },
  "setup_notes": [ "GSC window: ...", "Attached DataForSEO search-volume context for 87 of 100 queries." ],
  "summary": {
    "query_page_rows_returned_by_gsc": 3120, "gsc_row_cap_hit": false,
    "rows_flagged_as_near_miss": 214, "distinct_opportunities_returned": 100,
    "keyword_context_source": "dataforseo"
  },
  "opportunities": [
    {
      "query": "how to fix cls layout shift",
      "primary_page": "https://example.com/blog/core-web-vitals-guide",
      "total_impressions": 4200, "total_clicks": 38, "best_position": 14.2,
      "total_estimated_headroom_clicks": 214.0,
      "pages": [ { "page": "...", "flag_reason": "ranks_outside_target_position",
                   "ctr_vs_expected_ratio": 0.6, "estimated_headroom_clicks": 214.0 } ],
      "keyword_context": { "volume": 1200, "keyword_difficulty": 34, "cpc": 2.10, "source": "dataforseo" }
    }
  ],
  "history_file": ".seo-engine/state/keyword-opportunities-history.json",
  "history_note": "History persists ONLY the flagged opportunities each run ...",
  "remediation_guidance": "... improve primary_page's genuine usefulness ... never keyword-stuffing, never a new thin page ...",
  "report_file": ".seo-engine/reports/keyword-opportunities-<timestamp>.json"
}
```

## State files

| File (under `.seo-engine/`) | Role | Written by | Read by |
|---|---|---|---|
| `state/keyword-opportunities-history.json` | flagged opportunities only (keyed `query::primary_page`, capped 52 entries) — a key absent from a run means "not flagged," never "zero traffic" | `find_opportunities.py` | `find_opportunities.py` (this skill only) |
| `reports/keyword-opportunities-<timestamp>.json` | dated run report | `find_opportunities.py` | human/agent (terminal output) |

## How to interpret results

1. **`total_estimated_headroom_clicks` is the primary ranking signal**, not
   `keyword_context.volume`. Headroom comes from the site's own earned
   impressions; volume is total market size and says nothing about whether
   *this site* can realistically capture it.
2. **`flag_reason` tells you what kind of fix is needed:**
   - `ranks_outside_target_position` — the page needs to become more
     genuinely useful for the query — a content-quality gap.
   - `ctr_below_position_expectation` — the page already ranks reasonably but
     the title/snippet isn't earning the clicks the position supports. Check
     `seo-metadata` first — often a title/meta-description problem, not depth.
3. **`keyword_context` being `null` is not a reason to deprioritize.** It only
   means no paid API is configured or the vendor had no data for that
   long-tail query — GSC still shows real impressions, which is itself a
   legitimate signal.
4. **`keyword_difficulty`/`competition` contextualizes the remaining gap, not
   a veto** — a near-miss with existing impressions already beats a cold-start
   difficulty score calibrated for ranking from zero.
5. Treat headroom and the expected-CTR curve as a **rough prioritization
   heuristic**, not a traffic forecast — rank a backlog with it, don't promise
   a click number to a stakeholder.
6. **A query spread across many `pages`** can mean genuine topical depth, or
   unintentional cannibalization. More than 2-3 entries with similar
   impressions → flag for human review as a possible consolidation question
   before optimizing any one of them.

## Safe to auto-apply vs. human review

This skill **only mines and ranks opportunities — it makes no content edits.**

Safe without asking:
- Re-running the script to refresh the list (read-only against GSC/Ahrefs/DataForSEO).
- Handing `opportunities` to `seo-content-optimize` or `seo-metadata` as input
  to *their* review process.
- Flagging apparent cannibalization for human review — a flag, not a
  merge/redirect (that is `seo-redirects` territory, with its own sign-off).

Human review first:
- Any specific rewrite/expansion of `primary_page` — this skill identifies
  *where*, never *what to write*.
- Any decision to create a new page for a query instead of improving an
  existing one — the doorway-page/scaled-content-abuse risk surface (§1
  below); requires an articulable reason a real reader needs a *separate*
  page, not just "a query exists."
- Any page-consolidation/redirect decision arising from a cannibalization flag.

## Guardrails

- red-flags §1 (scaled content abuse, doorway pages) — one opportunity-list
  entry is never a mandate for one new page; `remediation_guidance` in the
  script's own output states this.
- red-flags §6 (the meta-rule) — state in one sentence why a specific edit
  helps a real searcher; "it's a near-miss in GSC" describes *where*, not *why*.
- Preferred remediation style once an opportunity is identified: adding
  citations, direct quotations, and concrete statistics — geo-playbook §5 —
  over generic prose expansion or heading/list restructuring, which that
  research found no benefit for. Never invent a statistic to satisfy this
  pattern; keyword-stuffing the flagged query is out of scope entirely.
- Nothing in this skill's domain touches cloaking, link schemes, or
  canonical/redirect risk directly — that stays with `seo-technical-audit` and
  `seo-redirects`.

## References

- [common-setup.md](../../shared/seo-references/common-setup.md) — paths/cwd rules,
  config and env resolution, GSC property auto-resolution and Pacific-time windows.
- [api-reference.md](../../shared/seo-references/api-reference.md) — GSC method and
  quotas; DataForSEO vs. Ahrefs auth/cost models (why DataForSEO is preferred).
- [seo-playbook.md](../../shared/seo-references/seo-playbook.md) §1 — the people-first
  governing principle; §6 — compounding-what-already-has-traction logic.
- [geo-playbook.md](../../shared/seo-references/geo-playbook.md) §5 — the one
  evidence-backed content-improvement tactic (citations/quotes/statistics).
- [red-flags.md](../../shared/seo-references/red-flags.md) §1 (scaled content abuse,
  doorway pages) and §6 (the meta-rule).

## Graceful degradation

Generic philosophy: common-setup § Graceful degradation. Skill-specific:

- **GSC is the hard requirement.** Without it the script has no meaningful
  signal — it prints the exact remediation (`GOOGLE_APPLICATION_CREDENTIALS`
  or `GSC_SERVICE_ACCOUNT_JSON`, plus service-account access on the property)
  and exits non-zero rather than returning a confusing empty result.
- **Paid keyword-volume/difficulty context is optional and additive, never
  blocking.** With neither `DATAFORSEO_LOGIN`+`DATAFORSEO_PASSWORD` nor
  `AHREFS_API_KEY` set, the script still runs and ranks purely by GSC-derived
  headroom, and says so plainly in `setup_notes`.
- Each run is read-only against all three APIs — no quota-costly writes — but
  DataForSEO/Ahrefs enrichment consumes paid API units, so `--max-queries`
  (default 100) caps how many flagged queries get enriched per run.
