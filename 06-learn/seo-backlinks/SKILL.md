---
name: seo-backlinks
description: Read-only backlink profile monitoring — tracks new/lost backlinks since the last run, flags broken backlinks (external links to URLs on this domain that now 404 or redirect badly), and surfaces competitor-gap awareness for research context. Invoke on a recurring maintenance cadence, after a Domain Rating/referring-traffic change, or when seo-content-optimize/seo-keyword-research needs competitor-overlap context. Never acquires or automates outbound link-building — do not extend it expecting outreach or guest-post suggestions.
---

# seo-backlinks

## Hard boundary — read this first

**This skill is read-only monitoring and reporting, full stop.** Per
red-flags §1 ("Link spam / link schemes"): this system does not build,
recommend, or automate outbound link acquisition of any kind —
`seo-backlinks` is a **monitoring** skill (tracking your own profile and
competitors' for research), never an acquisition tool. If you are tempted to
add outreach logic, guest-post suggestions, or a "link opportunities to
pursue" list because it seems adjacent to "backlink monitoring," don't — it
is explicitly out of scope for this skill and this system.

The one exception genuinely in-scope, **broken backlinks**, is not link
acquisition: an external site *already* links here and the link is losing
value because *this site's own server* now returns a bad response. Fixing
that is fixing your own site's behavior toward a link you already have.
Route the actual fix to `seo-redirects`; this skill only detects and reports it.

## When to use this skill

- On a recurring maintenance cadence, as part of `seo-maintain`'s continuous
  loop, to catch newly lost or newly broken backlinks before they compound.
- After noticing a Domain Rating, referring-domain count, or referral-traffic
  change and wanting to know whether backlinks explain it.
- Before or during `seo-content-optimize` / `seo-keyword-research` work, when
  competitor-overlap context would help prioritize content decisions.
- After a migration, redesign, or URL restructuring — broken backlinks are a
  common, easy-to-miss casualty, surfaced here from the *external* link side
  (complementing `seo-technical-audit`'s internal-link checks).
- **Not** for: any form of link acquisition, outreach, or "link building" —
  this skill does not do that, ever (see hard boundary above).

## What it checks / does

Runs `scripts/monitor_backlinks.py`:

1. **Selects a provider** — Ahrefs (`AHREFS_API_KEY`) preferred, else
   DataForSEO (`DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD`); `--provider` forces
   one. Neither configured → structured "not configured" report naming both
   options, exits cleanly.
2. **Fetches the current backlink list**, paginated oldest-first
   (`first_seen:asc`) up to `--cap` (default 1000, total across pages, for a
   deterministic window run-over-run). Ahrefs also calls its dedicated
   `broken_backlinks` endpoint; DataForSEO has none, so broken backlinks are
   derived by filtering the fetched list for a target-status ≥ 400 (rows
   without a status field are never guessed into "broken").
3. **Checks profile totals first** (`profile_totals` in the report). If the
   provider's total exceeds `--cap` (or the fetch fills the cap and the total
   is unknown), link-level new/lost diffing is **skipped**
   (`diff.skipped_reason: "backlink_count_exceeds_cap"`) in favor of a
   referring-*domain*-level diff over the stable window (`diff.mode`) — a
   truncated link window would fabricate churn.
4. **Snapshots** the normalized list to `.seo-engine/state/backlinks-<date>.json`.
   An empty or failed fetch **never overwrites** the stored snapshot — it is
   only written after a successful, confirmed fetch (`snapshot_file: null` +
   `skipped_reason: "empty_fetch_unconfirmed"` otherwise).
5. **Diffs** against the most recent prior snapshot: `new_backlinks` requires
   absence before **and** `first_seen` within 7 days of the previous run
   (otherwise `appeared_but_not_recent`); `lost_backlinks` requires the
   provider's `is_lost` flag **or** absence on 2 consecutive runs (a first
   miss is `possibly_lost`, low severity, tracked via a persisted
   `missing_streak`). First-ever run → `is_baseline: true`, empty new/lost
   lists — never mislabeled as "100% new."
