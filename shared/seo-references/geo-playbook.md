# GEO Playbook: Generative Engine Optimization (2026)

> Read by: `geo-optimize`, `geo-monitor`, `seo-structured-data` (for the "don't oversell schema"
> caveat), `seo-content-optimize`.
>
> GEO — getting cited by ChatGPT, Perplexity, Google AI Overviews/AI Mode, Claude, Gemini, and
> Copilot — is a much younger, much less settled field than traditional SEO. This playbook is
> deliberately honest about that: it separates **established fact** (primary-source, e.g. a
> vendor's own documentation, or a large controlled study with disclosed methodology) from
> **corroborated pattern** (multiple independent sources agree, still correlational) from
> **single-source speculative claim** (an individual vendor blog's number, uncorroborated,
> often unfalsifiable). Do not let a skill present a speculative claim as settled strategy.
>
> The single most important finding in this playbook is negative: **the most commonly recommended
> GEO tactic — publishing an `llms.txt` file — does not work.** Read §1 before anything else.

## 1. llms.txt: adoption is real, effect is not

A June 2026 Ahrefs server-log study of 137,210 domains (via Ahrefs' Web Analytics customer base —
note this skews more technical/SEO-aware than the general web, so treat the adoption figure as an
upper bound) found:

- **28% of sampled domains publish an llms.txt file** (~38,360 sites) — adoption is real and
  growing (one independent tracker cites an 8.8x increase from June 2025 to May 2026).
- **97% of published llms.txt files received zero requests** in May 2026.
- Of the small remainder that *did* get hit, 96% of requests were from bots (not humans), and of
  those bot hits, the large majority (~77-80%) came from generic/unknown crawlers and SEO audit
  tools — **not** named AI platforms. AI retrieval bots specifically accounted for only ~1.1% of
  AI-bot requests overall.
  [Ahrefs: llms.txt study](https://ahrefs.com/blog/llmstxt-study/)
- An independent 90-day, 60,000-visit experiment (Otterly.AI) found AI platforms **never cited a
  `.md` URL** — only ordinary HTML pages.
- Google's own AI-search guidance states llms.txt does not change what gets cited in AI Overviews
  or AI Mode.

**Conclusion: do not build or recommend llms.txt as a citation-driving mechanism.** `geo-optimize`
may still generate one for the narrow, distinct use case of **agentic browsing / agent-to-agent
machine readability** (a coding agent or automation reading your site's own capability map) — but
never present it internally or to a user as something that improves AI-search visibility. If a
target repo already has one, leave it be (harmless) but don't prioritize maintaining it.

## 2. What actually predicts AI citation: it's complicated, and platform-dependent

Two Ahrefs studies point in apparently different directions, and the honest synthesis is that
**AI platforms do not behave like a single monolith**:

- **38% of Google AI Overviews citations come from the top 10 Google organic results** — makes
  sense, since AI Overviews draws heavily from Google's own existing web index and ranking.
  (Moderate confidence; one adversarial review pass split 2-1 on this exact figure.)
- But across a broader 15,000-query study spanning multiple AI assistants, **only ~12% of
  AI-cited URLs ranked in Google's top 10**, and roughly 80% of AI citations didn't rank in
  Google's top 100 *at all*. Overlap with Google's top 10 varies sharply by platform — Perplexity
  highest (~28.6%), ChatGPT lowest (~6-8%).
  [Ahrefs: AI search overlap](https://ahrefs.com/blog/ai-search-overlap/)

**Practical synthesis:** Google AI Overviews is the one AI surface where traditional Google-rank
optimization (everything in [seo-playbook.md](seo-playbook.md)) directly transfers, because it's
built on the same index. ChatGPT, Perplexity, and Claude draw from a wider, differently-weighted
pool — ranking well in Google is helpful but far from sufficient for those surfaces. Treat "rank
well organically" as a floor, not a GEO strategy in itself.

## 3. Structured data (schema.org) does not have proven AI-citation benefit

This directly contradicts a widespread GEO-vendor claim, so it's stated plainly: **there is no
credible evidence that adding schema.org markup increases AI-search citation.**

- Google's own documentation states verbatim: **"There's also no special schema.org structured
  data that you need to add"** for AI Overviews or AI Mode.
  [AI features and your website](https://developers.google.com/search/docs/appearance/ai-features)
- The best available controlled test (Ahrefs, May 2026; difference-in-differences, 1,885 pages
  that added JSON-LD vs. matched controls from a 6M-URL base, 30-day window) found: ChatGPT +2.2%
  and Google AI Mode +2.4% (both statistically indistinguishable from zero), and Google AI
  Overviews **−4.6%** (a statistically significant *decrease*). Caveat Ahrefs itself flags: every
  tested page already had 100+ AI Overview citations before the test, so this measures "does
  schema help pages already visible," not cold-start visibility.
- Contradicting vendor claims (e.g., "+350% from FAQ schema") trace to single uncontrolled case
  studies with confounded variables (content and schema changed simultaneously, no control group)
  — treat these as **single-source speculative**, not evidence.

**What this means for `seo-structured-data`:** keep implementing and validating schema — it has
real, separately-justified value for classic rich results and crawler comprehension (see
[seo-playbook.md](seo-playbook.md) §8) — but never justify a structured-data task internally as
"this will improve AI citation." It won't reliably, and may occasionally correlate with a slight
decrease on some surfaces.

## 4. AI crawler access: precise, per-vendor guidance

This is one of the highest-leverage, most commonly misconfigured areas — many sites accidentally
block the crawler that actually matters for citation while believing they only blocked "AI
training," or vice versa. `geo-optimize` should audit `robots.txt` against this exact table, not
a generic "block/allow all AI bots" toggle.

| Vendor | Crawler | Purpose | Blocking it means |
|---|---|---|---|
| OpenAI | `GPTBot` | Model training only | **No effect on ChatGPT search/citation** |
| OpenAI | `OAI-SearchBot` | Powers ChatGPT search citations | Site excluded from ChatGPT search answers (may still appear as a bare navigational link) |
| OpenAI | `ChatGPT-User` | Live fetch during user actions/browsing | Breaks live-fetch features, not indexing |
| Google | *(standard Googlebot)* | Same index powers AI Overviews/AI Mode | Google states there are **no additional crawl requirements** for AI Overviews — it uses the standard Search index |
| Google | `Google-Extended` | Training/grounding data for the Gemini app & Vertex AI | **Does not affect AI Overview/AI Mode inclusion or ranking** ; Google now offers a separate Search generative AI control (see current guidance below) |
| Anthropic | `ClaudeBot` | Model training only | No effect on Claude's live web-search citations |
| Anthropic | `Claude-SearchBot` | Indexing for Claude's search quality | Blocking reduces/prevents indexing → less visibility and accuracy in citations |
| Anthropic | `Claude-User` | Live fetch for user-directed web search | Blocking reduces visibility for user-directed queries |
| Perplexity | `PerplexityBot` | Builds/refreshes the citation index | Blocking excludes from citations (page may still show as domain/headline/summary) |
| Perplexity | `Perplexity-User` | Live fetch | Affects live-fetch, not the standing index |
| Apple | `Applebot-Extended` | Training/Apple Intelligence generation (opt-out model) | Blocking doesn't affect regular `Applebot`, which still powers Siri/Spotlight/Safari results |
| Amazon | `Amazonbot` | Indexing for Alexa/search answers | Blocking removes from Alexa/search answer citations |
| Bing/Copilot | `Bingbot` / `BingPreview` | Single unified crawler and index | Blocking removes the site from **both** classic Bing results and Copilot citations — there is no separate "training-only" bot to block selectively |

**Caveat on Perplexity:** Cloudflare documented undeclared "stealth" crawlers impersonating Chrome
and rotating ASNs across tens of thousands of domains to evade robots.txt/WAF blocks, later
attributed in Cloudflare's reporting to Perplexity-adjacent infrastructure; Perplexity disputed the
attribution. Treat this as a **corroborated but disputed pattern** — meaning a `robots.txt` block
on `PerplexityBot` is not a airtight guarantee of exclusion, and this is a live, unresolved
controversy rather than settled fact.

Scale context (Cloudflare Radar, aggregate data): roughly 80% of all AI-crawler traffic is for
training, 18% for search/citation indexing, 2% for live user actions; Googlebot alone reaches
roughly 3x more pages than GPTBot.

`geo-optimize`'s robots.txt check should flag: any blanket `Disallow` rule that inadvertently
catches a *-SearchBot or *-User crawler, and any AI-crawler allowance the site owner didn't
consciously choose (defaults should be reviewed, not assumed).

## 5. Content: what's actually evidence-backed vs. vendor mythology

The Princeton/Allen Institute/Georgia Tech/IIT Delhi "GEO" paper (Aggarwal et al., KDD 2024,
[arXiv:2311.09735](https://arxiv.org/abs/2311.09735)) is the only rigorous, disclosed-methodology
study of content-level interventions found in this research. It tested 9 content-modification
strategies against a synthetic generative-engine benchmark (10,000 queries, 25 domains):

- **Adding citations/sources, adding direct quotations, and adding statistics each produced a
  30-40% relative improvement** in how much the LLM-judge favored the modified content.
- Keyword stuffing produced no improvement (and hurt on one metric).
- **The paper did not test headers, H2/H3 structure, bullet/numbered lists, or FAQ formatting at
  all.** Multiple vendor blogs cite this paper as proof that "lists and headers boost AI
  citation by 40%" — that is a misattribution. The paper's actual finding is about *substantive*
  content additions (evidence, quotes, data), not document structure.
- Caveat: the benchmark used a synthetic GPT-3.5-based generative engine and an LLM-judged
  "subjective impression" score, not production ChatGPT/Perplexity/Google systems — treat the
  magnitude as indicative, not a guaranteed real-world multiplier.

**Actionable, evidence-backed content guidance:** when writing or improving a page, favor citing
sources, including direct quotations from authoritative references, and including concrete
statistics/data over restating claims in prose without support. This is also just good writing —
another sign it's a durable tactic rather than a hack.

**No credible evidence supports:** a specific optimal word count per "chunk" (a 134-167-word
claim was specifically investigated and refuted), a specific heading structure requirement, or
listicle/table formatting as citation drivers. Treat these as unsubstantiated until better
evidence exists.

## 6. Entity and brand signals

- **Brand mentions (unlinked, plain-text) correlate with AI visibility far more strongly than
  backlinks do.** Ahrefs' 75,000-brand study found branded web mentions at Spearman r≈0.664 vs.
  Domain Rating r≈0.326, referring domains r≈0.295, and raw backlink count r≈0.218 — brand
  mentions are roughly 2-3x more correlated than any traditional link-authority metric. Ahrefs'
  own conclusion: all measured factors are "moderate to very weak" correlations, and correlation
  is not causation — but the *relative* ordering (mentions > authority > links) is a useful
  prioritization signal. [Ahrefs: brand visibility factors](https://ahrefs.com/blog/ai-overview-brand-correlation/)
- **Wikipedia is a major, well-documented influence on LLM outputs** — one study (5,127 prompts
  across GPT-4o, Claude 3.5, Gemini 1.5) found Wikipedia content influenced ~27-34% of responses
  depending on model, rising to ~58% for definitional queries. This traces to Wikipedia's outsized
  presence in training data, not to any on-page tactic a site owner controls directly — but it
  means a Wikipedia presence (where genuinely notable/verifiable) is a real, if slow, entity-authority
  lever.
- Google's Knowledge Graph itself is substantially built from Wikidata/Wikipedia (migrated from
  Freebase 2014-2016; ~72% of person-entity attributes reportedly sourced from Wikipedia
  infoboxes) — this is an entity-recognition pathway distinct from generative-AI citation, but
  relevant to any "does this site/brand have a recognized entity" question.
- **NAP (name/address/entity) consistency claims for AI-search specifically are unsubstantiated**
  — this is a local-SEO concept applied to AI search by analogy in vendor blogs, with no vendor
  documentation or study confirming it matters for LLM citation. Don't build automated "NAP audit
  for GEO" logic on this basis.

**Scope honesty — the largest GEO levers are off-site, and outside this system's write-scope.**
The strongest measured correlates of AI visibility — brand mentions (r≈0.664 above), community
presence (Reddit/Quora discussion, which multiple 2026 studies place among the most-cited source
categories across AI engines), and Wikipedia — all happen on *other people's sites*. A
repo-embedded agent system can **monitor** the outcomes (citation probes, GA4 AI-referral
traffic, crawler logs — see §9) but cannot and must not manufacture them: automated
mention-building, community posting, or Wikipedia editing for visibility crosses directly into
[red-flags.md](red-flags.md) §1 territory (link-spam/reputation-abuse adjacency), and Wikipedia
editing for promotion violates its conflict-of-interest policy. The honest framing every skill
should carry: **on-site work (this system's domain) is necessary but not sufficient for AI
visibility.** When crawler access is clean, content is solid, and visibility is still flat, the
remaining levers are off-site (earned media, genuine community presence, entity notability) —
the right output is that conclusion stated plainly, not another round of on-site tactic
iteration.

## 7. Freshness: real, but platform- and surface-dependent

An Ahrefs study of ~17 million cited URLs across ChatGPT, Perplexity, Gemini, Copilot, Google AI
Overviews, and Google organic found AI-cited pages average **1,064 days old vs. 1,432 days for
organic results (25.7% "fresher")** — but the effect size varies sharply by platform:

| Platform | Average age of cited content |
|---|---|
| ChatGPT | ~958 days (strongest freshness preference) |
| Copilot | between ChatGPT and Gemini |
| Gemini | between Copilot and Perplexity |
| Perplexity | closer to organic |
| **Google AI Overviews** | **~1,432 days — statistically identical to organic, no freshness preference** |

[Ahrefs: do AI assistants prefer fresh content?](https://ahrefs.com/blog/do-ai-assistants-prefer-to-cite-fresh-content/)

Widely-repeated claims of a "13-week rule" or "3.2x more citations for content under 30 days old"
are **unsubstantiated single-source claims** with no disclosed methodology, and are directly
contradicted by the primary data above (average cited-content age is measured in *years*, not
weeks). `seo-content-optimize` should treat freshness as a real but modest signal, strongest for
ChatGPT, essentially absent for Google AI Overviews specifically — and should never recommend
cosmetic timestamp updates (see [seo-playbook.md](seo-playbook.md) §7 and
[red-flags.md](red-flags.md)).

## 8. Authorship / E-E-A-T for AI citation: mostly unproven

Google's own position is that E-E-A-T is a human-rater evaluation framework, not a per-page
ranking signal (see [seo-playbook.md](seo-playbook.md) §4) — and Google has made **no comparable
public statement** about authorship/credentials mattering specifically for AI Overview source
selection. Commonly repeated statistics ("named bylines get 1.9x more AI citations," "YMYL content
with author credentials is 3.5x more likely cited") trace to vendor blog posts with **no disclosed
methodology or sample size** — these are speculative extrapolations, not findings.

The one concrete, multiply-corroborated mechanism (via independent reverse-engineering research,
not an official vendor statement) is that **Perplexity appears to weight a "trust seed" allowlist
of domains** (government, established news, Wikipedia, major publications) plus cross-source
corroboration — this is a domain-level trust signal, not an individual-author-credential signal.

**Practical stance:** keep doing genuine E-E-A-T work (real bylines, real credentials, real
editorial standards) because it's good practice and plausibly helps indirectly via traditional
authority and trust — but don't oversell it internally as a quantified AI-citation lever with a
specific multiplier attached.

## 9. Measuring AI visibility without expensive tools

The engine samples configured models through **OpenRouter**, using one account and Exa web
search. `AI_VISIBILITY_MODELS` selects the models; citations come from response annotations.
These are API samples, not the consumer chat products or Google AI Overviews/AI Mode.
The search engine and model are part of each measurement identity, so changing either starts
a separate series. Do not splice previous direct-vendor results into the new series.

Use fixed, repeatable prompts and multiple samples. See [api-reference.md](api-reference.md)
for setup and optional commercial trackers (Profound and Otterly.AI) as separate evidence.

**Single probes are noise.** LLM answers are stochastic — sampling temperature, retrieval
nondeterminism, and per-request index variance mean one probe per prompt/provider is a coin
flip, not a measurement. A "we lost our ChatGPT citations!" alarm built on one API call is
usually just the model answering differently this time. Measurement discipline this system
implements (and any DIY tracker should copy): **N samples per prompt×provider** (default 3;
majority vote = "cited"); **a provider API error is its own state** — recorded as `error`,
excluded from gained/lost diffs, never conflated with "not cited"; and **loss alerts are
flap-damped** — a citation is reported as lost only after two consecutive runs without it
(the first miss is a low-severity "possible loss, confirming next run"). Costs scale as
providers × prompts × samples; that multiplier is the price of a signal worth acting on.

Complementary, zero-API-cost signals:
- **GA4's native "AI Assistant" channel** (shipped 2026-05-13; Medium=`ai-assistant`) automatically
  buckets referral traffic from ChatGPT, Gemini, Claude, Copilot, DeepSeek, and Grok — but
  **excludes Perplexity**, which still lands under generic Referral. Add a custom channel-group
  rule matching `perplexity\.ai` (and any other AI referrer domain not yet covered) above the
  default Referral rule.
- **Cloudflare Radar's free "AI Insights" dashboard** (radar.cloudflare.com/ai-insights) tracks
  AI-crawler volume and crawl-to-referral ratios in aggregate, and in more detail for
  Cloudflare-proxied sites.
- **Server-log analysis** against the maintained AI-crawler user-agent list from the
  `ai-robots-txt/ai.robots.txt` project — a simple, free, always-current way to see which AI
  crawlers actually visit, independent of any vendor's dashboard.

## 10. Search partners and crawl eligibility

OpenAI uses multiple search partners and its own crawler. Bing discovery is useful, but
Bing indexation is not a documented universal prerequisite for ChatGPT citations. Allow
OAI-SearchBot if search discovery is desired; GPTBot is a separate training control.
ChatGPT-User requests are user-triggered and do not establish indexing. IndexNow submits
updates to participating engines; it does not guarantee inclusion, ranking or ChatGPT visits.
See [OpenAI crawlers](https://developers.openai.com/api/docs/bots) and
[ChatGPT search](https://help.openai.com/en/articles/9237897-chatgpt-search).

Google now provides a separate [Search generative AI control](https://support.google.com/webmasters/answer/16908024).
Inspect that control when diagnosing AI-search eligibility. Do not infer its setting from
Google-Extended robots rules. Recheck current official documentation before changing policy.

## 11. Rendered content and accessible HTML

Google AI search uses Google's index, including its rendering pipeline. Do not claim a
client-rendered page is invisible to every AI answer engine. Serving substantive accessible
HTML improves reliability for raw-HTML fetchers and users, but prioritize from actual
raw/rendered evidence. `check_js_visibility.py` flags likely empty shells; a rendered
comparison confirms the gap. Serve equivalent content to users and crawlers.

Google's [AI search guidance](https://developers.google.com/search/docs/fundamentals/ai-optimization-guide)
requires no special AI schema, fixed chunk length or `llms.txt`. Useful original content,
indexability and reader experience remain the foundation. These are eligibility and quality
principles, not guaranteed traffic interventions.

## Sources

- [Ahrefs: We analyzed 137,210 domains — llms.txt study](https://ahrefs.com/blog/llmstxt-study/)
- [Ahrefs: Only 12% of AI-cited URLs rank in Google's top 10](https://ahrefs.com/blog/ai-search-overlap/)
- [Ahrefs: Top brand visibility factors in ChatGPT, AI Mode, AI Overviews](https://ahrefs.com/blog/ai-overview-brand-correlation/)
- [Ahrefs: Do AI assistants prefer fresh content?](https://ahrefs.com/blog/do-ai-assistants-prefer-to-cite-fresh-content/)
- [Google: AI features and your website](https://developers.google.com/search/docs/appearance/ai-features)
- [Aggarwal et al., "GEO: Generative Engine Optimization," KDD 2024 — arXiv:2311.09735](https://arxiv.org/abs/2311.09735)
- [OpenAI crawler documentation](https://developers.openai.com/api/docs/bots)
- [Anthropic crawler documentation](https://support.claude.com/en/articles/8896518)
- [Perplexity crawler documentation](https://docs.perplexity.ai/docs/resources/perplexity-crawlers)
- [Cloudflare: From Googlebot to GPTBot](https://blog.cloudflare.com/from-googlebot-to-gptbot-whos-crawling-your-site-in-2025/)
- [Cloudflare: Perplexity stealth crawler report](https://blog.cloudflare.com/perplexity-is-using-stealth-undeclared-crawlers-to-evade-website-no-crawl-directives/)
