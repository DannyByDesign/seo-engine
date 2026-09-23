---
name: seo-internal-linking
description: "Builds an alias-folded internal-link graph from a crawl snapshot to find orphan pages (evidenced against an independent sitemap/GSC URL universe, never claimed from crawl data alone), unreachable clusters, and pages more than ~4 clicks deep, then scores existing pages by topical overlap for contextual link-insertion candidates. Invoke when a page isn't indexing/refreshing despite being live, after adding pages, after an IA/navigation change, or in a seo-maintain pass. Not for crawlability/redirect/canonical issues (use seo-technical-audit)."
---

# seo-internal-linking

Read [seo-internal-linking instructions](../../05-execute/seo-internal-linking/SKILL.md) and follow that skill before acting.
Resolve its scripts and references from that canonical directory, not this discovery adapter.
Run commands from the user's website repository; keep all site-specific state there.