6. **Flags broken backlinks** as structured findings — the one actionable
   category. A report is written on every path, including not-configured and
   fetch-error runs.
7. **Optionally** (`--competitor-gap [DOMAIN]`) reports competitor-gap
   awareness — Ahrefs `organic_competitors`, or DataForSEO
   `competitors_domain`/`domain_intersection` when a competitor is named —
   always under a `scope_note` reiterating informational-only.

## Running it

> All commands below run from the **target repo root** (the repo that contains the
> website). State and reports land in `<repo>/.seo-engine/` — running from anywhere
> else writes state to the wrong repo. `${CLAUDE_SKILL_DIR}` is set by Claude Code to
> this skill's directory and works for both the symlink and plugin install.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/monitor_backlinks.py"

python3 "${CLAUDE_SKILL_DIR}/scripts/monitor_backlinks.py" --provider ahrefs
python3 "${CLAUDE_SKILL_DIR}/scripts/monitor_backlinks.py" --provider dataforseo

python3 "${CLAUDE_SKILL_DIR}/scripts/monitor_backlinks.py" --cap 2000

python3 "${CLAUDE_SKILL_DIR}/scripts/monitor_backlinks.py" --no-diff

python3 "${CLAUDE_SKILL_DIR}/scripts/monitor_backlinks.py" --competitor-gap

