---
name: geo-optimize
description: Audits AI-search (GEO) readiness — checks robots.txt against the per-vendor AI-crawler table so a site doesn't accidentally block ChatGPT/Claude/Perplexity/Bing crawlers, checks AI-crawler cloaking, flags JS-dependent content invisible to AI crawlers (none render JS), and can scaffold a narrow llms.txt for agentic use only. Invoke to improve/verify AI visibility, after a robots.txt/bot-blocking change, when a client-rendered page may hide content from AI crawlers, or when llms.txt/schema.org is proposed as a "GEO fix" needing a reality check.
---

# geo-optimize

Read [geo-optimize instructions](../../05-execute/geo-optimize/SKILL.md) and follow that skill before acting.
Resolve its scripts and references from that canonical directory, not this discovery adapter.
Run commands from the user's website repository; keep all site-specific state there.
