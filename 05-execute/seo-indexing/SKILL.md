---
name: seo-indexing
description: Manages what search engines have actually indexed — auto-discovers/confirms/submits the sitemap, runs GSC URL Inspection to surface index-coverage and canonical-mismatch issues, and submits caller-supplied or snapshot-diffed changed URLs to IndexNow for Bing/Yandex/etc. (never Google). Invoke after publishing/updating/deleting pages, after a sitemap change, when GSC coverage or "why isn't this indexed" comes up, or during a routine seo-maintain pass. Not for keyword/ranking research (seo-rank-tracking) or crawl audits (seo-technical-audit).
---

# seo-indexing

Keeps search engines' actual index state in sync with what the site wants indexed: sitemap
registration, GSC coverage/canonical checks on important pages, and IndexNow submission for
changed URLs on the engines that support it.

## When to use this skill

- After publishing, updating, or deleting pages — submit changed URLs via IndexNow; confirm
  sitemap freshness for Google.
- After changing the sitemap itself (new file, new URL, moved location) — confirm registration.
- "Is this page indexed," "why isn't X showing up in Google," or GSC's Coverage report comes up.
- As part of a routine `seo-maintain` cycle, especially right after its crawl-snapshot diff
  surfaces newly-changed URLs — feed those into this skill's IndexNow step.
- **Not** for keyword/ranking research (`seo-keyword-research`, `seo-rank-tracking`), general
  crawl/technical health (`seo-technical-audit`), or content quality (`seo-content-optimize`).

## The one hard fact this skill must never contradict

