---
name: seo-content-optimize
description: Improves the substantive quality of existing on-page content — adding citations/sources, direct quotations, and concrete statistics to unsupported claims, and refreshing pages with a genuine, verified staleness signal (not a timestamp bump). Invoke when a user asks to "improve content quality," "make this page more citable/authoritative," "check for outdated content," or when seo-maintain/seo-technical-audit surfaces thin or stale-flagged pages — never to increase publishing volume or output new pages.
---

# seo-content-optimize

This is the highest policy-risk skill in the system: every other skill audits
metadata, technical plumbing, or structure; this one is the closest to
rewriting words a real visitor will read. **The red-flags veto layer governs
everything here, not just informs it** — see Guardrails before proposing or
applying any change.

## When to use this skill

- A user asks to improve content quality, credibility, or "citability" of a
  specific page or section.
- `seo-maintain`'s opportunity ranking or `seo-technical-audit` flags
  `thin_content` and dispatches here.
- A user asks to check for outdated/stale content on the site.
- As part of a GEO-improvement request — but only for the one evidence-backed
  content tactic this system endorses (below), never as a pretext to
  restructure content into lists/FAQs for citation purposes (geo-playbook §5
  refutes that specific claim, not just "unproven").
- **Not** for increasing publishing volume, generating new pages to "cover"
  a topic, or any request that's actually asking for more content rather than
  better content — refuse or redirect those.

## The one evidence-backed content tactic this skill applies

Per geo-playbook §5: adding citations/sources, direct quotations, and
concrete statistics to substantive claims is the one content-level GEO lever
with disclosed-methodology evidence behind it — and it's simply good writing,
which is why it's durable rather than a fragile hack. Concretely:

- A vague claim becomes a sourced one — **only** if the number/source can
  actually be verified. Never invent a statistic to satisfy this pattern; a
  fabricated statistic is worse than no statistic, on both trust and
  factual-accuracy grounds.
- A claim attributed to an expert, standard, or study gets an actual
  citation/link or direct quotation instead of unsourced restated prose.

**What this does NOT mean:** do not restructure content into bullet lists,
added headers, or FAQ blocks as a "citation booster" — geo-playbook §5 is
explicit this is a documented misattribution, not a softer version of the
real finding. Do not add schema.org/JSON-LD under a GEO justification (that's
`seo-structured-data`'s scope, and not a citation lever there either — see
geo-playbook §3). Do not add or treat `llms.txt` as relevant here — measurably
not a citation lever (geo-playbook §1).

## What it checks / does

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
# First run on a site: archives a baseline snapshot, produces no candidates yet.
python3 "${CLAUDE_SKILL_DIR}/scripts/find_staleness_signals.py"

# Re-run later (default refuses a baseline younger than 30 days -- a short
# window mostly just confirms "hasn't changed yet", not "has gone stale").
python3 "${CLAUDE_SKILL_DIR}/scripts/find_staleness_signals.py" --min-days-old 30

# Tune crawl size and how many unchanged-content pages get live-refetched.
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
citation/quotation/statistic per the tactic above. Never: change only a
"last updated" timestamp while leaving substance the same; swap the year
without checking whether the underlying substance changed too; invent a
statistic or citation to fill the pattern.

## Safe to auto-apply vs. human review

Safe to apply directly, without asking first:
- Updating a factual claim to a verifiably current value confirmable from the
  page's own other content, the site's other pages, or a source the agent can
  actually access and read.
- Adding a citation/link to a source already referenced elsewhere on the page
  or site but not linked at the specific claim, or a direct quotation from a
  source already in scope for the page.
- Rewording a relative-time phrase into an explicit, currently-accurate year
  or evergreen phrasing, once the underlying fact is confirmed still accurate.

Must be flagged for human review, not auto-applied:
- Any update to a claim, statistic, price, or fact the agent cannot verify
  from content already available to it — flag what's suspected stale and why.
- Any candidate where it's ambiguous whether the matched language is actually
  stale vs. correct historical narration — when in doubt, flag.
- `version_reference` matches specifically — confirming whether a cited
  version is superseded requires domain knowledge this skill cannot assume;
  flag with the specific version string found.
- Any case touching more than a handful of pages with the same kind of edit
  in one pass — re-verify each is written from that page's own content, not a
  shared template, before batching.

Never do, full stop:
- Treat a staleness candidate as license to add pages, expand scope beyond
  the flagged page, or "refresh" content with no actual staleness signal.
- Restructure a page into lists/headers/FAQ format and describe that as the
  fix for a staleness or citation finding.
- Bump a "last updated" date as part of, or instead of, a substantive fix.

## Guardrails

- **Never increase publishing volume as an end in itself** — red-flags §1
  (scaled content abuse); this skill edits existing pages for quality only.
- **Never freshness-fake** — red-flags §3; a suspiciously new date on stale
  content destroys reader trust immediately, and this is exactly what
  Google's helpful-content guidance targets.
- **Never produce templated or programmatic content with no per-page
  differentiation** — red-flags §1, doorway pages.
- **Every proposed change must be justifiable in one sentence as "this makes
  the page more useful to a real reader"**, independent of any search engine
  or AI assistant existing — seo-playbook §1; red-flags §6, the meta-rule. If
  you can't state that sentence honestly, refuse or downgrade the change to a
  flagged recommendation rather than auto-applying it.

## References

- [common-setup.md](../seo-references/common-setup.md) — paths/cwd rules,
  the shared snapshot-store contract.
- [seo-playbook.md](../seo-references/seo-playbook.md) §1 — the people-first
  governing principle; §7 — content freshness tied to real signal, never
  time-since-edit, the direct basis for this skill's detection design.
- [geo-playbook.md](../seo-references/geo-playbook.md) §5 — citations/
  quotations/statistics as the one evidence-backed tactic, lists/headers/FAQ
  explicitly not supported; §7 — AI-citation freshness data (no "13-week rule").
- [red-flags.md](../seo-references/red-flags.md) §1, §3, §6.

## Graceful degradation

Generic philosophy: common-setup § Graceful degradation. Skill-specific: this
entire skill runs with **zero API keys** — the crawler and the staleness
live-fetch are both free and unauthenticated. There is no paid integration
that unlocks additional capability specific to this script; judging whether
prose is substantively better is not something any of this system's paid
APIs do.
