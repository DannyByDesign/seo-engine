---
name: seo-rank-tracking
description: Tracks Google ranking positions over time from Search Console's free position data (by query or page) and flags statistically meaningful position drops against a trailing baseline; optional live SERP spot-check for one keyword via DataForSEO/Ahrefs. Invoke for 'check our rankings', 'did we lose rankings', 'organic traffic dropped', or suspected algorithm-update impact. Not for finding new keyword opportunities (use seo-keyword-research) or the whole-site scheduled checkup (use seo-maintain).
---

# seo-rank-tracking

Ranking-position monitoring built on Google Search Console's own free position data
as the source of truth. GSC already holds real position data for every query/page
combination the site has impressions for — a paid SERP tracker answers a different
question (the exact position right now, from one location/device) and is reserved
here for validating a single already-suspicious data point, never for routine
whole-site tracking.

## When to use this skill

- A human or `seo-maintain` asks to check rankings, monitor keyword/page positions,
  or answer "did we lose rankings for X."
- Investigating an organic-traffic drop — the `drops` list establishes *which*
  queries/pages regressed and *when*, before handing off to `seo-technical-audit`
  (did something break?) or correlating with a known Google update.
- On a recurring cadence (weekly is reasonable — GSC position data only stabilizes
  over roughly a week of traffic) to keep the history current.
- Validating a GSC-reported drop against live reality, or watching a competitor's
  position for one priority keyword — `check_serp_position.py`, not the default path.
- **Not** for: finding new keyword opportunities → `seo-keyword-research`; the
  scheduled whole-site checkup → `seo-maintain`; vanity keyword counts — tracking
  scope is deliberately curated (`target_topics`) or impression-filtered.

## What it checks / does

1. **`track_rankings.py`** — pulls GSC search-analytics rows (`query`+`date` by
   default, `page`+`date` with `--dimension page`) over a rolling window (default
   90 days, ending 3 days before GSC's "today" to respect its reporting lag; GSC
   windows use Pacific-time dates — see common-setup § Integration availability).
   Rows are fully paginated up to `--max-rows`. Tracking scope: config.yml
   `target_topics` as a case-insensitive substring filter (query dimension), else
   every key with window impressions ≥ `--min-impressions` — useful before any
   curation exists. Rows are bucketed into impression-weighted ISO-week averages
   via the shared `gsc_trends` lib (the same methodology seo-maintain reuses); the
   trailing *partial* week is dropped, so "latest week" always means the latest
   **complete** week. A **drop** is flagged only when that week is worse than the
   trailing `--baseline-weeks` mean by ≥ `--drop-threshold` positions **and** the
   worsening exceeds the baseline's own week-to-week standard deviation — ordinary
   volatility on low-volume keys never flags. Query-dimension drops get
   `ranking_pages` context attached so there is a concrete URL to investigate.
   Improvements are recorded but never escalated: a drop can mean something just
   broke and compounds while unnoticed; a gain is not time-sensitive.
2. **`check_serp_position.py`** — supplementary single-keyword live check.
   DataForSEO (`serp_live`) is a genuine synchronous live fetch (preferred);
   Ahrefs answers from its own `organic_keywords` crawl index — a second,
   independently-lagged data point, not a live snapshot. Domain matching is
   subdomain-aware: a result on `blog.example.com` counts for `example.com`.

## Running it

> All commands below run from the **target repo root** (the repo that contains the
> website). State and reports land in `<repo>/.seo-engine/` — running from anywhere
> else writes state to the wrong repo. Set `SKILL_DIR` to this skill's resolved absolute directory before running these commands
> (see common-setup.md); no host-specific variable is required.

```bash
python3 "${SKILL_DIR}/scripts/track_rankings.py"

python3 "${SKILL_DIR}/scripts/track_rankings.py" --dimension page

python3 "${SKILL_DIR}/scripts/track_rankings.py" --days 60 --drop-threshold 5.0 --baseline-weeks 8

python3 "${SKILL_DIR}/scripts/track_rankings.py" --min-impressions 25 --max-rows 200000

python3 "${SKILL_DIR}/scripts/check_serp_position.py" --keyword "best running shoes"

python3 "${SKILL_DIR}/scripts/check_serp_position.py" --keyword "best running shoes" --location-code 2826 --language-code en

python3 "${SKILL_DIR}/scripts/check_serp_position.py" --keyword "best running shoes" --domain competitor.com --source ahrefs
```

`--min-impressions` does double duty: the fallback tracking-scope floor *and* the
latest-week reliability floor (a position computed from a handful of impressions is
too noisy to act on, so the drop check is suppressed for that key that week).

## Expected output

`track_rankings.py` (stdout + report file), trimmed to the load-bearing fields:

```jsonc
{
  "dimension": "query",
  "summary": {
    "distinct_keys_returned_by_gsc": 6800, "distinct_keys_tracked_this_run": 340,
    "tracking_scope": "impression_threshold",
    "gsc_hit_cap": false,
    "drops_flagged": 6, "improvements_noted": 11
  },
  "drops": [{
    "key": "core web vitals checklist",
    "latest_week_start": "2026-06-29", "latest_position": 14.8,
    "latest_week_impressions": 620,
    "baseline_avg_position": 8.1, "baseline_stdev": 0.9, "baseline_weeks_used": 4,
    "position_delta": 6.7,
    "ranking_pages": [{ "page": "https://example.com/blog/cwv-checklist", "impressions": 590, "position": 15.1 }]
  }],
  "improvements": [ ],
  "setup_notes": ["GSC window ...", "Tracking scope ..."],
  "history_file": ".seo-engine/state/rank-history.json",
  "report_file": ".seo-engine/reports/rank-tracking-<stamp>.json"
}
```

