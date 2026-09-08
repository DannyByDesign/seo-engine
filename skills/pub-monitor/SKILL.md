---
name: pub-monitor
description: Measures whether a publication is working — per-publication Search Console rollups over rolling 14/30/90-day windows with previous-window deltas (site, post, pillar, query, daily series), an awaiting/receiving indexing proxy per post, deterministic insights, refresh triggers (click drops, age, never indexed, dated figures) that queue rewrite spokes, and a sync that turns the latest brand-mention run into GEO gap opportunities for pub-curate. Invoke weekly or from the maintenance loop. AI-assistant mention tracking itself lives in geo-monitor.
---

# pub-monitor

The answer to "is it working". Traffic and indexing come from Search Console; assistant
mentions and citations come from `geo-monitor`'s brand-mention tracker (the Lettertrace
method, `publication-playbook.md` §7). This skill rolls the first up per publication and
folds the second into the topic-selection loop.

## When to use this skill

- Weekly, per publication: `report_performance.py --period 30d --sync-geo`.
- Before planning a refresh cycle: `refresh_triggers.py --queue`.
- Whenever `pub-curate` needs a current `geo` signal: `report_performance.py --sync-geo`
  after a `geo-monitor` run.
- **Not** for probing assistants (`geo-monitor`), first-party site trends
  (`seo-rank-tracking`), or fixing anything (route to `pub-research`/`pub-enhance`).

## What it checks / does

### 1. `scripts/report_performance.py`

Resolves the publication's own Search Console property (never the main site's cached one),
pulls page, query×page and date rows for the current window (ending three days back) and
page rows for the previous equal window, then reports: site totals with deltas,
impression-weighted position, per post `current/previous/delta` plus `state: awaiting |
receiving` keyed on the first day an impression was ever recorded (persisted), per-pillar
rollups, top 50 queries with the posts they drove, a zero-filled daily series, and plain-
language insights (posts still awaiting after 21 days, the leading section, the biggest
mover). `--sync-geo` reads the latest `geo-monitor` brand-mention run and writes the GEO
opportunities state: prompts where a competitor is named more than the client, with a gap
score.

### 2. `scripts/refresh_triggers.py`

Flags posts with named triggers: `clicks_drop` (≥ `--drop-ratio` between the last two runs,
prior clicks ≥ `--min-prior-clicks`), `aged` (older than `--max-age-days` and never updated),
`never_indexed` (older than `--awaiting-days` with no impression), `dated_numbers` (a figure
dated more than a year back in the prose). `--queue` adds one `Refresh: <title>` spoke per
post (`refresh_of` set) so the planner schedules a real rewrite through research and enhance.

## Running it

> Run from the target repo root. `${CLAUDE_SKILL_DIR}` is this skill's directory.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/report_performance.py" --publication llm-billboard --period 30d
python3 "${CLAUDE_SKILL_DIR}/scripts/report_performance.py" --publication llm-billboard --sync-geo
python3 "${CLAUDE_SKILL_DIR}/scripts/refresh_triggers.py" --publication llm-billboard
python3 "${CLAUDE_SKILL_DIR}/scripts/refresh_triggers.py" --publication llm-billboard --queue --max-age-days 120
```

Flags: `report_performance.py` `--publication`, `--period`, `--sync-geo`, `--publications-dir`;
`refresh_triggers.py` `--publication`, `--drop-ratio`, `--min-prior-clicks`, `--max-age-days`,
`--awaiting-days`, `--queue`, `--publications-dir`.

## Expected output

```jsonc
{ "checked": true, "publication": "llm-billboard", "property": "sc-domain:llmbillboard.com",
  "window": { "start": "…", "end": "…" }, "previous_window": { "…": "…" },
  "site": { "current": { "clicks": 41, "impressions": 3120, "ctr": 0.0131, "position": 18.4 }, "previous": { "…": "…" }, "delta": { "…": "…" } },
  "posts": { "published": 14, "receiving": 9, "items": [ { "slug": "…", "state": "awaiting", "current": { "…": "…" } } ] },
  "pillars": [ { "section": "AI Search", "posts": 4, "receiving": 3, "current": { "…": "…" } } ],
  "top_queries": [ { "query": "…", "clicks": 6, "impressions": 210, "position": 9.8, "posts": ["…"] } ],
  "series": [ { "date": "…", "clicks": 1, "impressions": 90 } ],
  "insights": [ "9 of 14 published posts have received at least one Search Console impression." ],
  "geo_sync": { "synced": 12, "from_run": "…" }, "report_file": ".seo-engine/reports/pub-performance-<slug>-<stamp>.json" }
```
Without Search Console configured: `checked: false` with the env var to set (exit 1), but
`--sync-geo` still runs.

## State files

| File | Role | Written by | Read by |
|---|---|---|---|
| `.seo-engine/state/pub-performance-<slug>.json` | first-impression dates, run history (60 runs) | `report_performance.py` | `refresh_triggers.py`, itself |
| `.seo-engine/state/pub-geo-opportunities-<slug>.json` | GEO gaps from the latest mention run | `report_performance.py --sync-geo` | `pub-curate score_suggestions.py` |
| `.seo-engine/state/pub-mentions-<slug>.json` | brand-mention runs (input) | `geo-monitor track_brand_mentions.py` | `report_performance.py --sync-geo` |
| `.seo-engine/state/pub-refresh-<slug>.json` | last refresh check | `refresh_triggers.py` | audits |
| `.seo-engine/reports/pub-performance-<slug>-<stamp>.json` | dated report | `report_performance.py` | calling agent |

## How to interpret results

- **`awaiting` for the first two to three weeks is normal** on a new domain; the insight
  flags only posts past 21 days. A publication with most posts `awaiting` after six weeks
  has a crawl or quality problem — run `pub-site validate_site.py` and `seo-indexing`.
- **Position is impression-weighted**; a "worse" position with far more impressions usually
  means new queries arrived, not that rankings fell.
- **Pillar rollups tell you where authority is forming**; feed that back to `pub-curate`
  (priority flags), not into more posts on the winning pillar for their own sake.
- **Triggers are independent signals.** `dated_numbers` on a fresh post is a research
  defect; `clicks_drop` on an old one is a refresh candidate; `never_indexed` may mean retire.
- **GEO gap items are prompts, not keywords**: read them as the questions assistants get
  where a competitor is the answer today.

## Safe to auto-apply vs. human review

- **Safe without asking:** every report, `--sync-geo`, `--queue` (it only adds open spokes).
- **Ask first:** retiring a `never_indexed` post, or lowering trigger thresholds so most of a
  catalogue is flagged at once.

## Guardrails

- A refresh is a rewrite through research and enhance; this skill never touches
  `updated_at` (red-flags §3).
- Search Console data is treated as ~3 days late and never compared across windows of
  different length.
- No claim is made about causation; a rising pillar after a change is correlation.

## References

- [publication-playbook.md](../seo-references/publication-playbook.md) §7 (metrics and
  the named-vs-cited distinction), §4 (where refresh fits in the loop).
- [geo-playbook.md](../seo-references/geo-playbook.md) §9 (measurement discipline), §10
  (Bing feeds ChatGPT: indexing is a GEO precondition).
- [red-flags.md](../seo-references/red-flags.md) §3 (no freshness faking), §7.
- [api-reference.md](../seo-references/api-reference.md) — Search Console setup.

## Graceful degradation

Search Console is the only dependency of `report_performance.py`; without it the script says
which env var unlocks it and still performs `--sync-geo`. `refresh_triggers.py` works with no
keys (age and dated-number triggers) and gains the click and indexing triggers once
performance history exists.
