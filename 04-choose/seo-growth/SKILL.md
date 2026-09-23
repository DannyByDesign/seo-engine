---
name: seo-growth
description: Autonomously understand any website repo, research its market with external APIs, develop positioning, choose growth opportunities, write copy and implement changes, then learn from Google organic and ChatGPT referrals. Start here after installing the engine or when asked to grow the website; derives its own seeds and briefs. Uses the host agent and existing authorization.
---

# seo-growth

## When to use this skill

Use when the user wants the website to acquire organic visitors, including cold-start sites.
Start in the existing website repo. A separate publication is an optional experiment.
Begin with [the ordered workflow](../../workflow/README.md), then load only the next
needed section. The agent does the strategy and authoring; do not hand the owner a form asking
for keywords, competitors, positioning or intervention JSON. No extra model API is required
for reasoning when the host agent is already available.

## What it checks / does

`run_strategy.py` inventories the target and validates agent-authored understanding, research
and positioning. Read its status before selecting an opportunity; the next missing or stale
section is explicit. Follow the [artifact contract](../../workflow/contract.md), storing
actual response snapshots and distinguishing sourced facts from hypotheses. Once adopted,
content interventions bind the current `position_digest`. Technical repairs can proceed with
diagnostics while external research is unavailable.

Use `research_market.py` for terminal API calls: DataForSEO Google SERPs, volumes, keyword
ideas, domain competitors and ranked keywords; Brave independent web search; Firecrawl
search and rendered scraping. Read [API selection and setup](../../02-research/research-apis.md).
The agent derives query/target inputs from understanding and previous results. Calls preserve
timestamped responses/failures and consume a durable daily call allowance before execution.
Set `growth.research.daily_call_limit` in config (default twenty logical calls); account dollar
limits are separate. `--allow-paid` uses existing authorization, not a new per-call question.

Select one actionable opportunity from `seo-maintain`, `seo-keyword-research`, or explicit
customer questions and current search results when GSC is empty. Record audience, demand
source, business relevance, target URL, source files, original contribution and expected
outcome before editing. Do not invent keyword volumes or claim every site has demand.

Implement in the website's existing framework/CMS. Inspect project instructions, routes,
components and tests. Preserve URL and useful content for refreshes. Add information the
owner can substantiate; escalate missing factual inputs without padding. Run the relevant
build/tests and inspect rendered HTML. Follow existing deployment authorization, verify the
production URL, canonical, robots and expected content, and record the date and revision.
Do not call local output deployed. A missing host/credential is an explicit blocker.

`traffic_report.py` exports GA4 landing-page sessions and key events or compares normalized
analytics exports. It separates Google organic from ChatGPT referrals; neither is a model
citation probe. It requires equal, nonoverlapping, mature windows of whole weeks, matched
property/timezone/filters, complete data, and explicit synthetic provenance. Small cohorts
remain insufficient sample; complete zero baselines with substantial post-period traffic are
labeled observed new traffic, without relative or causal lift. Observed deltas, even with controls, are not causal proof.

`run_growth.py` persists each intervention: planned → validated → deployment_unverified →
verified → observing/awaiting_decision → closed or followup_required. Read status on every scheduled run to resume failures and find overdue
reviews. `create` records the pre-edit fingerprint; edit the declared files, then `validate`
runs the repo's configured test/build commands. `deploy` requires `--approve-deploy` and
unchanged validated sources. Deployment intent is saved before execution. A timeout/failure stays `deployment_uncertain`; verify or reconcile before retry. New work after deployment requires a new intervention ID. `verify` fetches production and checks expected text, canonical,
noindex and Google/OAI robots access. A successful command alone is never verified deployment.

Use [brief.example.json](references/brief.example.json) as a schema example, adapting files,
commands and evidence to the actual repo. Include every dependency that can affect the page
(template, config, lockfile and content). Commands are executable repository code, not sandboxed.
No framework adapter is assumed: the agent implements the change using the existing stack.

Recurring execution: [growth-cycle.md](../../shared/seo-references/growth-cycle.md) is the scheduled-agent
prompt. `run_cycle.py` writes a work packet; `--execute-agent` invokes the explicitly configured
`growth.agent_command` argv array with the packet path appended. The command must accept that
file as its last argument. Configure the actual agent/host scheduler and inspect its first run;
installation alone does not schedule work. Cycle reports persist success/failure and overlapping
cycles are refused. Read-only packet generation needs no model key.

Demand selection is recorded with `assess_opportunities.py --candidates-file candidates.json
--out assessment.json`. Supply two to ten candidates with ID, query, audience, intent, page,
action, original value, business reason, ordinal `business_value` (1–3), estimated
`effort_hours`, and `evidence[]` with kind (`customer_question`, `gsc`, `serp`, `keyword_data`),
reference, observation and observed_on. Evidence older than ninety days needs rechecking.
The brief embeds these alternatives under `selection`, with `selected_id` and rationale.
Inspection of references is required; the tool records observations rather than proving them.
Assumptions alone cannot start an intervention. Priority is an explicit business judgment,
not predicted traffic. Read [site-types.md](references/site-types.md) for applicable choices.

