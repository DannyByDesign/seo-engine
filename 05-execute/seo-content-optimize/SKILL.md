---
name: seo-content-optimize
description: Improves the substantive quality of existing on-page content — adding citations/sources, direct quotations, and concrete statistics to unsupported claims, and refreshing pages with a genuine, verified staleness signal (not a timestamp bump). Invoke when a user asks to "improve content quality," "make this page more citable/authoritative," "check for outdated content," or when seo-maintain/seo-technical-audit surfaces thin or stale-flagged pages — and research-backed first-party copy work selected through seo-growth.
---

# seo-content-optimize

This is the highest policy-risk skill in the system: every other skill audits
metadata, technical plumbing, or structure; this one is the closest to
rewriting words a real visitor will read. **The red-flags veto layer governs
everything here, not just informs it** — see Guardrails before proposing or
applying any change.

## When to use this skill

Use to improve existing copy or implement a research-backed new landing page, guide,
comparison or other useful content selected through `seo-growth`. A staleness finding is
one input, not a prerequisite for useful content work. Follow the current positioning and
copy brief in the growth workflow; the agent researches and writes rather than asking the
owner for complete copy.

Write for the reader's task: explain the offering, answer relevant questions, provide
credible proof and a working next action. Use citations, examples, calculations, headings
or FAQs when they help that task. No single formatting tactic or statistic quota establishes
search performance. Verify material facts and preserve the site's voice and design system.

## What it checks / does

Before writing or revising copy, read [seo-copywriting](../seo-copywriting/SKILL.md) and select
a varied reference packet for the target page. Record example IDs and useful techniques in
the work evidence. Write from current research and positioning, then review factual support,
reader usefulness, natural phrasing and accidental copying.
Run the copywriting skill's LanguageTool checker on finished prose and again after edits.
Resolve suggestions without changing factual meaning, names, numbers, quotations or useful
brand-specific phrasing. Record an unavailable checker as `not_checked`.

Runs `scripts/find_staleness_signals.py`. The script does **not** decide what
to write — it surfaces staleness candidates for a human/agent to judge; it
does not grade prose quality or citation density.

A page becomes a **staleness candidate** only when **both** hold:

1. **Content hash unchanged.** The script **always crawls fresh**
   (`snapshots.new_crawl` into the shared store — there is no flag to reuse an
   existing snapshot as "current" instead, since that would fabricate the diff) and
   compares each page's `content_hash` against an honest baseline chosen by
   `snapshots.find_baseline`: same site, same `max_pages`, neither side
   truncated, at least `--min-days-old` days older. Pages are matched by
   `urlnorm.canonical_key` of the final URL, so a slash/www alias never
   breaks the diff. No comparable baseline → `checked: false` with the exact
   refusal reason in `not_checked.content_hash_diff` — the script never diffs
   a crawl against itself or an incomparable snapshot.
2. **Live text contains real time-bound language.** For pages that pass step
   1, a fresh, unauthenticated HTTP GET (no rendering, no paid API) is
   regex-scanned for a hardcoded year older than the current year
   (`hardcoded_year`), relative-time phrasing like "last year"/"this year"
   (`relative_time_phrase`), an old copyright year (`copyright_year`), or a
   version-shaped token such as "Python 3.11" (`version_reference`; a bare
   decimal in price/rating context, e.g. "$49.99" or "rated 4.8 stars", is
   rejected).

