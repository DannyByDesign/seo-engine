---
name: geo-optimize
description: Audits AI-search (GEO) readiness — checks robots.txt against the per-vendor AI-crawler table so a site doesn't accidentally block ChatGPT/Claude/Perplexity/Bing crawlers, checks AI-crawler cloaking, flags JS-dependent content invisible to AI crawlers (none render JS), and can scaffold a narrow llms.txt for agentic use only. Invoke to improve/verify AI visibility, after a robots.txt/bot-blocking change, when a client-rendered page may hide content from AI crawlers, or when llms.txt/schema.org is proposed as a "GEO fix" needing a reality check.
---

# geo-optimize

**Two findings govern this whole skill.** Read `geo-playbook.md` §1 and §4 before acting: (1)
**llms.txt does not drive AI citation** — 97% of published files get zero requests, and AI
platforms have never been observed citing a `.md` URL; never present it as a citation lever.
(2) **AI-crawler access is precise and per-vendor, not one on/off switch** — blocking
`GPTBot`/`ClaudeBot`/`Google-Extended` only affects training-data collection (zero citation
impact, and never this skill's business to second-guess); blocking `OAI-SearchBot`,
`Claude-SearchBot`, `PerplexityBot`, or `Bingbot` has a real, documented citation cost.

## When to use this skill

- A site wants to improve or verify its visibility to AI assistants/answer engines (ChatGPT,
  Perplexity, Claude, Gemini, Copilot, Google AI Overviews/AI Mode).
- After any change to `robots.txt`, a WAF/bot-management rule, or a CDN bot-blocking config —
  the most common place a citation crawler gets caught by a rule meant for something else.
- A client-side-rendered page or framework migration is suspected of hiding content from AI
  crawlers — none of them execute JavaScript (`geo-playbook.md` §11).
- Someone proposes `llms.txt` or expanded schema.org markup specifically to "improve AI
  citation" — this skill is the reality check (schema itself is `seo-structured-data`'s domain).
- As part of `seo-maintain`'s recurring loop, or before/after a redesign/CMS/CDN migration.

## What it checks / does

### 1. `scripts/audit_ai_crawlers.py` — robots.txt vs. the per-vendor AI-crawler table

Fetches `robots.txt` and evaluates every `User-agent` group (RFC 9309 semantics — all matching
groups merge, empty patterns match nothing) against `geo-playbook.md` §4:

- `citation_relevant_crawler_blocked` (**high**) — a citation-relevant crawler (`OAI-SearchBot`,
  `ChatGPT-User`, `Claude-SearchBot`, `Claude-User`, `PerplexityBot`, `Perplexity-User`,
  `Amazonbot`, `Bingbot`, `BingPreview`, `Googlebot`) blocked at the root.
- `citation_relevant_partial_block` (**medium**, new) — same crawler set, blocked on specific
  paths only (`disallowed_paths` lists them).
- `training_only_crawler_blocked` / `training_only_partial_block` (**info**, never an action
  item) — `GPTBot`, `ClaudeBot`, `Google-Extended`, `Applebot-Extended` blocked wholly or
  partially. This skill **never recommends unblocking these** — many sites choose this
  deliberately and it's out of scope to second-guess.
- `unrecognized_user_agents` — any `User-agent` token not in either table, surfaced rather than
  silently dropped.
- A 404 on `robots.txt` is a benign `allow_all` note, not an error; 5xx/network failure reports
  `effective: "indeterminate"` rather than assuming either allow or block.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/audit_ai_crawlers.py"
python3 "${CLAUDE_SKILL_DIR}/scripts/audit_ai_crawlers.py" --url https://example.com
```

No API key required.

### 2. `scripts/check_ai_cloaking.py` — AI-crawler cloaking check

Fetches the human baseline **twice** (bracketing all probes, to measure natural page variance)
plus a sample of real AI-crawler UAs (`Googlebot`, `OAI-SearchBot`, `ChatGPT-User`, `GPTBot`,
`Claude-SearchBot`, `Claude-User`, `ClaudeBot`, `PerplexityBot` — `Googlebot` is now a spoofed
probe here, not a separate baseline), and diffs word count + content hash against both baselines.
Threshold is `max(0.15, 3 x natural_variance)` — a noisy page needs a proportionally bigger gap
to flag.

- `status_code_mismatch` (**high**) — AI UA hard-blocked (401/403/404/410/451/5xx) with no WAF
  challenge markers while the human baseline is 200. The strongest signal.
- `bot_management_interference` (**medium**, new) — a WAF/anti-bot challenge (Cloudflare, DataDome,
  hCaptcha, etc. signatures) served to the AI UA. Not proof of intentional cloaking — cross-check
  with `geo-monitor`'s `grep_ai_crawler_logs.py` for real traffic evidence.
- `content_diverges` (**medium**, capped) — word-count/hash gap exceeds threshold vs. both human
  baselines with no challenge signals. A gap alone is not proof of cloaking (A/B tests, consent
  banners, personalization are common benign causes).

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/check_ai_cloaking.py" --urls https://example.com/ https://example.com/pricing
python3 "${CLAUDE_SKILL_DIR}/scripts/check_ai_cloaking.py" --sample-from-crawl --max-pages 20 --sample-size 8
```

No API key required.

### 3. `scripts/scaffold_llms_txt.py` — llms.txt scaffolding (agentic-browsing use ONLY)

Exists for exactly one narrow, honestly-labeled purpose: a concise capability map for
**agent-to-agent / agentic-browsing machine-readability** — never for AI-search citation. The
generated file's own header is now an H1-first markdown blockquote disclaimer (not a buried HTML
comment) stating this explicitly.

