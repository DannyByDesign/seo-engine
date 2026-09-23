# Final product evaluation

The repository now supports a substantially stronger organic-growth experimentation
workflow, but it has **not demonstrated that it turns any website repo into traffic from
Google and ChatGPT**. Ten adversarial grading rounds are complete. The final independent
grade is **6.95/10**; the requested score above 9.1 was not achieved.

## How the grade was determined

The rubric stayed fixed. Rounds 1–9 used one adversarial reviewer; round 10 used a fresh
reviewer to challenge accumulated assumptions. These are reviewer judgments, not empirical
effectiveness scores. The progression was 5.5, 6.0, 6.6, 7.1, 7.5, 7.7, 7.9, 7.9, 8.0,
then 6.95. The fresh review was more conservative, including zero credit for absent outcomes.

| Dimension | Weight | Final score |
|---|---:|---:|
| First-party execution and applicability | 30% | 8.5 |
| Content value, factuality and trust | 20% | 8.0 |
| Operational reliability | 20% | 8.0 |
| Valid traffic measurement and decisions | 15% | 8.0 |
| Demonstrated traffic outcomes | 15% | 0.0 |

With no demonstrated outcomes, perfect scores in every other dimension would yield 8.5.
More local tests cannot establish the missing outcome evidence.

## What changed

- **First-party execution:** a new `seo-growth` skill connects demand evidence and alternative
  opportunities to actual repository edits, project test/build/deploy commands, distinguishing
  production assertions, observations, and retain/refine/revert/defer decisions. It supports
  recovery from uncertain deployments and linked follow-up changes.
- **Publication integrity:** explicit final-content editorial review binds claims, fetched
  evidence, assets and policy. Reviewed drafts resume without rewriting; relinking proposes
  reviewed changes; refreshes preserve URLs, dates and original context. Staged builds and
  atomic writes protect the last good output. Attribution and ownership are truthful.
- **Measurement:** GA4 referral exports and validated imports distinguish Google organic
  traffic and ChatGPT referrals from API visibility probes. Comparisons check coverage,
  timezones, windows, sample sizes and deployment uncertainty. Synthetic data is isolated
  from production decisions. Reports keep descriptive observations separate from causal lift.
- **Operations and guidance:** Codex installation, recurring work packets, explicit costs,
  observation deadlines, evidence provenance, site-type recipes and current platform guidance
  make the workflow more usable. Installation does not activate a scheduler by itself.

## Final review findings and repairs

The final graded snapshot passed 375 tests but had three reproduced defects: refetching a
changed source could overwrite evidence for an already published article; installation
missed `.env` and state exclusions in Git worktrees; and retaining an inconclusive experiment
silently stopped observation.

Targeted fixes now use immutable source snapshots, detect Git worktrees correctly, and
require explicit `close_without_traffic_evidence: true` for inconclusive retention, recording
`traffic_conclusion: not_demonstrated`. Regression tests exercise the published receipt and
rebuild, a real temporary Git worktree, and rejected/acknowledged retention. These fixes
follow the tenth grade and are not assigned an eleventh score.

The reviewer independently verified all three fixes, then reproduced a related unresolved
defect: `stage_diagrams` in `skills/pub-enhance/scripts/enhance_article.py` writes pending
refresh specifications into `assets/<published-slug>`. `scripts/lib/editorial.py` binds every
file in that directory, so preparing refresh visuals can invalidate the old published review
and block production rebuilds before approval. Cover generation shares that directory too.
The source-cache fix therefore isolates research, not the entire refresh workflow. A future
repair must isolate draft assets and promote them with approved content, preserving the old
article and its assets throughout preparation; it needs an end-to-end refresh regression.

The current tree passes **378 tests**, the documentation checker (25 skills, zero problems),
Python compilation and `git diff --check`. Local tests include actual loopback static and
dynamic HTTP routes. They do not represent production deployment or traffic acquisition.

## Remaining gaps

The refresh-asset isolation defect above remains an actionable operational gap at the
ten-round stopping point. Do not treat pending visual refreshes as isolated from production.

No production site or credentials were supplied: there is no authenticated GA4/GSC result,
inspected production scheduler run, deployed framework/CMS pilot, independently assessed
real editorial output, mature traffic/conversion observation, or demonstrated cost effectiveness.
Generic command interfaces and recipes also do not establish support for every framework,
CMS, business model or website type. Source quotations and review attestations improve
accountability but cannot automatically prove factual truth or original value.

The next evidence-producing step is an authorized pilot with baseline analytics, substantive
first-party changes, recorded deployment boundaries, and mature post-period observations.
Include unchanged and failed outcomes, actual costs and confounders; extend observation when
traffic is too sparse. Repeat across materially different site types before claiming broad
effectiveness. Rankings, citations and traffic remain dependent on demand, competition,
platform selection and the quality of the website's actual offering.

See the [round log](improvement-rounds.md), [tested capability ledger](capability-evidence.md),
and [historical initial audit](product-evaluation-2026-09-09.md) for the evidence trail.