Age alone or time-bound language alone is independently insufficient — a
`hardcoded_year` match on a page correctly narrating its own founding year as
settled history still appears in the output (the regex can't know intent),
which is why every candidate carries `context`: **read it before concluding
anything is actually outdated.**

Site-level **`template_boilerplate`**: a match string appearing on more than
half of the scanned pages (and at least 5 of them, e.g. a footer copyright
line) is reported once, separately, and excluded from every per-page
candidate (`copyright_year` boilerplate is `auto_fixable`; others are not).

## Running it

> All commands below run from the **target repo root** (the repo that contains the
> website). State and reports land in `<repo>/.seo-engine/` — running from anywhere
> else writes state to the wrong repo. `${CLAUDE_SKILL_DIR}` is set by Claude Code to
> this skill's directory and works for both the symlink and plugin install.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/find_staleness_signals.py"

python3 "${CLAUDE_SKILL_DIR}/scripts/find_staleness_signals.py" --min-days-old 30

python3 "${CLAUDE_SKILL_DIR}/scripts/find_staleness_signals.py" --max-pages 300 --fetch-limit 40
```

No API key required — the crawler and the staleness live-fetch are both free
and unauthenticated.

## Expected output

```jsonc
{
  "crawl_summary": { "pages": 240, "errors": 0, "non_200": 1 },
  "pages_analyzed": 240,
  "checked": true,
  "previous_snapshot": ".seo-engine/state/crawls/crawl-<UTCstamp>.jsonl",
  "previous_snapshot_age_days": 46.3,
  "pages_with_unchanged_content_hash": 58,
  "pages_live_fetched_for_language_scan": 58,
  "pages_skipped_due_to_fetch_limit": 0,
  "fetch_errors": [],
  "template_boilerplate": [ { "type": "template_boilerplate", "kind": "copyright_year",
                              "pages_matched": 58, "percent_of_scanned": 100, "auto_fixable": true } ],
  "candidate_count": 6,
  "candidates": [
    {
      "url": "https://example.com/guides/pricing-2024",
      "inbound_internal_link_count": 12,
      "unchanged_since": "crawl-<UTCstamp>.jsonl", "unchanged_for_days": 46.3,
      "staleness_signals_found": 3,
      "staleness_signals": [
        { "kind": "hardcoded_year", "match": "2024", "context": "...our updated 2024 pricing tiers..." },
        { "kind": "relative_time_phrase", "match": "this year", "context": "...we changed our plans this year..." }
      ],
      "detail": "Content hash unchanged for at least 46.3 day(s) AND live text contains 3 time-bound expression(s) ..."
    }
  ],
  "methodology_note": "...",
  "note": "This script only detects and reports candidates. It never edits content and never touches a timestamp. ...",
  "report_file": ".seo-engine/reports/content-staleness-<date>.json"
}
```

When `checked` is `false`, read `reason` and `not_checked.content_hash_diff` —
this run's crawl is still stored in the shared snapshot store as a future
baseline; it is a deliberate refusal to guess, not a bug.

## State files

| File (under `.seo-engine/`) | Role | Written by | Read by |
|---|---|---|---|
| `state/crawls/` (shared snapshot store) | consumes/produces | see common-setup.md § Snapshot contract | this skill + any other |
| `reports/content-staleness-<date>.json` | dated run report | `find_staleness_signals.py` | human/agent (terminal output) |

## How to interpret results and apply changes — this is agent judgment work

The script's job ends at a list of candidates with matched staleness
language. Everything past that is this skill's real work and is not
scriptable — deciding what to write requires reading the page, understanding
the domain, and knowing whether a fact is genuinely outdated.

**Step 1 — read each candidate's actual page content.** For every candidate,
read the full surrounding context of each `staleness_signals` entry, not just
the ~120-character `context` window. Decide per match: genuinely outdated
(the fix is real work) vs. correctly narrating settled history (a
false-positive candidate — do nothing).

**Step 2 — if genuinely stale, make a substantive fix, never a cosmetic one.**
Update the actual outdated fact, and where the claim lacks one, add a
citation/quotation/statistic per the page's actual reader need. Never: change only a
"last updated" timestamp while leaving substance the same; swap the year
without checking whether the underlying substance changed too; invent a
statistic or citation to fill the pattern.

## Safe to auto-apply vs. human review

Perform authorized source edits and agent factual/copy review. Existing broad growth scope
covers creating useful pages and improving existing ones. Research uncertain facts using
available sources; ask only for inaccessible owner facts or genuinely conflicting decisions.
Do not invent claims while waiting. Reuse existing deployment authority. Inspect source,
rendered output and actual links/forms before calling the intervention complete.

## Guardrails

No fabricated facts, fake freshness, plagiarism or mass near-duplicate pages. Every new page
needs distinct value and a discovery path. Use current product evidence for prices/features;
a search snippet or competitor claim is not proof about this product. Page length and cadence
are choices, not quality targets. Apply the current growth brief rather than making unrelated
sitewide changes because a staleness detector returned candidates.

## References

- [common-setup.md](../../shared/seo-references/common-setup.md) — paths/cwd rules,
  the shared snapshot-store contract.
- [seo-playbook.md](../../shared/seo-references/seo-playbook.md) §1 — the people-first
  governing principle; §7 — content freshness tied to real signal, never
  time-since-edit, the direct basis for this skill's detection design.
- [geo-playbook.md](../../shared/seo-references/geo-playbook.md) §5 — citations/
  quotations/statistics evidence and its scope limits; §7 — AI-citation freshness data (no "13-week rule").
- [red-flags.md](../../shared/seo-references/red-flags.md) §1, §3, §6.

## Graceful degradation

Generic philosophy: common-setup § Graceful degradation. Skill-specific: this
entire skill runs with **zero API keys** — the crawler and the staleness
live-fetch are both free and unauthenticated. There is no paid integration
that unlocks additional capability specific to this script; judging whether
prose is substantively better is not something any of this system's paid
APIs do.
