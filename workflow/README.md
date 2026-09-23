# Autonomous organic growth

Start a fresh workspace with `seo-setup`. After onboarding, read the saved brand brief and
continue with `seo-growth`; reuse established goals instead of restarting the interview. The host agent supplies reasoning, browsing,
code editing and its available tools; this engine supplies domain instructions, API clients,
evidence memory and execution/measurement checks. No second paid model is required for
strategy when the host agent can do the work itself.

| Order | Responsibility | Existing specialist tools |
|---|---|---|
| [00 Onboarding](../00-onboarding/README.md) | Establish one-site goals, brand brief, access and setup progress | seo-setup |
| [01 Understand](../01-understand/README.md) | Discover the business, repository and operating envelope | Agent discovery and strategy recorder |
| [02 Research](../02-research/README.md) | Derive seeds and investigate customers, competitors and demand | seo-keyword-research, geo-monitor, external API clients |
| [03 Position](../03-position/README.md) | Decide audiences, differentiation and research-backed messaging | Agent reasoning; optional pub-strategy for an owned publication |
| [04 Choose](../04-choose/README.md) | Select a useful acquisition intervention and make its brief | seo-growth opportunity assessment |
| [05 Execute](../05-execute/README.md) | Edit the actual site, validate, deploy and verify | Content, technical, metadata, linking, schema, performance and publication skills |
| [06 Learn](../06-learn/README.md) | Evaluate outcomes, revise the strategy and schedule next work | Traffic reports, seo-maintain, pub-monitor |

Onboarding has its own directory; the six phase directories own the ongoing workflow. Each phase contains its actual
skill folders and scripts; `skills/` contains compatibility symlinks for existing callers.
`scripts/lib/` contains shared implementation rather than a second competing workflow.

Read only the next needed stage plus the [artifact contract](contract.md). The first invocation
should inspect the target and write its understanding, not ask the owner to supply keywords,
competitors, positioning or briefs. Research missing facts with available tools. Ask only for
facts/access/decisions that cannot be recovered and materially block the next action. Work on
independent useful tasks while waiting. Reuse established publishing and spending authority.

The agent writes `.seo-engine/state/strategy/{understand,research,position}.json` through
`run_strategy.py`; immutable revisions preserve the reasoning trail. Each downstream record
binds its parents and evidence. Changed sources or stale research invalidate downstream state
and route the next cycle back to the earliest affected stage. Artifact validity checks provenance;
realistic agent evaluations establish whether the reasoning and resulting website are useful.

Use the target host's scheduler for unattended recurrence. A copied folder cannot create
credentials, launch a host agent without a runtime, or confer publication authority. Report
those exact setup dependencies; they do not prevent local discovery, research or implementation.
