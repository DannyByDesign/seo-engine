---
name: seo-indexing
description: Manages what search engines have actually indexed — auto-discovers/confirms/submits the sitemap, runs GSC URL Inspection to surface index-coverage and canonical-mismatch issues, and submits caller-supplied or snapshot-diffed changed URLs to IndexNow for Bing/Yandex/etc. (never Google). Invoke after publishing/updating/deleting pages, after a sitemap change, when GSC coverage or "why isn't this indexed" comes up, or during a routine seo-maintain pass. Not for keyword/ranking research (seo-rank-tracking) or crawl audits (seo-technical-audit).
---

# seo-indexing

Read [seo-indexing instructions](../../05-execute/seo-indexing/SKILL.md) and follow that skill before acting.
Resolve its scripts and references from that canonical directory, not this discovery adapter.
Run commands from the user's website repository; keep all site-specific state there.