`check_serp_position.py`:

```jsonc
{
  "keyword": "best running shoes", "domain": "example.com",
  "check": { "source": "dataforseo", "found": true, "position": 6,
             "matched_url": "https://example.com/best-running-shoes",
             "top_10_context": [ { "rank_absolute": 1, "domain": "...", "url": "...", "title": "..." } ],
             "note": "..." },
  "history_file": ".seo-engine/state/serp-check-history.json",
  "history_entries_for_this_keyword": 3
}
```

## State files

| File (under `.seo-engine/`) | Role | Written by | Read by |
|---|---|---|---|
| `state/rank-history.json` | daily GSC rows for **tracked keys only**, deduped by dimension→key→date; grows across runs regardless of `--days` | `track_rankings.py` | `track_rankings.py` (this skill only) |
| `state/serp-check-history.json` | ad-hoc live-check log per `keyword::domain::source`, capped per key | `check_serp_position.py` | `check_serp_position.py` |
| `reports/rank-tracking-<stamp>.json` | dated run report | `track_rankings.py` | human/agent (terminal output) |

`rank-history.json` is a curated record of the keys this skill watches, **not** a
mirror of everything GSC returned — untracked keys are deliberately not persisted.

## How to interpret results

1. **`drops` is the list to act on; `improvements` is informational.** Never open an
   investigation off an improvement.
2. **A flagged drop is an investigation lead, not a diagnosis.** In order: (a) hand
   `ranking_pages` (query dimension) or the key itself (page dimension) to
   `seo-technical-audit` — status regression, accidental noindex, canonical change,
   CWV regression coinciding with the drop week (red-flags §4 is the lens); (b) if
   nothing technical, check whether the drop date lines up with a known Google
   core/spam update before assuming a site-side cause; (c) validate with
   `check_serp_position.py` — a large live-vs-GSC mismatch is more likely GSC's own
   averaging/rounding/lag than a real discrepancy, and the live check is the
   tie-breaker (one exact moment/location/device vs. GSC's aggregate).
3. **`baseline_stdev` is the volatility context** — the gate already accounts for
   it, but when triaging several drops, prioritize low-stdev, high-impression keys.
4. **`gsc_hit_cap: true`** means the row set was truncated — treat absence as
   unknown, not zero, and raise `--max-rows` for full coverage.
5. **A drop whose `ranking_pages` is empty or impression-starved** can mean the page
   stopped ranking for the query entirely — higher priority than a same-size slip.
   If a key's *impressions* collapsed rather than its position, that is an
   indexing/visibility question — hand off to `seo-indexing`.

## Safe to auto-apply vs. human review

This skill **only observes and reports** — it never changes content, code, or config.

Safe without asking:
- Re-running `track_rankings.py` on a schedule (read-only against GSC).
- Running `check_serp_position.py` to validate one flagged drop (consumes paid API
  budget where configured — deliberate, per-keyword, never bulk).
- Handing a drop's `ranking_pages`/key to `seo-technical-audit` as *its* input.
- Appending to this skill's own history files.

Human review first:
- Any conclusion that a drop was *caused* by a specific change — this skill
  establishes *that* and *when*, never *why*.
- Any remediation itself — owned by `seo-technical-audit`, `seo-redirects`, or
  `seo-content-optimize` under their own rules.
- Declaring a drop "not worth investigating" — the script has no notion of
  page/query business value; a human or `seo-maintain` makes that call.

## Guardrails

- red-flags §4 (silent technical failures) is the investigation lens; red-flags §6
  (the meta-rule) vetoes speculative content edits to "win back" a position —
  escalate unless the fix is an unambiguous technical correction.
- Never respond to a drop with bulk resubmission/re-crawl requests — that is
  `seo-indexing` territory, with its own guardrails.
- Never promote `check_serp_position.py` into the default tracking mechanism — GSC
  is free and sufficient for trend detection; paid SERP checks validate single
  suspicious data points.

## References

- [common-setup.md](../../shared/seo-references/common-setup.md) — paths/cwd rules, config
  and env resolution, GSC property auto-resolution and Pacific-time windows.
- [api-reference.md](../../shared/seo-references/api-reference.md) — GSC method and quotas;
  DataForSEO vs. Ahrefs auth/cost models (why DataForSEO is preferred live).
- [red-flags.md](../../shared/seo-references/red-flags.md) — §4 technical failure classes;
  §6 the meta-rule.
- [seo-playbook.md](../../shared/seo-references/seo-playbook.md) — helpful-content framing
  for any downstream remediation.

## Graceful degradation

Generic philosophy: common-setup § Graceful degradation. Skill-specific:

- **GSC is the hard requirement.** Without it `track_rankings.py` prints the exact
  remediation (`GOOGLE_APPLICATION_CREDENTIALS` or `GSC_SERVICE_ACCOUNT_JSON`, plus
  service-account access on the property) and exits non-zero.
- **DataForSEO (`DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD`) or Ahrefs
  (`AHREFS_API_KEY`) unlock `check_serp_position.py` only.** With neither, it
  explains what each unlocks and exits 0 — the optional check being unavailable is
  not a failure of the skill.
- `target_topics` in config.yml is optional; the impression-threshold fallback
  keeps the skill useful from the very first run.
