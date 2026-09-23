---
name: seo-redirects
description: "Audits redirects at the config-source level: multi-hop chains, loops, redirect-to-redirect targets, and drift between the framework's declared redirect config (next.config.js, vercel.json, _redirects, .htaccess, nginx) and live behavior; validates a pre-migration redirect map (--old-urls-file) as a launch gate. Invoke before/after URL restructures or domain moves, or when a redirect chain/loop finding needs its governing config rule located. For broad crawl health checks that only surface redirect symptoms, use seo-technical-audit."
---

# seo-redirects

Read [seo-redirects instructions](../../05-execute/seo-redirects/SKILL.md) and follow that skill before acting.
Resolve its scripts and references from that canonical directory, not this discovery adapter.
Run commands from the user's website repository; keep all site-specific state there.
