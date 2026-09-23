---
name: geo-monitor
description: Measures actual AI-search visibility: whether the target domain gets cited by ChatGPT, Claude, Perplexity and Gemini for tracked prompts (N samples, majority-voted, flap-damped loss detection), and how often the brand and its competitors are NAMED in answers (mention rate, share of voice, prominence, sentiment, owned-citation rate, Wilson intervals), per publication or for the main site. Invoke for "are we showing up in AI search" or the scheduled GEO step. It only measures; geo-optimize and the pub-* skills act.
---

# geo-monitor

A **measurement** skill, not an optimization skill. It answers "is the target domain actually
getting cited, and did that change since last time" — nothing more. It never edits content,
`robots.txt`, or schema; when a result surfaces a problem, hand off to `geo-optimize` (crawler
access) or `seo-content-optimize` (content substance) rather than self-remediating.

**Single probes are noise.** LLM answers are stochastic; per `geo-playbook.md` §9 this skill
always samples N times per prompt×provider (default 3) and majority-votes the state, never
trusts one call.

## When to use this skill

- A user asks whether/how the site shows up in ChatGPT, Claude, Perplexity, or Gemini answers, or
  wants a recurring visibility check (`seo-maintain`'s scheduled loop, or a cron session).
- "Did we lose a citation we used to have" — or establishing a baseline before/after a
  `geo-optimize`/`seo-content-optimize` change (correlation only, never proof of causation).
- A user wants to know which of the site's own pages are actually earning citations right now.
- **Not** for generating or tuning content/robots.txt/schema to chase a citation — report and
  route to `geo-optimize`/`seo-content-optimize` instead.

## What it checks / does

### 1. `scripts/track_ai_visibility.py` — DIY citation probing

Calls each configured vendor's own web-search/grounding API (OpenAI Responses `web_search`,
Anthropic Messages `web_search_20250305`, Perplexity Sonar, Gemini Google Search grounding) `
--samples` times per tracked prompt and checks whether the target domain appears among the
citations each API itself returned. A provider with no key reports `not_configured`, never an
error — a partial key set still produces a useful, narrower run.

**Tracked-prompt resolution, in order:**
1. `--prompt "..."` (repeatable) — ad hoc, overrides everything else for that run.
2. `geo_prompts` in `.seo-engine/config.yml` — the durable, curated, natural-language set worth
   investing in.
3. `target_topics` (same config key `seo-rank-tracking` reads), turned into a generic `"What is
   the best <topic>?"` shape — usable but a clearly weaker signal; the output says so
   (`prompt_source: "target_topics_derived"`).
4. **Neither configured and no `--prompt` given → the script refuses to guess**, exits with
   `checked: false` and a `next_step` naming exactly what to ask the user. Inventing prompts here
   would produce a report that looks precise while measuring nothing anyone asked about.

Per-sample state ∈ `{cited, not_cited, mixed, error, not_configured}`. A sample with a provider
error is excluded from the vote, never conflated with "not cited"; if every sample errors, the
aggregate state is `error`. Majority vote: `cited` if `cited_count >= ceil(valid_samples / 2)`.

**Loss detection is flap-damped**, per prompt×provider: first `not_cited` after a `cited` run →
`possible_citation_loss` (low, unconfirmed, appears in `possible_citation_losses`); only a
**second consecutive** `not_cited` run promotes it to `confirmed_citation_loss`, surfaced in the
headline `newly_lost_citations` (medium). Provider errors never count toward either bucket
(`indeterminate_provider_errors` is separate). Citation URLs are target-domain-matched and
deduped; Gemini's are matched by title, since its grounding `uri` is an opaque per-run redirect,
not the real source URL.

```bash
python3 "${SKILL_DIR}/scripts/track_ai_visibility.py"

python3 "${SKILL_DIR}/scripts/track_ai_visibility.py" \
  --prompt "what is the best expense tracking software for freelancers" \
  --prompt "how do I automate invoice reminders"

python3 "${SKILL_DIR}/scripts/track_ai_visibility.py" --domain example.com --samples 5
python3 "${SKILL_DIR}/scripts/track_ai_visibility.py" --skip-trackers
```

### 2. Commercial tracker cross-check (optional)

If `PROFOUND_API_KEY` / `OTTERLY_API_KEY`+`OTTERLY_PROJECT_ID` are set, results land under
`commercial_tracker_cross_check`, tagged `"source": "third_party_commercial_tracker"` — **never
merged into the per-prompt DIY results**, since these vendors measure against their own prompt
set/taxonomy. Treat purely as "does an independent tracker roughly agree with our probing
direction," per api-reference.md's AI-visibility-tracking section.