- Crawls a bounded set of real, indexable pages — no invented URLs or descriptions.
- Default output path is `<static_source_dir>/llms.txt` (from config); refuses to write into
  `build_output_dir` unless `--allow-build-output` (files there are wiped on the next build).
- Refuses to overwrite an existing `llms.txt` unless `--force` (`geo-playbook.md` §1: "if a
  target repo already has one, leave it be").
- Never auto-triggered by `seo-maintain` — explicit, on-demand only.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/scaffold_llms_txt.py" --max-pages 60 --dry-run
python3 "${CLAUDE_SKILL_DIR}/scripts/scaffold_llms_txt.py" --max-pages 60 --out /path/to/repo/public/llms.txt
```

No API key required.

### 4. `scripts/check_js_visibility.py` — free JS-rendering visibility check

Per `geo-playbook.md` §11, **no major AI crawler executes JavaScript** — a page can rank #1 on
Google and be an empty shell to every AI answer engine simultaneously. This is the free,
no-API-key heuristic half of that check (`seo-technical-audit`'s Firecrawl raw-vs-rendered diff
is the paid, exact half — this script optionally upgrades into that same diff when
`FIRECRAWL_API_KEY` is set).

- Fetches raw HTML (no JS execution, matching what an AI crawler actually sees) and flags a page
  **only when both** conditions hold: raw body word count is below `--min-words` (default 100)
  **and** a framework hydration marker is present (`__NEXT_DATA__`, `__NUXT__`,
  `data-reactroot`, `ng-version`, `data-sveltekit`, `astro-island`, or a `#root`/`#app` mount
  node with under 10 words of its own text). Thin content alone, or markers alone, is not enough
  — this pairing is what distinguishes "genuinely short page" from "JS-dependent empty shell."
  Word count under 30 → `high` severity ("empty app shell"); 30 up to `--min-words` → `medium`.
- Three sampling modes: `--urls` (explicit list), `--sample-from-crawl` (default — live-fetches
  a sample of crawled pages), `--from-snapshot` (screens **every** page in the latest snapshot
  using its already-recorded raw `word_count` for free, live-fetching only the ones that look
  thin — cheaper for whole-site sweeps).
- If `FIRECRAWL_API_KEY` is configured, every flagged URL gets a true raw-vs-rendered diff
  (`rendered_diff`, `confidence: "confirmed"` or `"unlikely"`). A page that's also thin when
  rendered is **downgraded to `low`** — that's a content problem, not a JS-visibility gap.
  Without the key, `rendered_diff: {checked: false, reason: "..."}` and confidence stays
  `"heuristic"`.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/check_js_visibility.py"