Optional `--paid-discovery --seeds query,query --location-code 2840 --language-code en --out
demand.json` performs bounded DataForSEO volume and SERP calls without needing GSC impressions.
It preserves failures and unknown volumes; API availability is not proof of opportunity.

For unresolved deployments, `--stage reconcile --reconciliation-file reconciliation.json`
records `decision: confirmed_not_deployed`, reviewer, reason and a repo-local evidence_file.
Inspect hosting logs first; the command records your judgment and a hash, not automatic proof.
Then validate again and retry with existing deployment authorization. Measurement excludes
all days from the deployment attempt through first verified availability. Both boundaries
remain recorded; a delayed asynchronous rollout is never assigned a precise causal timestamp.

`--stage decide --decision-file decision.json` records reviewer, decision
(`retain`, `refine`, `revert`, `defer`), reason and `costs` (`known: false`, or `known: true`
with actual nonnegative `human_minutes` and `api_usd`). A defer also needs future `next_review`.
Inconclusive comparisons automatically remain observing with a new review date. Retaining
one requires explicit `close_without_traffic_evidence: true`; the decision records
`traffic_conclusion: not_demonstrated` and the inconclusive channels. Use this only to end
measurement deliberately on other reader/business grounds; otherwise defer. Retain closes
the experiment. Refine/revert create followup_required work;
they record a decision, not an executed source change or rollback. Create and verify that
follow-up intervention with the same authorization and validation process.

Evidence may include a repo-local `snapshot` path. The assessment hashes that file and labels
its provenance distinctly from an operator-supplied assertion; neither label means automatic
verification. Inspect source context before accepting an opportunity.

At creation, capture each production baseline (or confirmed 404), or provide a repo-local
`baseline_file` explicitly labeled as supplied. Each page declares `assertions[]` with kind
and expected value: text_present/text_absent, title, canonical, indexable (boolean), header
(with name), or robots_allowed (boolean, with bot). Legacy expected_text is a text_present
assertion. At least one assertion must distinguish baseline from intended output. This
supports metadata-only repairs without adding prose. A performance deployment can use a
revision header assertion; measure performance itself with the performance skill.
For supplied header/robots baselines, include baseline_headers/baseline_robots_file.

A `kind: technical_repair` brief uses a saved `diagnostic_file` instead of keyword-demand
alternatives; diagnose that report and preserve reader content. Content growth still requires
competing evidenced opportunities. Assertions are targeted smoke checks, not proof of full
page equivalence, indexing, rankings or performance.

`--stage update --update-file update.json` records reviewer, reason and action cancel/block/
resume for pre-deployment work. Block needs future next_review; resume requires revalidation.
Cancellation releases URL ownership and preserves history. Attempted deployments must first
be reconciled; they cannot be cancelled to erase uncertainty.

For refine/revert, create the next intervention with `--parent-id <id>` and a `followup`
object with the parent's decision and substantive scope. It must address all parent URLs.
The parent becomes followup_in_progress, then superseded only on verified child deployment. Cancelling an undeployed child returns the parent to followup_required so a replacement can be created.
Other active interventions cannot claim the same URL. A rollback still requires a new brief,
actual source change, validation and authorized deployment.

Production jobs reject synthetic traffic exports. Tests may create an explicit
`simulation: true` brief for localhost or reserved test domains; status and outcomes retain
that label and cannot count as operational evidence. Never relabel a synthetic export as real.

In a Git repo, validation fingerprints include tracked and nonignored files as well as the
declared source set, excluding engine runtime state and installed skill links. This catches
an omitted shared template or configuration change. Keep build outputs ignored. For a non-Git
project, declare all input dependencies explicitly. Measurement converts the deployment
interval to the analytics timezone and resolves landing paths under the site's URL prefix.
GA4 coverage warnings are retained across every response page.

## Running it