### 3. Free, zero-cost complementary signals

- **GA4's "AI Assistant" channel** (Medium=`ai-assistant`) buckets ChatGPT/Gemini/Claude/
  Copilot/DeepSeek/Grok referral traffic automatically but **excludes Perplexity** — add a custom
  channel rule matching `perplexity\.ai` above the default Referral rule. Dashboard-based, not
  scripted here.
- **Cloudflare Radar's "AI Insights"** dashboard — aggregate AI-crawler volume/crawl-to-referral
  ratios. Also dashboard-based.
- **`scripts/grep_ai_crawler_logs.py`** — the one free signal that *is* scripted, since it's a
  pure local-file operation.

#### `scripts/grep_ai_crawler_logs.py`

Greps a server access-log (plain text or `.gz`) for 16 known AI-crawler user-agents (casefolded
substring match — catches lowercase `bingbot/2.0`), each tagged with a
`role ∈ {citation_index, live_fetch, training_only}`: `GPTBot`/`ClaudeBot`/`Google-Extended`/
`Applebot-Extended`/`Bytespider`/`Meta-ExternalAgent`/`CCBot` (training_only);
`OAI-SearchBot`/`Claude-SearchBot`/`PerplexityBot`/`Amazonbot`/`bingbot`/`BingPreview`
(citation_index); `ChatGPT-User`/`Claude-User`/`Perplexity-User` (live_fetch). Reports a hit count
and up to `--sample-lines` sample lines per crawler, and a `hits_by_role` rollup. CLF timestamps
are parsed with full time-of-day and timezone offset (not truncated to a date); lines without a
parseable timestamp are still counted, never silently dropped. Client IPs in persisted sample
lines are masked (IPv4 last two octets, IPv6 to the first hextet) before being written anywhere.

```bash
python3 "${SKILL_DIR}/scripts/grep_ai_crawler_logs.py" /var/log/nginx/access.log
python3 "${SKILL_DIR}/scripts/grep_ai_crawler_logs.py" /var/log/nginx/access.log.gz --since-days 30
python3 "${SKILL_DIR}/scripts/grep_ai_crawler_logs.py" access.log --sample-lines 5
```

Needs no config or API key — reads only the log file path given. If `.seo-engine/` isn't
reachable from wherever the log lives, it degrades to stdout-only rather than crashing.

**A crawler hit means a visit, not a citation.** For `citation_index` crawlers, a visit is a
*precondition* for citation, not proof of it. For `training_only` crawlers, a hit (or its
absence) has **no bearing on citation at all**. Cross-check a zero-count `*-SearchBot`/`*-User`
crawler against `geo-optimize`'s `audit_ai_crawlers.py` before assuming anything is broken. A
zero `PerplexityBot` count specifically does not guarantee zero Perplexity crawl activity —
Cloudflare has documented undeclared stealth crawlers evading robots.txt (`geo-playbook.md` §4,
"corroborated but disputed").

### 4. `scripts/track_brand_mentions.py` — named, not just cited (Lettertrace method)

Citation probing asks "was our URL among the sources"; this asks "was our brand *named*, and
were the competitors" — the two are separate currencies and uncorrelated in the measured data
(`publication-playbook.md` §7). For a publication (`--publication`) the subject comes from
`strategy.yml` (client name/aliases/domain, competitors, ranking-target phrases as topics,
publication domains as owned); otherwise from `--brand`/`--alias`/`--domain`/`--competitor`/
`--topic` or `geo_topics` in `.seo-engine/config.yml`.

`--generate` turns each topic into `--variations` prompts (default 8, max 20) with the one
rule that measured anything in the vendor's pilots: two thirds must explicitly demand named
companies ("List the top 5 … by name"; never "a shortlist", never how-to), each labeled
`general | mid | niche`. Each prompt runs on every configured provider `--replicates` times
(1-10); the answer text is scanned with deterministic detection (`scripts/lib/mentions.py`:
name + aliases, never the domain label, link targets blanked, longest alias first); detected
entities get a cheap-model `sentiment`/`recommended` (skip with `--no-enrich`); citations carry
an `owned` flag. Output per run: per-entity mention rate, share of voice, average prominence,
recommend rate, sentiment score; owned-citation rate; informative rate; the five-state verdict
`no-data | no-competitors | thin-sample | sampled-absence | sampled-presence`; the prompts competitors win;
the owned pages that get cited; the trend against the previous run; `first_mention_at`.
`--dry-run` prints the prompt set and the exact number of billed calls; `--max-prompts` caps
a run.

