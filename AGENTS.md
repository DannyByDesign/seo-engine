# SEO Engine workspace

This repository distributes an installable engine. Users run it inside their existing
website repositories; each website owns its private context and state.
The skills are Markdown instructions for any capable AI agent, independent of its model.

For "get started", "onboard me", or first-time SEO work, read
`00-onboarding/seo-setup/SKILL.md`. Follow its conversation; do not read every skill or
ask the user to navigate folders, author config, or supply a keyword strategy.
Use your question tool if available, otherwise ordinary chat.

If `.seo-engine/onboarding.json` is complete, read `.seo-engine/knowledge.md` and the
saved next action; continue with `04-choose/seo-growth/SKILL.md` or the relevant specialist.
Resume incomplete onboarding. Don't repeat the interview each session. A different
website needs its own workspace, not a replacement domain in this one's config.

All runtime commands use this site's workspace as cwd (or explicit `SEO_REPO_ROOT`).
Resolve script paths from the skill's actual location. No host-specific environment variable,
model subscription, or second model API is required for host-agent research and writing.
Scripted publication generation has its own optional provider requirements.

Read the brand brief before strategy/content work, but confirm publishable firsthand
contributions for each topic under `shared/seo-references/content-interview.md`.
Never treat onboarding answers as blanket publication permission.

For work on the reusable engine itself, edit and test the template; don't onboard it as a
customer website. Keep credentials and brand context out of template files and the writing
corpus. Run the relevant offline tests and `python3 scripts/dev/check_docs.py` after edits.
