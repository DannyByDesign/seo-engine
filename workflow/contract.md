# Agent-authored strategy contract

Use `04-choose/seo-growth/scripts/run_strategy.py --action record --section understand|research|position --file INPUT.json`.
The host agent creates INPUT from its work; these are not owner questionnaires. Store scratch
JSON and source responses in the target's ignored `.seo-engine/reports/`. Accepted records
live in `.seo-engine/state/strategy/`; each has an immutable revision and current pointer.

Every section contains `author` (agent identity is valid), `evidence`, `claims`, and `unknowns`
(list, empty when none). Evidence IDs must be unique across sections. Example evidence:

```json
{"id":"product-export","kind":"repo","path":"src/product.json","quote":"CSV export","observed_on":"YYYY-MM-DD"}
```

External evidence additionally records `url` and uses kind `web`, `api`, `customer`, or
`analytics` as appropriate. `path` is a real local snapshot, and `quote` must occur verbatim
there. Use the actual collection date; writing a current date on an old observation is not
fresh research. Never save auth headers or credentials. Example claim:

```json
{"text":"The product supports CSV export.","kind":"fact","evidence_ids":["product-export"]}
```

Use `kind: hypothesis` for an inference; cite evidence when available. A JSON validator cannot
establish that the quotation entails the claim; the agent must inspect meaning and context.
Facts and hypotheses in copy briefs need the same distinction. Internal hypotheses are not
permission to publish unsupported factual claims.

## Understand

Required: `business`, `conversion_goal` (strings); `audiences`, `source_files`, `seed_queries`
(nonempty lists); `commands` containing actual `test` and `build` argv arrays. `source_files`
must exist. At least one inspected repository evidence item is needed. Add discovered
`site_url`, geography, language, product facts, constraints and authority notes as relevant.
Represent unavailable business inputs in `unknowns`, not fake facts or empty placeholder claims.

## Research

Required: `market_summary` (string), `questions`, `competitors`, `opportunities` (nonempty lists).
A competitor item can report that a real investigation found no direct commercial competitor;
retain the actual search alternatives and evidence. At least one external evidence item is
required. Questions and competitor observations should reference evidence IDs.

`opportunities` uses the existing opportunity schema: two to ten objects with `id`, `query`,
`audience`, `intent`, `page` (site-relative), `action`, `original_value`, `business_reason`,
`business_value` (integer 1–3), `effort_hours` (positive), and `evidence[]`. Each candidate's
evidence has `kind` (`customer_question`, `gsc`, `serp`, `keyword_data`), `reference`,
`observation`, `observed_on`, and preferably `snapshot` (repo-local path). These entries
describe inspected research; assertions without actual evidence cannot justify selection.

## Position

Required strings: `audience`, `problem`, `promise`, `differentiation`. Required nonempty lists:
`message_rules`, `copy_briefs`. A copy brief contains `page`, `reader_job`, `angle`, `cta`,
and `claims[]`; add outline, objections, proof and internal-link plan as useful. It can refer
to evidence IDs from either parent. Parent digests and source hashes are checked on use.

## Execute and learn

The existing `run_growth.py` ledger owns execution; do not create a parallel task system.
Content briefs bind `position_digest` once this strategy workflow is adopted. Technical
repairs can proceed independently with diagnostics. `run_cycle.py` includes strategy status,
artifact paths and actual observations/decisions in the scheduled work packet. The agent
reads those inputs to update strategy; the packet itself is not an autonomous reasoning model.