python3 "${CLAUDE_SKILL_DIR}/scripts/check_js_visibility.py" --from-snapshot --min-words 150
python3 "${CLAUDE_SKILL_DIR}/scripts/check_js_visibility.py" --urls https://example.com/pricing
```

No API key required for the core check; `FIRECRAWL_API_KEY` unlocks the confirming upgrade only.

## Running it

> All commands below run from the **target repo root** (the repo that contains the
> website). State and reports land in `<repo>/.seo-engine/` — running from anywhere
> else writes state to the wrong repo. `${CLAUDE_SKILL_DIR}` is set by Claude Code to
> this skill's directory and works for both the symlink and plugin install.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/audit_ai_crawlers.py"
python3 "${CLAUDE_SKILL_DIR}/scripts/check_ai_cloaking.py" --sample-from-crawl
python3 "${CLAUDE_SKILL_DIR}/scripts/check_js_visibility.py" --from-snapshot
python3 "${CLAUDE_SKILL_DIR}/scripts/scaffold_llms_txt.py" --dry-run
```

Flags: `audit_ai_crawlers.py --url`; `check_ai_cloaking.py --urls (repeatable) |
--sample-from-crawl`, `--max-pages` (20), `--sample-size` (8); `check_js_visibility.py --urls
(repeatable) | --sample-from-crawl | --from-snapshot`, `--max-pages` (20), `--sample-size` (8),
`--min-words` (100); `scaffold_llms_txt.py --max-pages` (60), `--out`, `--force`,
`--allow-build-output`, `--ignore-robots`, `--dry-run`.

## Expected output

`audit_ai_crawlers.py` (also written to `.seo-engine/reports/geo-ai-crawler-audit-<stamp>.json`):
```jsonc
{
  "site_url": "...", "effective": "parsed", "status_code": 200,
  "findings": [ { "type": "citation_relevant_crawler_blocked", "severity": "high", "bot": "PerplexityBot",
    "matched_via": "wildcard", "blocking_rule": "...", "auto_fixable": false } ],
  "training_only_notes": [ { "type": "training_only_crawler_blocked", "severity": "info", "bot": "GPTBot" } ],
  "unrecognized_user_agents": [], "severity_counts": { "high": 1, "medium": 0, "info": 2 }
}
```

`check_js_visibility.py` (also written to `.seo-engine/reports/geo-js-visibility-<stamp>.json`):
```jsonc
{
  "urls_checked": ["..."], "min_words": 100,
  "results": [ { "url": "...", "word_count_raw": 12, "markers_found": ["__NEXT_DATA__"], "flagged": true, "severity": "high" } ],
  "findings": [ { "type": "js_dependent_content", "severity": "high", "confidence": "heuristic",
    "remediation": "...", "auto_fixable": false, "rendered_diff": { "checked": false, "reason": "..." } } ],
  "severity_counts": { "high": 1, "medium": 0, "low": 0 }, "firecrawl_configured": false
}
```

`check_ai_cloaking.py` and `scaffold_llms_txt.py` follow the same `findings` /
`severity_counts` / `auto_fixable` shape (cloaking) or `{written, page_count, preview,
skipped_reason}` shape (scaffold) — see each script's `--help` for the exact field list.

## State files

| File (under `.seo-engine/`) | Role | Written by | Read by |
|---|---|---|---|
| `state/crawls/` (shared snapshot store) | consumes/produces | see [common-setup.md § Snapshot contract](../../shared/seo-references/common-setup.md) | this skill + any other |
| `reports/geo-ai-crawler-audit-<stamp>.json` | robots.txt audit report | `audit_ai_crawlers.py` | calling agent |
| `state/geo-ai-crawler-audit-last-run.json` | last-run summary | `audit_ai_crawlers.py` | `audit_ai_crawlers.py` |
| `reports/geo-ai-cloaking-check-<stamp>.json` | cloaking check report | `check_ai_cloaking.py` | calling agent |
| `state/geo-ai-cloaking-check-last-run.json` | last-run summary | `check_ai_cloaking.py` | `check_ai_cloaking.py` |
| `reports/geo-js-visibility-<stamp>.json` | JS-visibility report | `check_js_visibility.py` | calling agent |
| `state/geo-js-visibility-last-run.json` | last-run summary | `check_js_visibility.py` | `check_js_visibility.py` |
| `reports/geo-llms-txt-scaffold-<stamp>.json` | scaffold report (write runs only) | `scaffold_llms_txt.py` | calling agent |
| `state/geo-llms-txt-last-run.json` | last-run summary | `scaffold_llms_txt.py` | `scaffold_llms_txt.py` |