```bash
python3 "${SKILL_DIR}/scripts/track_brand_mentions.py" --publication llm-billboard --generate --dry-run
python3 "${SKILL_DIR}/scripts/track_brand_mentions.py" --publication llm-billboard --replicates 2
python3 "${SKILL_DIR}/scripts/track_brand_mentions.py" --brand thrad --domain thrad.ai \
  --competitor "Lapis=trylapis.com" --topic "LLM advertising platforms" --generate --providers openai,anthropic
```

## Running it

> All commands below run from the **target repo root** (the repo that contains the
> website). State and reports land in `<repo>/.seo-engine/` — running from anywhere
> else writes state to the wrong repo. Set `SKILL_DIR` to this skill's resolved absolute directory before running these commands
> (see common-setup.md); no host-specific variable is required.

```bash
python3 "${SKILL_DIR}/scripts/track_ai_visibility.py"
python3 "${SKILL_DIR}/scripts/grep_ai_crawler_logs.py" /var/log/nginx/access.log
```

Flags: `track_ai_visibility.py --prompt` (repeatable), `--domain`, `--samples` (default 3, must
be >= 1), `--skip-trackers`; `grep_ai_crawler_logs.py` positional `log_file`, `--sample-lines`
(default 2), `--since-days`; `track_brand_mentions.py` `--publication`, `--brand`, `--alias`,
`--domain`, `--competitor`, `--topic` (all repeatable where plural), `--variations`,
`--generate`, `--replicates`, `--providers`, `--max-prompts`, `--no-enrich`, `--dry-run`,
`--publications-dir`.

## Expected output

`track_ai_visibility.py` (also written to `.seo-engine/reports/ai-visibility-<stamp>.json`):
```jsonc
{
  "checked": true, "run_id": "...", "target_domain": "example.com", "prompt_source": "geo_prompts",
  "diy_providers_configured": ["openai", "anthropic"],
  "cost_note": "This run makes up to 6 billed web-search LLM API call(s): 2 provider(s) x 1 prompt(s) x 3 sample(s) ...",
  "summary": { "prompts_cited_by_at_least_one_provider": 3, "newly_gained_citations_count": 1,
               "newly_lost_citations_count": 1, "possible_citation_losses_count": 1,
               "indeterminate_provider_errors_count": 0 },
  "newly_gained_citations": [ { "prompt": "...", "provider": "perplexity", "urls": ["..."] } ],
  "newly_lost_citations": [ { "prompt": "...", "provider": "openai", "last_known_citation_urls": ["..."] } ],
  "prompts": [ { "prompt": "...", "cited_by": ["openai"], "provider_detail": { "openai": { "state": "cited" } },
                 "diff_vs_previous_run": { "has_prior_run": true, "providers": { "openai": { "change": "unchanged" } } } } ],
  "history_file": ".seo-engine/state/ai-visibility-history.jsonl", "history_schema_version": 2
}
```

`grep_ai_crawler_logs.py`:
```jsonc
{
  "scan_summary": { "total_known_ai_crawler_hits": 412, "hits_by_role": { "citation_index": 300, "training_only": 100, "live_fetch": 12 } },
  "crawlers": [ { "user_agent": "GPTBot", "role": "training_only", "hit_count": 88, "sample_lines": ["..."] } ]
}
```

## State files

| File (under `.seo-engine/`) | Role | Written by | Read by |
|---|---|---|---|
| `state/ai-visibility-history.jsonl` | append-only, one record per prompt per run (schema v2: prompt, target_domain, run_id, per-provider state/cited_count/citation_urls) | `track_ai_visibility.py` | `track_ai_visibility.py` (flap-damped diffing) |
| `reports/ai-visibility-<stamp>.json` | dated run report | `track_ai_visibility.py` | calling agent |
| `reports/ai-crawler-log-scan-<stamp>.json` | dated scan report (best-effort) | `grep_ai_crawler_logs.py` | calling agent |
| `state/pub-mentions-<slug>.json` (`main` for the first-party site) | prompt set, up to 52 runs of mention/citation metrics, `first_mention_at` | `track_brand_mentions.py` | `track_brand_mentions.py` (trend), `pub-monitor` GEO sync |
| `reports/pub-mentions-<slug>-<stamp>.json` | dated brand-mention report | `track_brand_mentions.py` | calling agent |

Brand probes are API samples, not consumer ChatGPT traffic. Fewer than ten successful
responses stay thin-sample. Per-prompt gaps need at least ten responses and separated Wilson
intervals; incomplete runs cannot feed publication scoring. Trends require matching prompt,
provider, entity and implementation signatures with no failed probes. Repeated prompts can
remain correlated; intervals do not establish population representativeness.

