---
name: seo-references
description: The research-verified SEO/GEO knowledge base consumed by every other seo-engine skill — evidence-graded playbooks (what drives rankings and AI citations, what measurably doesn't), Google spam-policy guardrails, API reference, and shared setup conventions. Invoke directly only when asked to consult, verify, or update the underlying SEO/GEO research or evidence for a claim; task skills (seo-*, geo-*, pub-*) load the specific sections they need on their own.
---

# seo-references

Reference material, not a task skill. Each file is loaded on demand by the other
seo-engine skills — read the specific section a task needs rather than everything.

## Files

| File | What it holds | Read it when |
|---|---|---|
| [seo-playbook.md](seo-playbook.md) | Durable classic-SEO strategy: helpful-content principle, CWV thresholds, E-E-A-T reality, canonicalization, internal linking, freshness, structured data's real value | Deciding *whether/why* to make an on-page or technical change |
| [geo-playbook.md](geo-playbook.md) | AI-search evidence: llms.txt (§1, doesn't drive citation), what predicts citation (§2), schema's null GEO effect (§3), per-vendor crawler table (§4), content tactics (§5), off-site levers (§6), freshness (§7), E-E-A-T (§8), measurement (§9), search partners and controls (§10), rendered-content visibility (§11) | Anything touching AI visibility, robots.txt AI bots, or GEO claims needing a reality check |
| [publication-playbook.md](publication-playbook.md) | The owned-publication model the `pub-*` skills reproduce: charter and decisions (§1), measured site anatomy (§2), article anatomy (§3), pipeline contracts (§4), truthful attribution (§5), mention policy (§6), monitoring metrics (§7), vendor capability map (§8) | Building, writing for, or judging a publication; any question about why a pub-* script does what it does |
| [red-flags.md](red-flags.md) | **The veto layer.** Google spam policies, manual-action mechanics, self-inflicted technical failures, GEO gotchas, the §6 meta-rule, and §7 (where the lines are for publications) | BEFORE any content- or config-changing action, every time |
| [api-reference.md](api-reference.md) | Auth models, endpoints, quotas, pricing for every integration | Setting up keys, debugging an API failure, budgeting |
| [common-setup.md](common-setup.md) | Shared conventions: config/env resolution, paths & working directory, the snapshot contract, graceful degradation | Running any seo-engine script; resolving any state-file question |

## Evidence-grade legend (used throughout the playbooks)

For website-wide image planning, sourcing, metadata and rendered review, read [images.md](images.md).

- **Established fact** — primary source (vendor's own docs) or a large controlled study
  with disclosed methodology.
- **Corroborated pattern** — multiple independent sources agree; still correlational.
- **Single-source speculative** — one vendor blog's number, uncorroborated. Never
  present these as settled strategy.

## Duplication policy (for anyone editing skill files)

Task-skill SKILL.md files MAY carry: one-sentence pointers with a `§` anchor, hard
constraints as single imperative lines ("Never fabricate `author` — red-flags §6"),
exact env-var names, runnable commands, and negative triggers naming a sibling skill.
They may NOT carry: multi-sentence evidence summaries, any statistic/percentage/date,
tables that exist in a reference file, or framework how-tos — those live here, dated
and maintained in exactly one place. `scripts/dev/check_docs.py` enforces this.