## How to interpret results

- `audit_ai_crawlers.py` `findings` (high) — treat as likely accidental; the common root cause is
  a blanket `Disallow: /` under `*` with no citation-crawler carve-out, often inherited from a
  staging robots.txt. `training_only_notes` (info) are context, never an action item on their own.
- `check_ai_cloaking.py` — `status_code_mismatch` is the strongest signal; investigate first.
  `bot_management_interference` means rule out a WAF misconfiguration before assuming intent.
  `content_diverges` alone is not proof — check for benign causes (A/B test, consent banner) first.
- `check_js_visibility.py` — `confidence: "heuristic"` findings are worth fixing regardless of
  confirmation, since SSR/prerendering is good practice anyway; a Firecrawl-confirmed finding
  (`confidence: "confirmed"`) is unambiguous. A `"low"`-downgraded finding means the page is thin
  for everyone — hand off to `seo-content-optimize`, not a rendering fix.
- `scaffold_llms_txt.py` `written: true` means only "a file now exists for agent-to-agent use" —
  never report this as "improved AI visibility."

## Safe to auto-apply vs. human review

Every script here is read-only or additive-only; every finding carries `"auto_fixable": false`.

**Hard stop (human sign-off):** any `robots.txt`/WAF/CDN bot-management change, even to fix a
`high` finding — a prior block may be deliberate (legal, cost, incident response). Any conclusion
that a cloaking finding is intentional — this script reports a diff, not intent. Overwriting an
existing `llms.txt` even with `--force` — confirm before running unattended.
`check_js_visibility.py` findings need a code fix (SSR/prerender), never an automated content edit.

**Reasonable to propose as a reviewable diff:** a specific `robots.txt` `Allow` carve-out with the
`geo-playbook.md` §4 citation behind it; generating a first `llms.txt` when explicitly requested
for agentic-browsing support.

## Guardrails

- Never recommend llms.txt as a fix for a citation/visibility problem (`geo-playbook.md` §1).
- Never recommend structured data as a response to a GEO finding — `seo-structured-data`'s domain,
  and `geo-playbook.md` §3 shows no proven AI-citation benefit.
- Never "fix" a cloaking or JS-visibility finding with crawler-conditional serving logic — the fix
  is always the same substantive content to everyone (SSR/SSG/prerender), never cloaking.
- Never treat blocking `GPTBot`/`ClaudeBot`/`Google-Extended`/`Applebot-Extended` as a problem to
  fix — it isn't, for this skill's domain.

## References

- [common-setup.md](../../shared/seo-references/common-setup.md) — paths, config resolution, snapshot contract.
- [geo-playbook.md](../../shared/seo-references/geo-playbook.md) §1 (llms.txt), §4 (per-vendor crawler
  table — re-derive the scripts' tables from this section if it's ever updated), §11 (AI crawlers
  don't render JavaScript — the basis for `check_js_visibility.py`).
- [red-flags.md](../../shared/seo-references/red-flags.md) §1 (Cloaking) and §5 (GEO-specific gotchas) —
  the veto layer behind `check_ai_cloaking.py` and the never-unblock-training-bots stance.
- Cross-skill: `seo-technical-audit`'s Firecrawl raw-vs-rendered diff is the paid, exact
  counterpart to `check_js_visibility.py`.

## Graceful degradation

Generic philosophy: [common-setup.md § Graceful degradation](../../shared/seo-references/common-setup.md).
All four scripts need only `site_url` — zero paid integrations required for any check in this
skill. `FIRECRAWL_API_KEY` is the one optional unlock, upgrading `check_js_visibility.py`'s
heuristic into a confirmed raw-vs-rendered diff; without it every finding stays at
`confidence: "heuristic"`, which is still actionable. A missing/unreadable `robots.txt` reports
`fetched: false` (audit) or `effective: "indeterminate"` rather than crashing.