## How to interpret results

- **A prompt with zero configured providers proves nothing** — check `diy_providers_configured`
  before drawing any conclusion.
- **`not_cited_by` is not itself a defect.** Per `geo-playbook.md` §2, AI platforms are not a
  monolith; not being cited by one provider for one prompt is one data point, not a bug.
- **`newly_lost_citations` is the time-sensitive signal** — a confirmed (two-consecutive-miss)
  loss deserves urgency; `possible_citation_losses` is a heads-up, confirm next run.
- **`newly_gained_citations` tells you what's already working** — feed the actual cited URLs back
  to `seo-content-optimize`/`geo-optimize` as site-specific evidence, not a generic vendor tactic.
- **The Gemini result is not literally AI Overviews/AI Mode** — it's the Gemini API's own
  grounding; Google AI Overviews/AI Mode in Search has no public API.
- **Zero ChatGPT citations + page absent from Bing → dispatch `seo-indexing`, not
  `seo-content-optimize`.** Per `geo-playbook.md` §10, ChatGPT search rides substantially on
  Bing's index — treat Bing indexation as a floor for ChatGPT-citation odds, and fix it at the
  indexation level before any content-level GEO theory.
- **Flat visibility with clean crawler access and solid content is a real, honest conclusion, not
  a signal to keep iterating on-site.** Per `geo-playbook.md` §6, the strongest AI-visibility
  correlates (brand mentions, community presence, Wikipedia) are off-site and outside this
  system's write-scope — report that plainly rather than proposing another round of on-site tactics.
- **Do not treat correlation with a recent site change as proof of causation** — this skill has no
  controlled-experiment design.
- **A `thin-sample` verdict means the prompts, not the brand, failed**: answers did not name
  anyone. Regenerate prompts (`--generate`) in the named-companies shape before reading a 0%
  mention rate as a gap; `sampled-absence` is the honest zero.
- **Named and cited move independently.** A rising owned-citation rate with a flat mention
  rate is the normal early trajectory for a young publication; expect months.

## Safe to auto-apply vs. human review

This skill only measures and reports — no content/robots.txt/schema/config changes.

- **Safe without asking:** running the probe scripts, appending history, writing the dated report,
  reporting gained/lost citations back to the user or `seo-maintain`.
- **Must be flagged, never decided silently:** no `geo_prompts`/`target_topics` configured and no
  `--prompt` given — do not invent prompts to make the run "succeed." Surface the `checked: false`
  refusal as a question ("which queries matter to you?").
- **Route, don't fix:** a likely-fixable problem (crawler blocked, page disappeared from
  citations, thin content) goes to `geo-optimize`/`seo-content-optimize` with this run's evidence
  — never modify robots.txt, content, or schema from this skill.

## Guardrails

- Never scrape a chat UI to measure visibility — only documented vendor APIs (`geo-playbook.md` §9).
- Never report the Gemini API grounding result as if it were Google AI Overviews/AI Mode.
- Never treat a single probe as a measurement — always the N-sample majority vote.
- Never report a `possible_citation_loss` with the same urgency as a confirmed one.

## References

- [common-setup.md](../../shared/seo-references/common-setup.md) — paths, config resolution.
- [geo-playbook.md](../../shared/seo-references/geo-playbook.md) §9 (measurement methodology — the basis
  for this skill, including the N-samples/flap-damping discipline), §2 (platforms aren't a
  monolith), §4 (per-vendor crawler table `grep_ai_crawler_logs.py` mirrors), §6 (off-site levers
  and scope honesty), §10 (Bing as ChatGPT's index — the interpretation rule above).
- [red-flags.md](../../shared/seo-references/red-flags.md) §5 — cloaking risk extends to AI crawlers;
  relevant if a log scan or `geo-optimize` audit surfaces divergent serving, which this
  monitoring skill would not itself detect but should route to `geo-optimize`.

## Graceful degradation

Generic philosophy: [common-setup.md § Graceful degradation](../../shared/seo-references/common-setup.md).
`track_ai_visibility.py` runs with zero API keys — every provider reports `not_configured` and
`setup_notes` explains what to set; it never crashes for a missing key. `PROFOUND_API_KEY` /
`OTTERLY_API_KEY`+`OTTERLY_PROJECT_ID` are fully optional. `grep_ai_crawler_logs.py` needs no API
key or config at all; if `.seo-engine/` isn't reachable it still prints full JSON to stdout, just
without a written report file.
