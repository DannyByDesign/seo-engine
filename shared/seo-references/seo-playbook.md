# Sustainable SEO Playbook (2026)

> Read by: `seo-technical-audit`, `seo-metadata`, `seo-structured-data`, `seo-performance`,
> `seo-content-optimize`, `seo-internal-linking`, `seo-maintain`.
>
> This file encodes only durable, policy-aligned strategy — confirmed against Google's own
> documentation and cross-verified independent studies as of mid-2026. Every claim below is
> either an **established fact** (primary source, verbatim or paraphrased faithfully) or a
> **corroborated pattern** (multiple independent sources agree). Where evidence was thin or
> contested, that is stated explicitly rather than smoothed over — an automated agent should
> know the difference between "Google says so" and "an SEO blog says so."

## 1. The one governing principle

Google's ranking systems are built to reward content **created to benefit people**, and to
deprioritize content **created to manipulate rankings** — regardless of how it was produced
(hand-written, outsourced, or AI-generated).
[Creating helpful, reliable, people-first content](https://developers.google.com/search/docs/fundamentals/creating-helpful-content)

This is the test to run before optimizing anything: *does this change make the page more useful
to a person who lands on it, independent of any search engine ever existing?* If yes, it's
durable SEO. If the honest answer is "no, but it should rank better," it's a liability — see
[red-flags.md](red-flags.md).

Practically, this means:
- AI-assisted content production is **not** a policy problem. Google explicitly states it does
  not penalize content for being AI-generated. The problem is **scale without value** — mass-producing
  pages that don't meaningfully help anyone. A 2025 Ahrefs study of ~600,000 pages found a
  statistically negligible correlation (0.011) between AI-content percentage and ranking position —
  there is no "AI content penalty" to route around, only a "low-value-at-scale" penalty to avoid.
- Never build automation that increases publishing *volume* as a proxy for quality. Every skill in
  this system that touches content must justify the change in terms of user value, not just
  "more pages" or "more keywords covered."

## 2. Technical foundation (non-negotiable, not glamorous)

Content that cannot be crawled cannot rank — by any engine, human-facing or AI-facing. This is
the least exciting and most load-bearing layer:
- No accidental `noindex`, blocked-by-robots, or 4xx/5xx on pages meant to be found.
- Correct, non-conflicting canonicalization (see §5).
- Crawlable internal link graph — no orphan pages, no link-only-in-JS-onClick patterns that a
  crawler can't traverse.
- Valid, complete `sitemap.xml`, kept in sync with what's actually indexable.
- `robots.txt` intentionally scoped — see [geo-playbook.md](geo-playbook.md) §4 for the
  AI-crawler-specific nuance (blocking the wrong bot silently opts a site out of AI-search
  visibility while believing only training was blocked).

`seo-technical-audit` owns this layer; treat any regression here as higher priority than any
content or on-page work, because it silently caps the ceiling of everything else.

## 3. Core Web Vitals (the INP era)

Core Web Vitals remain a **live, non-deprecated input** to Google's core ranking systems.
Current thresholds ("good," per Google's own documentation):

| Metric | Threshold | Notes |
|---|---|---|
| **LCP** (Largest Contentful Paint) | < 2.5s | Loading performance |
| **INP** (Interaction to Next Paint) | < 200ms | Responsiveness — replaced FID in March 2024 |
| **CLS** (Cumulative Layout Shift) | < 0.1 | Visual stability |
| TTFB (Time to First Byte) | < 800ms | Cited by secondary sources as a supporting signal, not one of Google's three official Core Web Vitals |

[Understanding Core Web Vitals and Google search results](https://developers.google.com/search/docs/appearance/core-web-vitals)

Google's own framing is deliberately measured: good CWV "aligns with what our core ranking
systems seek to reward" — it is a **differentiator among pages that are already comparably
relevant**, not a dominant ranking factor that overrides relevance. Don't let a client pursue a
perfect Lighthouse score at the expense of content relevance; do treat CWV regressions as real,
Google-endorsed, sustainable technical debt to fix.

Field data (real-user CrUX metrics) is the authoritative signal, not lab data (PSI's synthetic
Lighthouse run). `seo-performance` should treat PSI's lab score as a diagnostic tool and CrUX
field data as the number that matters for ranking-relevant reporting. See
[api-reference.md](api-reference.md) for the CrUX API vs. PSI API distinction — **do not assume
Google is deprecating field data from the PSI response**; that claim was investigated and could
not be confirmed against current official docs. Treat it as unverified.

## 4. E-E-A-T: what it actually is, and isn't

E-E-A-T (Experience, Expertise, Authoritativeness, Trustworthiness) is **not a per-page algorithmic
ranking signal you can directly optimize for a score**. Google's own statements are explicit on
two points that are easy to conflate:

1. E-E-A-T is a **Quality Rater Guidelines framework** — used by human search-quality raters to
   evaluate how well Google's *systems* are performing, which feeds back into algorithm training
   and evaluation. It is not a scored field on an individual page.
   [E-E-A-T and quality raters](https://developers.google.com/search/blog/2022/12/google-raters-guidelines-e-e-a-t)
2. Within that framework, Google gives **extra weight specifically to YMYL topics** (Your Money
   or Your Life: health, financial stability, safety, civic/societal well-being) — it is not
   applied uniformly to all content.
   [Creating helpful, reliable, people-first content](https://developers.google.com/search/docs/fundamentals/creating-helpful-content)
3. Of the four components, Google states **trust is the most important**.

**Practical implication for automation:** don't apply a flat "add author bio + credentials to
every page" template. Scale E-E-A-T investment (visible author identity, credentials, citations,
editorial policy, contact/about transparency) to topic sensitivity — heaviest on YMYL content,
lighter elsewhere. Treat "add E-E-A-T signals" as a proxy for genuine trust-building (real
authorship, real sourcing, real correction policies), not a checklist of cosmetic elements.

## 5. Canonicalization and indexing hygiene

Canonical tags are a common source of silent, compounding damage in automated systems:
- Google Search Console's **URL Inspection** tool/API reveals the canonical URL Google *actually
  selected* for a page, which can diverge from the one declared in the page's `<link rel="canonical">`.
  A periodic diff of declared-vs-selected canonical is a legitimate automated integrity check, not
  paranoia. [Canonicalization troubleshooting](https://developers.google.com/search/docs/crawling-indexing/canonicalization-troubleshooting)
- A documented real-world attack vector is **compromised sites having malicious cross-domain
  `rel=canonical` tags or spammy 3xx redirects injected** — this is a security concern as much as
  an SEO one. `seo-redirects` and `seo-technical-audit` should flag any canonical pointing off-domain
  as a hard stop requiring human review, not an auto-fix.
- Canonical loops (A→B→A) and canonical chains (A→B→C) both suppress indexing of intermediate
  pages; resolve to a single, stable target.

## 6. Internal linking and topical authority

Internal links are the mechanism by which a crawler (and a reader) discovers relative importance
and topical relationships. Sustainable practice:
- No orphan pages — every indexable page should be reachable from at least one other indexed page
  via a normal `<a href>`.
- Link depth matters: pages more than ~3-4 clicks from the homepage get crawled and refreshed less
  often.
- Contextual, in-content links to topically related pages build **topical authority** — a cluster
  of interlinked pages on a subject signals depth of coverage more than any single page can alone.
  This is a durable strategy (not a hack) because it mirrors how a genuinely comprehensive
  resource on a topic would naturally link itself.
- Anchor text should be descriptive of the destination, not generically "click here" — this is
  both an accessibility and a relevance signal.

`seo-internal-linking` should build and maintain a link graph from crawl data, surface orphans,
and suggest **contextual** link insertions (linking from existing relevant sentences), never
injected boilerplate link blocks — the latter reads as manipulative and provides little real value.

## 7. Content freshness

Freshness matters, but the size of the effect is channel-dependent (see
[geo-playbook.md](geo-playbook.md) §5 for the AI-citation-specific freshness data, which is
better-quantified than the traditional-SEO freshness literature). For classic Search: content
that is meaningfully updated (not just re-timestamped) to reflect current facts, current
year-specific data, or corrections stays relevant longer and avoids "stale answer" displacement
by newer competing content.

**Do not "freshness-fake"** — changing a timestamp or a single sentence without substantive
content improvement is exactly the kind of manipulation-for-ranking Google's helpful-content
guidance targets, and it's a fragile tactic that degrades trust the moment a reader notices.
`seo-content-optimize` should only flag a page as "needs refresh" when there is a real,
identifiable staleness signal (outdated facts, superseded data, broken references), never on a
pure time-since-last-edit basis.

## 8. Structured data — traditional value, separate from GEO claims

Schema.org / JSON-LD markup has well-established value for **traditional Search**: eligibility
for rich results (article, product, FAQ, breadcrumb, etc. — subject to Google's ongoing curation
of which types get visual treatment), and it helps Google's systems parse page structure and
entities more reliably, per Google's own statements (not a ranking factor per se, but an
extraction aid).

Do **not** conflate this with a claim that structured data drives AI-search citation — the
evidence does not support that; see [geo-playbook.md](geo-playbook.md) §3. `seo-structured-data`
should implement and validate schema for its proven traditional-SEO value (rich-result eligibility,
crawler comprehension), not market it internally as a GEO lever.

## 9. What this playbook deliberately excludes

No keyword-density targets, no "optimal word count," no exact-match-domain tactics, no link-building
schemes, no PBNs, no negative-SEO countermeasures framed as growth tactics, no "post X times per
week" cadence rules. These either don't survive scrutiny as causal levers, or cross into
[red-flags.md](red-flags.md) territory. If a tactic can't be justified by "this makes the page
more useful to a real reader," it does not belong in this system.

## Sources

- [Creating helpful, reliable, people-first content](https://developers.google.com/search/docs/fundamentals/creating-helpful-content) — Google Search Central
- [Understanding Core Web Vitals and Google Search results](https://developers.google.com/search/docs/appearance/core-web-vitals) — Google Search Central
- [E-E-A-T and quality raters](https://developers.google.com/search/blog/2022/12/google-raters-guidelines-e-e-a-t) — Google Search Central Blog
- [Canonicalization troubleshooting](https://developers.google.com/search/docs/crawling-indexing/canonicalization-troubleshooting) — Google Search Central
- Ahrefs, "AI content vs. rankings" study (2025, ~600K pages, correlation 0.011)