**Google and Baidu do not participate in IndexNow.** Submitting a URL reaches Bing, Yandex,
Naver, Seznam.cz, Yep, Amazon (and Yahoo per Bing's own materials) — never Google. For Google,
the only levers are **sitemaps** and **URL Inspection**, both via Search Console. Never present
IndexNow as something that helps a page get into Google.

The flip side, per `geo-playbook.md` §10: **Bing's index is what ChatGPT search reads from** —
IndexNow submission and Bing Webmaster sitemap registration are also first-order GEO actions, not
housekeeping for "a search engine nobody uses." A page absent from Bing is a floor-level blocker
for ChatGPT-citation odds, worth fixing before any content-level GEO theory.

IndexNow also does **not guarantee indexing**, even on engines it reaches — it only signals a
change and may earn a *prioritized*, not immediate, crawl visit; the engine still applies its own
quality/quota gating. Submitted URLs **count toward the site's own crawl quota** — never build a
"resubmit the whole sitemap" habit, only genuinely new/changed/deleted URLs.

## What it checks / does

`scripts/sync_indexing.py` runs three independent jobs — each reports its own "not configured"
status rather than failing the whole run:

1. **Sitemap sync (GSC)** — lists what's registered, submits `--sitemap-url` if not already
   registered (or `--force-resubmit`). **Auto-discovers** the sitemap when `--sitemap-url` is
   omitted: robots.txt `Sitemap:` declarations first, then `/sitemap.xml`, `/sitemap_index.xml`,
   `/wp-sitemap.xml` in that order, first candidate that returns 200 and parses wins
   (`discovery_note` records what was found). A `sitemapindex` is followed one level deep, up to
   50 child sitemaps.
2. **URL Inspection sample (GSC)** — homepage, any `--inspect-url`, plus (if GSC configured) real
   top-clicked pages from the last 28 days. Reports index verdict, coverage/indexing/robots
   state, **declared vs. Google-selected canonical** (flagging mismatches), last crawl time, and
   rich-results verdict.
3. **IndexNow submission** — for changed URLs the caller supplies via `--changed-url` (repeatable),
   `--changed-urls-file`, or `--changed-from-snapshots` (below). This script deliberately does
   **not** auto-detect "what changed" on its own beyond that explicit snapshot-diff option.

### Where changed-URL lists come from

`--changed-from-snapshots` derives them itself: takes the latest crawl snapshot (must be <=48h
old) and its most recent **comparable** baseline (same `max_pages`, neither truncated — see
common-setup.md's Snapshot contract), then diffs `content_hash` per URL. A page present in both
snapshots with a changed hash is included; brand-new pages are not (no prior hash to compare).
**No comparable baseline → the script refuses rather than guessing** — `snapshot_diff_note`
explains why (no prior snapshot at all, current crawl truncated, or nothing comparable) and no
URLs are derived from that source. This keeps "what changed" grounded in an actual content diff.
Merges with any explicit `--changed-url`/`--changed-urls-file` entries, deduped.

## Running it

> All commands below run from the **target repo root** (the repo that contains the
> website). State and reports land in `<repo>/.seo-engine/` — running from anywhere
> else writes state to the wrong repo. `${CLAUDE_SKILL_DIR}` is set by Claude Code to
> this skill's directory and works for both the symlink and plugin install.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/sync_indexing.py"

python3 "${CLAUDE_SKILL_DIR}/scripts/sync_indexing.py" --changed-from-snapshots

python3 "${CLAUDE_SKILL_DIR}/scripts/sync_indexing.py" \
  --changed-url https://example.com/blog/new-post --changed-url https://example.com/pricing

python3 "${CLAUDE_SKILL_DIR}/scripts/sync_indexing.py" --changed-urls-file changed-urls.txt
python3 "${CLAUDE_SKILL_DIR}/scripts/sync_indexing.py" \
  --inspect-url https://example.com/ --inspect-url https://example.com/pricing --no-sitemap-sync

python3 "${CLAUDE_SKILL_DIR}/scripts/sync_indexing.py" --sitemap-url https://example.com/sitemap.xml --force-resubmit
python3 "${CLAUDE_SKILL_DIR}/scripts/sync_indexing.py" --no-inspect --changed-urls-file changed-urls.txt
```

Flags: `--sitemap-url`, `--force-resubmit`, `--no-sitemap-sync`, `--inspect-url` (repeatable),
`--max-inspect` (default 10 — see Guardrails for why), `--no-inspect`, `--changed-url`
(repeatable), `--changed-urls-file`, `--changed-from-snapshots`, `--indexnow-key-location`
(override when the key file isn't served at the default `https://{host}/{key}.txt`).

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/setup_indexnow_key.py"
python3 "${CLAUDE_SKILL_DIR}/scripts/setup_indexnow_key.py" --dir public
python3 "${CLAUDE_SKILL_DIR}/scripts/setup_indexnow_key.py" --existing-key-file public/<key>.txt
python3 "${CLAUDE_SKILL_DIR}/scripts/setup_indexnow_key.py" --force
```

`setup_indexnow_key.py` auto-scans the target dir for a reusable existing key file first (valid
only if the file's content exactly equals its filename stem); refuses a `build_output_dir` target
unless `--allow-build-output`; prints the `INDEXNOW_API_KEY=<value>` line to add to `.env` plus
the post-deploy verification URL. The key file is a public, harmless token, safe to commit.

## Expected output

`sync_indexing.py` (also written to `.seo-engine/reports/indexing-sync-<stamp>.json`):
```jsonc
{
  "generated_at": "...", "site_url": "https://example.com", "scope_note": "...",
  "sitemap": { "checked": true, "sitemap_url": "...", "already_registered": false,
               "submitted_this_run": true, "discovery_note": "..." },
  "url_inspection": { "checked": true, "pages_inspected": 8, "pages_with_canonical_mismatch": 0,
    "pages": [ { "url": "...", "verdict": "PASS", "coverage_state": "Submitted and indexed",
      "declared_canonical": "...", "google_selected_canonical": "...", "canonical_mismatch": false } ] },
  "indexnow": { "checked": true, "submitted": true, "accepted": true, "url_count": 2,
    "participants": ["Bing", "Yandex", "..."], "disclaimer": "...",
    "snapshot_diff_note": "--changed-from-snapshots: 3 page(s) with changed content_hash between ..." },
  "report_file": ".seo-engine/reports/indexing-sync-<stamp>.json"
}
```

If an integration isn't configured, that section reports `"checked": false` plus a `"reason"`
naming the exact env var — never a crash, never a silent no-op. A submitted URL list on a
different host than `site_url` surfaces as a clean `indexnow.error` (host-mismatch check runs
before any network call), not an exception.

`setup_indexnow_key.py` success: `{ "reused_existing_key": bool, "key_file": "...", "key": "...",
"env_var_line": "INDEXNOW_API_KEY=...", "next_steps": [...] }`. Failure:
`{ "error_type": "static_source_unknown" | "refused_build_output_dir" | "dir_not_found" |
"key_file_content_mismatch", "error": "..." }`.

## State files

| File (under `.seo-engine/`) | Role | Written by | Read by |
|---|---|---|---|
| `state/crawls/` (shared snapshot store) | consumes (via `--changed-from-snapshots`) | see [common-setup.md § Snapshot contract](../../shared/seo-references/common-setup.md) | this skill + any other |
| `reports/indexing-sync-<stamp>.json` | dated run report | `sync_indexing.py` | calling agent |

`setup_indexnow_key.py` writes only the public verification file (`<key>.txt`) into the target
static-source directory — not under `.seo-engine/`.

## How to interpret results

- **`sitemap.already_registered: false` before submission is normal on first run** — re-running
  after `submitted_this_run: true` should show `already_registered: true`.
- **`url_inspection.pages_with_canonical_mismatch > 0` is a real integrity signal**, not noise
  (seo-playbook.md §5). If `google_selected_canonical` points **off-domain**, treat it as a
  potential cross-domain canonical hijack — a security incident (red-flags.md §4) — escalate to
  `seo-redirects` immediately; never auto-correct.
- **`coverage_state` other than `"Submitted and indexed"`** on a page you expect indexed is worth
  a look, but read `robots_txt_state`/`page_fetch_state`/`indexing_state` for *why* first — some
  exclusions are intentional; don't guess, flag for review.
- **`indexnow.checked: false` with no `INDEXNOW_API_KEY` is a normal, common state** — Google was
  never going to receive IndexNow submissions regardless.
- **`indexnow.accepted: true` means the batch was accepted for processing — nothing more.** Never
  report an IndexNow submission as "the page is now indexed" or "Google was notified" — both false.
- A non-2xx IndexNow status almost always means the key verification file isn't reachable yet at
  `https://{host}/{key}.txt`, or submitted URLs don't share the key's host.

## Safe to auto-apply vs. human review

**Safe to apply directly:** re-registering an already-known, already-live sitemap (informational,
reversible); running URL Inspection (read-only); submitting a caller-supplied or
snapshot-diff-derived changed-URL list to IndexNow; writing a fresh IndexNow key file into a
directory that doesn't already have one (inert until referenced by `INDEXNOW_API_KEY`).

**Must be flagged for human review:** any cross-domain canonical mismatch (always escalate, never
auto-correct); a `noindex`/exclusion state you're not sure was intentional (flag for
`seo-technical-audit`, don't remove based on this output alone); rotating an existing IndexNow key
(`--force` invalidates it everywhere it's referenced — confirm first); a proposed changed-URL list
that looks like the whole site rather than a genuine delta (wastes crawl quota for no benefit).

## Guardrails

- Never present IndexNow submission as reaching Google.
- Never report `indexnow.accepted: true` as "indexed" — no per-URL confirmation exists.
- `--max-inspect` defaults to 10 specifically to stay well inside GSC's own per-property quota
  (600 QPM / 2,000 QPD) even on frequent scheduled runs — raise deliberately, not by default.
- Cross-domain canonical mismatches escalate, never auto-correct (seo-playbook.md §5, red-flags.md §4).
- Never build a "resubmit everything to IndexNow" habit — it wastes crawl quota for no benefit.

## References

- [common-setup.md](../../shared/seo-references/common-setup.md) — paths, config resolution, snapshot contract.
- [seo-playbook.md](../../shared/seo-references/seo-playbook.md) §5 — canonicalization/indexing hygiene;
  why declared-vs-selected canonical diffing is a legitimate automated check.
- [red-flags.md](../../shared/seo-references/red-flags.md) §4 — IndexNow misconceptions, canonical
  hijacking, accidental noindex; all directly govern this skill's behavior.
- [geo-playbook.md](../../shared/seo-references/geo-playbook.md) §10 — Bing as ChatGPT's search index; the
  basis for treating this skill's Bing-facing actions as GEO, not just classic SEO housekeeping.

## Graceful degradation

Generic philosophy: [common-setup.md § Graceful degradation](../../shared/seo-references/common-setup.md).
Zero paid keys required — this skill only touches free integrations (GSC, IndexNow). With neither
`GOOGLE_APPLICATION_CREDENTIALS`/`GSC_SERVICE_ACCOUNT_JSON` nor `INDEXNOW_API_KEY` set, every
section reports `"checked": false` with the exact env var to set next; the script still runs and
still writes a report. GSC setup unlocks both sitemap sync and URL Inspection at once (same
credential). Run `setup_indexnow_key.py` once, set the printed key, deploy, and IndexNow
submission unlocks on the next `sync_indexing.py` run.