python3 "${CLAUDE_SKILL_DIR}/scripts/monitor_backlinks.py" --provider dataforseo --competitor-gap competitor.com --competitor-limit 30
```

## Expected output

```jsonc
{
  "provider_used": "ahrefs",
  "setup_notes": [ "..." ],
  "scope_note": "This skill is READ-ONLY monitoring. It never acquires, builds, ...",
  "profile_totals": { "backlinks": 214, "referring_domains": 58, "source": "ahrefs.backlinks_stats" },
  "current_backlink_count": 214,
  "snapshot_file": ".seo-engine/state/backlinks-<date>.json",
  "diff": {
    "is_baseline": false, "mode": "link",
    "previous_snapshot_date": "2026-06-28T09:00:00+00:00",
    "new_backlinks": [ { "url_from": "...", "url_to": "...", "first_seen": "...", "domain_rating_source": 55 } ],
    "lost_backlinks": [ { "...": "same shape", "lost_evidence": "provider_is_lost" } ],
    "possibly_lost": [ { "...": "...", "missing_streak": 1 } ],
    "new_count": 3, "lost_count": 1
  },
  "broken_backlink_count": 1,
  "broken_backlinks": [
    { "type": "broken_backlink", "severity": "high", "url_to": "https://example.com/deleted-page",
      "url_from": "https://external-site.com/article", "http_code": 404,
      "auto_fixable": false, "human_review_reason": "..." }
  ],
  "findings": [ "same array as broken_backlinks -- top-level alias for uniform scanning" ],
  "competitor_gap": { "organic_competitors": { "...": "..." }, "scope_note": "Informational only ..." },
  "report_file": ".seo-engine/reports/backlinks-<date>.json"
}
```

## State files

| File (under `.seo-engine/`) | Role | Written by | Read by |
|---|---|---|---|
| `state/backlinks-<date>.json` | dated snapshot of the current normalized backlink list + `missing_streaks`; diffed against the most recent prior dated file; only written after a confirmed fetch | `monitor_backlinks.py` | `monitor_backlinks.py` (this skill only) |
| `reports/backlinks-<date>.json` | dated run report, written on every path including not-configured/error | `monitor_backlinks.py` | human/agent (terminal output) |

## How to interpret results

- **`provider_used: null`** → no provider configured. Read `setup_notes` for
  the exact env var(s). Nothing was fetched; an unconfigured optional
  integration is not an error state.
- **`diff.is_baseline: true`** → first-ever recorded run. Treat
  `current_backlink_count` as the starting point; meaningful new/lost data
  starts on the *next* run.
- **`diff.mode: "referring_domain"`** → the profile exceeded `--cap`;
  link-level diffing was skipped in favor of domain-level. Raise `--cap` for
  link-level diffing.
- **`new_backlinks` / `lost_backlinks`** → purely observational. A
  `lost_backlinks` entry is not an action item — do not attempt to "win the
  link back." `possibly_lost` entries may still reappear next run.
- **`broken_backlinks`** → the one category with a concrete fix path.
  `severity: "high"` means a 5xx or unreachable target; `"medium"` covers
  other 4xx. The fix is almost always a 301 redirect from the dead URL to its
  current equivalent — hand off to `seo-redirects` once the destination is
  confirmed. This script never applies the fix itself.
- **`competitor_gap`** → market/topic research context, nothing else. If you
  find yourself drafting outreach or a "prospects" list from this output,
  stop — see the hard boundary above.

## Safe to auto-apply vs. human review

**Nothing this script reports is auto-applied by the script itself** — a
read-only diagnostic (the agent/human decides what to change).

Never do, full stop (scope, not severity):
- Build, propose, or automate any outbound link acquisition, outreach,
  guest-post pitch, directory submission, or "link building suggestion" — no
  matter how adjacent it seems to "monitoring."
- Treat `lost_backlinks` as something to "win back" via outreach.
- Treat the competitor-gap domain list as a target list for anything other
  than content/keyword research context.

Human review first:
- Any `broken_backlink` finding's proposed remedy (301 redirect, restore the
  deleted page, or accept the loss) — the correct destination requires
  business knowledge this script does not have; route to `seo-redirects` for
  implementation, don't guess the destination here.
- A broken backlink whose target URL pattern suggests a larger, site-wide
  migration issue (many broken backlinks converging on an old path structure)
  — treat as a `seo-technical-audit`-level regression, not a one-off fix.

## Guardrails

- red-flags §1 (Link spam / link schemes) — the authoritative source for this
  skill's entire scope boundary; re-read before modifying this skill in any
  way that could be read as adding acquisition/outreach capability.
- red-flags §4 (technical mistakes that silently tank a site) — general
  redirect-chain/loop guidance governing how a broken-backlink fix should be
  implemented once handed to `seo-redirects`.
- geo-playbook §6 — brand mentions correlate with AI visibility more strongly
  than backlinks do; this skill's data is traditional-SEO/monitoring context,
  never a GEO lever, and must not be reframed as one.

## References

- [common-setup.md](../../shared/seo-references/common-setup.md) — paths/cwd rules,
  config and env resolution.
- [api-reference.md](../../shared/seo-references/api-reference.md) — Ahrefs API v3,
  DataForSEO sections: auth model, endpoint shapes, plan/rate-limit gating.
- [seo-playbook.md](../../shared/seo-references/seo-playbook.md) §5 — the "don't
  silently break existing equity" principle a broken backlink is one instance of.
- [red-flags.md](../../shared/seo-references/red-flags.md) §1 and §4.
- [geo-playbook.md](../../shared/seo-references/geo-playbook.md) §6.

## Graceful degradation

Generic philosophy: common-setup § Graceful degradation. Skill-specific:

- With neither `AHREFS_API_KEY` nor `DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`
  set, the script prints a structured "not configured" report naming both
  options and exits without error.
- With only one provider configured, it is used automatically — no flag
  required. With both, Ahrefs is preferred by default (dedicated
  broken-backlinks endpoint; DataForSEO's is derived); force DataForSEO with
  `--provider dataforseo` for cost or coverage reasons.
- `--competitor-gap` without DataForSEO and without a named competitor still
  works against Ahrefs (`organic_competitors`); a named competitor's
  link-source intersection requires DataForSEO (`domain_intersection`) — the
  report explains this via a `note` field rather than failing silently.