Run from the target repository, using the resolved absolute skill directory for your agent.
`${CLAUDE_SKILL_DIR}` below can be replaced by that path.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/run_strategy.py" --action inspect
python3 "${CLAUDE_SKILL_DIR}/scripts/run_strategy.py" --action record --section understand --file understand-input.json
python3 "${CLAUDE_SKILL_DIR}/scripts/run_strategy.py" --action status
python3 "${CLAUDE_SKILL_DIR}/scripts/research_market.py" --provider dataforseo --operation ideas --query "QUERY_DERIVED_FROM_PRODUCT" --location 2840 --language en --limit 10 --allow-paid
```

Strategy flags: `--action` (inspect/record/status), `--section` (understand/research/position),
`--file`. Research flags: `--provider`, `--operation`, `--query`, `--target`, `--location`,
`--language`, `--country`, `--search-location`, `--limit`, `--allow-paid`. Provider operation compatibility and
credential requirements are in the linked API guide. Target is a bare domain for competitor
research or an absolute URL for scrape. Research output paths are returned automatically.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/traffic_report.py" --ga4 --start YYYY-MM-DD --end YYYY-MM-DD --out baseline.json
python3 "${CLAUDE_SKILL_DIR}/scripts/traffic_report.py" --before baseline.json --after followup.json --pages /guides/topic --controls /guides/comparison --deployed-on YYYY-MM-DD --out comparison.json
```

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/run_growth.py" --stage create --brief-file brief.json
# Implement the documented change in the original website source, then:
python3 "${CLAUDE_SKILL_DIR}/scripts/run_growth.py" --stage validate --id deployment-guide
python3 "${CLAUDE_SKILL_DIR}/scripts/run_growth.py" --stage deploy --id deployment-guide --approve-deploy
python3 "${CLAUDE_SKILL_DIR}/scripts/run_growth.py" --stage verify --id deployment-guide
python3 "${CLAUDE_SKILL_DIR}/scripts/run_growth.py" --stage evaluate --id deployment-guide --before baseline.json --after followup.json
python3 "${CLAUDE_SKILL_DIR}/scripts/run_growth.py" --stage status
```

Cycle flag: `--execute-agent`. Its packet and last result live in `.seo-engine/reports/growth-cycle-packet.json` and `growth-cycle-last.json`.

Growth runner flags: `--stage`, `--id`, `--parent-id`, `--brief-file`, `--reconciliation-file`, `--decision-file`, `--update-file`, `--approve-deploy`, `--before`, `--after`.
Traffic flags: `--ga4`, `--start`, `--end`, `--out`, `--before`, `--after`, `--pages`, `--controls`,
`--deployed-on`. GA4 requires `GA4_PROPERTY_ID`, existing Google service-account credentials,
GA4 Data API enabled and Viewer access to the property. Reports filter the configured host.

For another analytics system, normalize an export to JSON with `property`, `timezone`,
`exporter`, `site_url`, `start`, `end`, `complete: true`, `synthetic: false`, `filters`, and
`rows[]`: `date`, site-relative `page`, `source`, `medium`, nonnegative `sessions`, `key_events`.
Set `sampled` and `thresholded` accurately. Completeness is the exporter's assertion; do not
label partial exports complete. File hashes retain provenance, not authenticity proof.

## Expected output

JSON `checked` and `output`. Comparisons report each channel's before/after sessions and key
events, deltas, sample verdict and limitations. `causal_lift` remains null. Export coverage
problems are recorded, then rejected at comparison time. Errors exit nonzero.

## State files

Strategy records and immutable revisions live in `.seo-engine/state/strategy/`; research
responses in `.seo-engine/reports/research/` and daily call reservations in `.seo-engine/state/research/`.
The cycle packet includes current strategy status and intervention learning for the next agent.

Intervention state and history live in `.seo-engine/state/growth/<id>.json`; a process lock prevents overlapping runners. `status` reports unfinished and overdue work. Command output is hashed rather than copied into state to avoid storing secrets.

Traffic exports and comparisons are written only to `--out`; store them under the target
repo's `.seo-engine/reports/`. Keep private analytics out of version control. Record changed
URLs, revision, deployment date, hypothesis, cost and review date alongside the exports.

## How to interpret results

A working implementation is not a traffic outcome. Investigate regressions before publishing
more. After enough observations, retain, refine or revert the intervention based on reader
value, actual traffic, conversions and cost; document confounders. Without data, report unknown.

## Safe to auto-apply vs. human review

Perform authorized local edits and tests. Reuse the user's existing scope for deployment;
configuration or the presence of credentials alone is not permission to publish. Do not
invent evidence, authorize spending, or create a recurring job without user scope covering it.

## Guardrails

No promised rankings, synthetic traffic evidence, automatic success from citations, or
scaled low-value pages. Protect existing routes, attribution and factual claims. GA4 misses
some referrers and consent-blocked sessions; key events need correct property configuration.

## References

- [Common setup](../../shared/seo-references/common-setup.md)
- [Publication playbook](../../shared/seo-references/publication-playbook.md)
- [GA4 reporting API](https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/runReport)
- [GA4 schema](https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema)

## Graceful degradation

Without GA4 credentials, use an attributable export from the site's analytics platform.
Without any traffic data, ship authorized useful work and report outcomes as unknown.
Cold-start discovery uses customer questions and current SERPs with stated uncertainty;
keyword volume estimates require a real data source.
