# Capability and evidence ledger

This ledger distinguishes tested behavior from deployment applicability and observed growth.
No production website, analytics property or longitudinal traffic dataset was supplied for
this evaluation. No paid discovery call, authenticated GA4 export or live publishing action
was performed. No synthetic result below is a traffic outcome.

| Capability | Evidence in this repo | Limit |
|---|---|---|
| Physical six-phase installation | `tests/test_phase_layout.py` verifies 26 unique phase-owned skills, phase-owned runners, direct installation into another repository, idempotent installation and cross-phase pipeline dispatch | Legacy `skills/` paths are compatibility symlinks; keep the complete engine together |
| Locally stored human writing | 38 Markdown source files, 373 literal passages and 51 task-curated examples; integrity and selection tests in `tests/test_writing.py` | English-focused; modern samples lean institutional/technical. Diversity is not proof of writing quality |
| LanguageTool proofreading | `tests/test_languagetool.py` exercises authenticated form requests, text extraction, Unicode offsets, partial failures, redirect rejection and final-edit integration using test responses | No configured endpoint or API account here; local Java runtime is also absent. No live LanguageTool result is claimed |
| First-party source change → test/build → deploy → HTTP verify | `tests/test_growth_workflow.py` runs commands and actual loopback HTTP for static HTML and a dynamic product route driven by deployed JSON | Proves the generic command lifecycle, not a specific Next.js/Astro/WordPress integration |
| Existing-site installation and recurring agent handoff | Test installs Codex symlinks, invokes a real local wrapper and reads its work packet | Actual agent host/scheduler must be configured and its first run inspected |
| Opportunity selection without prior GSC impressions | Dated alternative assessment; customer/SERP/keyword evidence and bounded paid seed discovery | Operator assertions are not automatically verified; paid connector tested offline only |
| Publication correctness | Review-bound prepare/publish/relink/build tests, immutable URL refresh, interrupted-write and failed-build preservation tests | Editorial judgments and source context remain accountable review; a receipt is not proof of truth |
| Actual referral analytics | GA4 API adapter and normalized exports; tests for coverage, referrer spoofing, sample and window comparability | No authenticated GA4 response was available; run opt-in `scripts/dev/smoke.py --site YOUR_URL --only ga4` when configured |
| Google search clicks/index signals | Existing paginated Search Console clients and regression suite | Credentials, property access and mature data required; impressions/clicks do not prove incremental effect |
| AI visibility diagnostics | Provider probes, design signatures and minimum-sample gating | API responses are not consumer ChatGPT exposure or visits; repetitions can be correlated |
| Traffic effect, costs and decisions | Intervention ledger, conservative deployment interval, observed cohort comparison, decisions/costs/review dates | No real intervention outcome yet. Real measured results must include failures and unchanged sites |

Supported workflow interfaces are repository-owned argv commands and HTTP-verifiable public
routes. CMS writes, host APIs, renderers and business facts are supplied by the target project
and reviewed through its normal process. Recipes exist for SaaS, ecommerce, local services,
docs and editorial sites; those are applicability guidance, not tested adapters or growth proof.

## Pilot required to evaluate effectiveness

Use an authorized website with a verified analytics property. Capture complete baseline
windows, choose a substantive intervention, preserve all input evidence and changed URLs,
validate and record the attempted/verified deployment interval. Wait for mature comparable
post-period data. Record Google organic sessions/clicks, ChatGPT referrals, configured key
events, actual human/API costs, confounders, failed attempts and the retain/refine/revert/defer
decision. Controls can help but require comparable pretrends; descriptive differences are not
causal estimates. Repeat across site types before broadening any effectiveness claim.

Configuration readiness was checked locally: no configured website, no GSC credentials, and GA4 not ready. Simulation jobs are labeled and restricted to local/reserved test hosts; synthetic exports cannot drive production lifecycle decisions.

The later autonomous-workflow rounds resolved the earlier shared refresh-asset boundary:
pending covers and diagrams fork the published bundle, rendering uses the recorded bundle,
and independent checks confirm that the live article's bytes/review remain valid through
refresh preparation. The frozen copy library, external research collector and strategy
handoff are covered in the [current evaluation](autonomous-workflow-rounds.md). Its 9.147/10
score uses the user's revised capability-focused rubric and does not retroactively change
the older outcome-weighted evaluation.
