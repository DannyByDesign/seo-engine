# Letterstory / Phantomstory teardown

Research report and reverse-engineering plan. Prepared 2026-09-08 for thrad (thrad.ai).

> **Build status (2026-09-08, same day):** Part 2 has been implemented under the six decisions
> recorded in its final section. The result is the nine `pub-*` skills plus the brand-mention
> tracker in `geo-monitor`, the shared libraries under `scripts/lib/`, and
> `skills/seo-references/publication-playbook.md`, which is now the maintained home of the
> anatomy documented in Part 1. This file stays as the evidence record; the playbook is what the
> skills cite.

**Method.** Raw-HTML inspection (curl, three user agents) of the four sites you named plus
letterstory.com, phantomstory.com, lettertrace.com, letterbrace.com; every post on the three
Letterstory-built sites (31 articles); DNS, WHOIS, Wayback; image files (dimensions, EXIF, C2PA);
the JS bundle; the in-app browser (console + network); Letterstory's *public* MCP manifest at
`app.letterstory.com/api/mcp` (218 tool schemas, served without auth); Letterstory's docs, pricing,
manifesto, blog, and two sample "Enhance" flows; the open-source Lettertrace repo; Product Hunt and
Hacker News launch threads. Everything marked **observed** was measured directly. Everything marked
**stated** is Letterstory's own claim. Everything marked **inferred** is my reading of the API surface.

---

## Part 1 — Findings

### 1. Who they are

| Entity | What it is | Evidence |
|---|---|---|
| The Letter Company | Parent. Founder Mathew Pregasen. | letter.company, LinkedIn, PH |
| Letterbrace (2023) | The original boutique technical-content agency. $4.8k–$9.8k/mo retainers, $2.8k per research-heavy article, $280/hr. Clients: PostHog, Retool, Modal, ElevenLabs, Oso, Evervault, Credal… | letterbrace.com |
| Letterstory | The platform that grew out of the agency's internal editing tool. "AI is a bad writer but a great editor." Curate → Write → Enhance → Publish → Monitor. | letterstory.com/manifesto |
| Phantomstory | The "ghost website" product: hosted third-party publications on fresh domains, on autopilot, funneling AI-search authority to a client brand. Launched HN 2026-07-12 (no traction), PH 2026-07-28 (199 upvotes, #5 of day). Claimed "3+ paying customers every day" on LinkedIn. | phantomstory.com, PH |
| Lettertrace | Open-source (MIT), BYOK AI-visibility monitor. Also the "GEO executor" the phantom dashboards run on. | lettertrace.com, GitHub |
| Letterspade | Sister video shop. Irrelevant here. | letterbrace.com |

Pricing (stated): Letterstory Free $0 / 2,500 credits; Starter $100 / 10k; Growth $300 / 30k;
Scale $1,000 / 100k and "third-party phantom sites". Phantomstory is quoted at **$500/mo on
phantomstory.com and $1,000/mo on letterstory.com/phantomstory** (inconsistent); PH: "$500/mo,
1–3 phantom sites, reported domain authority."

Listed Phantomstory customers (stated): Brevy, Cloudflare, Credal, Invoice Butler, Manifolds,
Marble, Nolla, Oso, Peaka, Rove, Ruby, Runlayer, Sansa, Seda, Usercentrics, Vellum, Wonderly.
Integrations: Profound, AirOps (GEO data), Webflow/Framer/Sanity/Contentful/Google Docs (publish).

### 2. The founder's theory, in his words

- "ChatGPT and Claude are smart cookies. They know a brand will always rank itself #1, so they
  trust third-party sources instead." (PH launch comment)
- "We don't do placements. At all." Phantoms are sponsored third-party blogs on fresh domains the
  client controls, with "organically-built search volume."
- Cadence: "people use our platform to publish 1–2 articles per day but never more." "This is
  *not* a quantity game."
- Brand mentions happen when an article is "around what the brand is actually building," or as
  "light placement" on articles that perform exceptionally.
- Disclosure "is entirely configurable." Some clients have no disclosed relationship; others
  disclose prominently. **"Disclosed publications are cited the same but then referenced less in
  ChatGPT and Claude's response. But they still get cited more than first-party content."**
- Phantoms double as a "marketing sandbox": run content-format experiments on the phantom, copy
  the winner to the first-party blog.
- Under the hood (stated): "adversarial writing kernels, a smart KD-sensitive priority queue, and
  an amazing canvas tools."

### 3. Three of your four sites are one Letterstory template. The fourth is not theirs.

| Site | Registered | Registrar / DNS | Host | Theme | Posts | Sections | Authors |
|---|---|---|---|---|---|---|---|
| llmbillboard.com | 2026-08-28 | Name.com / Vercel DNS | Vercel | `signal` | 14 | 4 | 14 |
| adsinllms.com | 2026-05-23 | Cloudflare / Cloudflare DNS → Vercel | Vercel | `forum` | 8 | 2 | 8 |
| promptsignal.co | 2026-09-02 | Name.com / Vercel DNS | Vercel | `classic` | 9 | 2 | 9 |
| adtech-world.com | 2026-04-08 (domain existed 2002–2011, re-registered) | GoDaddy / Cloudflare | Cloudflare + PHP 8.3 | n/a | 40 | 7 | none (org byline) |

Proof the first three are one system (observed): identical Next.js chunk hashes across all three
sites (same build), the same Supabase storage project (`mcxtywzsmeezbwapdahq`) and the **same
tenant folder** (`a8b36f25-811f-402d-bc38-bdad2f7d3ded`) for every image on all three sites, the
same route set, the same JSON-LD graph, the same `robots.txt` shape, the same `llms.txt` and
`feed.xml` generators. Each site is its own Vercel project (different deployment ids; the API's
`delete_deployment` tears down "its Vercel project"). Letterstory calls the framework
**Lettersprite**; content is baked in at build time and the site is rebuilt on every publish.

Two of the three domains sit at Name.com with Vercel nameservers, which matches Letterstory's
`buy_domain` contract: **"the domain is bought on Letterstory's platform Vercel account under our
registrant (the org never owns it)."** adsinllms.com is registered at Cloudflare and was almost
certainly connected via `connect_domain`. Worth checking who actually owns llmbillboard.com and
promptsignal.co in your account. If Letterstory owns them, the authority you are paying to build is
not portable.

**adtech-world.com** is a different operator entirely: PHP on Cloudflare, `en-IN` locale, GA4,
AdSense (`ads.txt` present), Unsplash stock covers reused across posts, a CRM pixel from
**adbellmedia.com** (a programmatic agency that also sells "Pharma / CBD / Casino backlinks"),
JSON-LD copy-pasted from a template that still points at `adtechworld.io`, and a Cloudflare-managed
`robots.txt` that **disallows GPTBot, ClaudeBot, CCBot, Google-Extended, Amazonbot, Bytespider,
Applebot-Extended and meta-externalagent** with `Content-Signal: ai-train=no`. It never mentions
thrad. It is an aged-domain AdSense/lead-gen site with free tools and "certifications" as link
bait. It cannot be producing GEO traffic from crawler-backed assistants because it blocks them. I
would drop it from the reference set, or keep it only as the contrast case (Section 8).

### 4. Anatomy of a phantom site (observed on all three)

**Routes.** `/` (home: hero + latest + sections), `/posts/<slug>`, `/sections/<slug>`,
`/authors/<slug>`, `/about` (tagline, "What we cover", "Contributors" masthead), `/search`
(`noindex`), `/feed.xml`, `/llms.txt`, `/sitemap.xml`, `/robots.txt`, `/opengraph-image`
(generated 1200×630 PNG for the home page), `/icons/<icon>.svg` logo. No `/posts` index, no tag
pages, no newsletter form (despite "blog and newsletter" in the tagline), no contact, no privacy
page. Custom 404.

**Head, every page.** `<html lang="en" data-theme="…">` carrying the entire theme as CSS custom
properties inline on the root element (`--bg --surface --surface-alt --fg --muted --border
--primary --primary-fg --secondary --accent --link --heading-color --kicker --hero-from --hero-to
--font-display --font-heading --font-body --font-mono --radius --content-width --container-width;
color-scheme`). Google Fonts preconnect + stylesheet. `meta robots: index, follow`;
`meta googlebot: index, follow, max-video-preview:-1, max-image-preview:large, max-snippet:-1`;
`application-name`; canonical; full OG + Twitter `summary_large_image`. Favicon is an inline
base64 SVG.

**Article head, additionally.** `og:type=article`, `article:published_time`,
`article:modified_time`, `article:author` (persona name), `article:section`, `article:tag`,
`og:image` 1200×675 with `og:image:alt = Cover illustration for “<title>”`, cover `<link
rel=preload>` and `fetchpriority=high`.

**JSON-LD graph.** Site-wide `@graph` of `Organization` (`@id #organization`, logo = the SVG icon)
and `WebSite` (`publisher → #organization`, `inLanguage`). Home adds `Blog` with a `blogPost[]`
array of `BlogPosting` stubs (`@id`, `url`, `headline`, `datePublished`). Article adds
`BlogPosting` with `mainEntityOfPage`, `image: [ImageObject{url, caption}]`, `datePublished`,
`dateModified`, `author: Person{name, jobTitle, worksFor→#organization}`, `publisher`,
`isPartOf→#website`, `articleSection`, `keywords`, `inLanguage`, and on posts with a Sources block
a `citation: [CreativeWork{name,url}]` array; plus `BreadcrumbList` (Home → Section → Title).
Author pages: `ProfilePage{mainEntity: Person{@id, name, jobTitle, description, url, worksFor},
hasPart: [BlogPosting…]}`. About: `AboutPage{mainEntity → #organization}`. No `FAQPage`, no
`sameAs`, no `Person.image`, no `Organization.sameAs`.

**Feeds.** `feed.xml` = RSS 2.0 with `dc:creator`, `category` = section, `atom:link rel=self`,
description = dek. `llms.txt` = `# Site`, `> tagline`, `## Posts`, then `- [title](url): dek`
per post (nothing else). `sitemap.xml` with `lastmod` (ISO ms), `changefreq` and `priority`:
home 1.0/daily, sections 0.5/weekly, authors 0.4/weekly, posts 0.7/monthly. `robots.txt` =
`User-Agent: * / Allow: / / Host: … / Sitemap: …`. **No AI crawler is blocked. No cloaking**
(byte-identical HTML to GPTBot, curl, and Chrome). No `text/markdown` negotiation.

**Client side.** Zero analytics or tracking scripts. Console is empty. Network is the page, one
CSS file, nine JS chunks, fonts, images. Measurement happens off-page: every domain has a
`google-site-verification` TXT record (Search Console), and the GEO layer is probed from
Letterstory's side.

**Images.**
- Cover: generated per headline. Original JPEG 2752×1536 (~1.8 MB) with a C2PA manifest (the
  dimension/metadata combination is consistent with Google's Gemini image models). Served through
  Supabase image transforms: `?width=1600&resize=contain&quality=70` for the hero, `width=1200`
  for cards. Alt: `Cover illustration for “<title>”`. Style: flat vector-ish editorial
  illustration in the theme palette (orange/ink/mint on the `signal` site).
- Diagrams: 1–2 per article, PNG 2910×1350 RGBA, deterministic house style (small-caps kicker
  title, one big number or a stepped flow, `Source: eMarketer, 2025` footer line, theme colours).
  Alt text is literally the generation brief: `Diagram: <title>. Visualizes: <one-sentence
  brief>`.
- Gaps worth not copying: no `width`/`height` attributes or `srcset` on any image (CLS risk), and
  Supabase storage answers with `x-robots-tag: none`, so none of the imagery is eligible for
  Google Images.

**Personas.** 8–14 recurring authors per site, generated from a combinatorial name bank (Rossi,
Petrova, Kowalski, Sabatini, Contreras, Haddad, Mbeki, Vance recur across the three sites).
Roles: Staff Writer, Senior Writer, Features Editor, Editor at Large, Columnist, Reporter,
Correspondent, Contributing Editor. Bio template: *"<Name> is a <role> at <Site> covering
<section>. Based in <City>, <First> has written for <Site> since <Year>."* The tenure is
fabricated: "since 2015" on a domain registered eleven days ago. The API confirms this is by
design (`started_at` "may predate the site"). Each author has a slug, an avatar of initials, and
"N stories · City" on the profile page.

**Cadence.** Launch-day burst of 4–5 posts, then one post per day at a stable hour per site
(llmbillboard ≈ 20:00–22:00 UTC, adsinllms ≈ 12:30–14:00 UTC, promptsignal ≈ 19:30–22:00 UTC).
API default for phantoms is 6/week; for client blogs 3/week.

**Network hygiene.** The three sites never link to each other, never link to letterstory.com, and
carry no disclosure of any relationship to thrad. Each occupies a different buyer persona of
thrad's category: llmbillboard = brand marketers ("conversational AI advertising"), adsinllms =
agency trading desks ("buying, bidding, optimizing paid placements inside LLMs"), promptsignal =
data/insights people ("what user prompts reveal about consumer intent").

### 5. Anatomy of an article (31 posts measured)

| Metric | Observed |
|---|---|
| Body length | 1,970–2,930 words rendered (displayed count 2,200–2,650); every post kickered "Long read"; read time ≈ words/220 |
| Structure | H1 → dek → byline (persona, role, date, read time, "Updated …") → share row → cover → "In this article" TOC → 6–8 H2 sections → closing section → "Filed under" → author box → "Next story" → "More in <Section>" ×3 |
| H2 style | 217 body H2s, mean 11.7 words, long declarative sentences; 22 use a colon; only 5 are questions (usually the final "What should X do…?" section). No H3s inside the body |
| Paragraphs | ~40 per post, mean 65 words, ~3 sentences; 2–4 bulleted lists; **zero tables** and zero blockquotes despite the "Create Tables" feature |
| Diagrams | 2 in 25 of 31 posts, 1 in 4, 0 in 2 |
| Opening | First paragraph opens on a cited statistic; second paragraph states the thesis and names a framework ("four dimensions"); the close returns to the opening number and issues a sequenced "if X is the gap, do Y" |
| External citations | 2–34 per post (median 12) to 1–14 hosts. **57% of inline anchors are the number itself** ("$2.08 billion", "18%", "25.5%"); the rest are short noun phrases. Inline links are `rel="noopener noreferrer nofollow" target=_blank` |
| Sources block | 24 of 31 posts end with an `H2 Sources` numbered list (host name as anchor). Those links are **followed** (no `nofollow`) and are mirrored into `BlogPosting.citation[]` |
| Internal links | 0–5 contextual body links per post with descriptive partial-match anchors ("keyword taxonomies to intent-topic frameworks", "multi-touch attribution"). 13 of 44 point to posts published *after* the linking post: the system **retro-links older posts when new ones publish** and bumps `dateModified` (the article you sent me was published 08-28 and modified 09-08 for exactly this reason). The API calls this `relink` |
| Brand mention | **1 of 31 posts links thrad.** Anchor is a statistic ("$25 to $60" CPM) pointing at a thrad.ai guide, nofollow, inside a paragraph about platform divergence. No pitch, no CTA, no "thrad" in the text. The API exposes this as `mention.degree = off | subtle | woven` plus a `rate` for phantom collections |
| Voice | Third-person, no "we"; blunt imperatives ("Start blunt:"); hedges removed; a handful of em dashes survive; heavy use of specific numbers and named sources (eMarketer, Similarweb, Sensor Tower, Seer) |
| Titles | Noun-phrase "X for Y" / "X vs Y" / "How X …", 6–11 words, no clickbait, no year in the title |
| Sections | 2–4 per site; the section is `articleSection`, `article:section`, `keywords`, the breadcrumb, the RSS category, and the nav |

### 6. How the machine behind it is wired (inferred from the 218-tool manifest)

The public MCP manifest is the closest thing to their source code. The important contracts:

**Strategy substrate.** `positioning = {priority_topics[], stances[], avoid_topics[]}`;
competitors (domain → sitemap scrape → topics → `inferred_keyword` + `keyword_priority
high|medium|low`, with `block_from_mentions`); brand context measured from the client's own site
(description, slogan, industries, palette, fonts, logos, socials; provider "context.dev");
`ranking_targets` (≤5 phrases like "best payroll software", each with `mention_framing`;
`suggest_ranking_targets` bases them on `already_strong | white_space | positioning`); `landings`
(URL + free-text "when it's worth citing"; collections with auto-mention "weave a natural mention
and link to any relevant landing page into articles as they're written"; `last_mentioned_at`
tracked). Onboarding steps registry: goals, domain, description, stances, import, flow, enhance,
visuals, gsc, kernel.

**Topic map = the site's information architecture.** Pillars (clusters; `is_priority`,
`is_muted`, `display_name` = the nav label, i.e. the site's *sections*) → spokes (`subtopic`,
`angle`, `brief`, `status open|queued|covered|dismissed`, `client_relevance high|medium|low`,
`source ai|user|geo`, `seo_keyword`, `seo_msv`, `seo_kd`, `article_id`). Spokes with no keyword
are "a pure topical-authority play". Series = coverage obligations ("one post per declared
item"). Seed posts are "the strongest spokes spread across pillars, not the first N."

**Curate.** `generate_suggestions` scores candidate topics on **competitor, GEO, SEO,
cluster-alignment, authority, and cannibalization** signals and emits `headline`, `why`,
`priority`, `score`, `signal_breakdown`, with `suggested | backlog | reserve | queued` states.
Seers add event-driven topics: `github_pr`, `github_release`, `notion_activity`, `spec_change`,
`news_trend`, `regulation_change`, in `suggest` or `auto` mode, with a "holding pen" for drafts
whose substance can't be confirmed against the source.

**Planner.** `cadence_per_week` (phantom default 6), `sourcing_mode topic_map | curate_first |
curate_only`, `approval_mode autopilot | review_window | manual`, `steering_prompt` (the
"direction" string is called "the highest-leverage override"), materialized publish slots,
"days and times de-robotized automatically" (in practice: one post/day at a stable hour).

**Auto-Pen = the per-article pipeline.** `outline{enabled, depth barebones|fleshed_out,
direction_gate}` → `positioning` → `kernel{family}` → `mention{degree, rate}` → `verifier` →
`enhance{flow_id, assignment auto|assigned, reviewerIds}` → `shred` → `relink`, plus an optional
content `template` (`blocks[] = {kind formatted|open, text (markdown), optional}` that "constrains
the SHAPE of a post and never says what it is about"). Research runs in phases
`plan → gather → read → direction → synthesize → verify`, accepts ≤20 `source_urls` and ≤40
`must_include` subsections, and can pause at a direction gate offering `direction_options`.
Writing kernels live on an external "kernel server" (codenames Alder/Aspen/Birch internally,
Spruce/Juniper/Sequoia/Madrona in marketing); the org picks one kernel; a brief goes in, a full
draft comes back. "Adversarial voting" is stated, never shown. Research plus kernel take 20–40
minutes per article.

**Enhance flow stages** (as provisioned for every phantom): `add_links` crawled from the blog's own
sitemap → external sources → the site's visuals (table / venn / generative diagram), with
`text_edit` stages, AI-preselected suggestions, an `awaiting_review` gate, and the internal-link
refresh (`relink`) on. `ensure_collection_enhance_flow` builds the same for a first-party blog.

**Visuals ("Canvas").** Categories: `full_ai`, `semi_structured` (stickers arranged by an LLM
inside an AI region), `line_art`, `generative_diagrams`, `editorial_image`, `table`, `venn`.
Cover styles for a collection: `editorial_image | full_ai | line_art` (default editorial_image,
"one house style"). Multiple image providers (catalog ids like `replicate:…`, a "Bloom" brand
provider), reference-image conditioning from another blog's look, a stock-photo ranker with
credit line, ~45–60 s per cover.

**Publish.** Article record: `title, slug, content (TipTap HTML or md), cover_image (+alt,
+credit), author (+slug, +profile), summary (dek), tags, metadata, paper_trail (audited sources),
published_at (set once), updated_at (only when content changes)`. Publish gate on reviewer
approvals. Connectors: Webflow, Framer, Contentful, Sanity, Google Docs; JSON/MDX export;
webhooks `article.published`, `flow_run.completed`.

**Provisioning a phantom.** `create_deployment(name, description, theme, collection_id,
customer_ref)` → steps `create → deploy → connect → dns` → `subdomain | buy_now | connect_later`.
Rules baked into the schema: the masthead name must **not contain the client's company name**
(rejected server-side); description is one sentence; **54 themes** (`sleek classic minimal
magazine midnight gazette dispatch metro review signal current ledger atelier noir chronicle
verdure couture atlas missive commit apex mint bloom cinder hearth harvest terra verve estate
counsel clinic nook lumen cellar horizon derma meridian keystone vantage cobalt sterling momentum
forum cadence evergreen beacon kernel graphite cortex cipher pulse apiwire bourse folio`); domain
purchases capped at 2 per org and $30 each; `is_test` keeps throwaways off the fleet board.
`configure_phantom` then runs `strategy → visuals → enhance → kernel → planner → map`, and
`onboard_domain` composes everything from a bare client domain: main blog import, org visuals,
enhance flow, a phantom with 3 seed posts (~30 min each), seers, readiness wait, and a Lettertrace
project for the client's AI-visibility tracking.

**Shredder.** A separate service that rewrites each sentence "across multiple LLM providers to
diversify, leaving structure untouched," with `coverage`, `attempts_per_unit`, a content-loss
check per sentence, and a `shareReport` enforcing per-provider ceilings and longest-run limits.
This is a stylometric-diversity / AI-detector-evasion pass. It exists; whether it runs on your
sites is not observable.

### 7. Monitoring: what "actually creating traffic" is measured with

**SEO layer (GSC).** Rolling `14d | 30d | 90d` windows ("data ends ~2 days ago") with the previous
equal window for deltas; `clicks, impressions, ctr, impression-weighted position`; per site, per
post, per query, per cluster/pillar; a per-post indexing proxy `state = awaiting | receiving`
based on `firstImpressionAt`; portfolio rollups across all phantoms; "deterministic insights —
opinionated claims with the numbers spelled out."

**GEO layer (Lettertrace executor).** Per-prompt assistant mention rates; which phantom posts get
cited as sources; "citation-without-mention opportunities"; mention portrayal (sentiment +
context); how the phantom's own posts mention the client; per-site ramp phase `authority →
ramping → steady`; a ~90-day `rate_series` of `citedGroundShare` (our slice of answers that cited
anyone), `ownedCitationRate` (answers citing our posts / answers probed) and `mentionRate`
(answers naming the client / answers probed), **each with Wilson score intervals** because "page
samples are tiny". GEO gap opportunities are synced from Profound / AirOps / Athena
(`prompt_text, share_of_voice, competitor_top, gap_score`).

**7b. Lettertrace internals (from the source code, MIT).** The full read, with every prompt and
formula quoted, is in `research/lettertrace-source-report-2026-09-08.md`. What matters for us:

- **The one rule of their prompt design:** "A monitored prompt only measures something if the
  answer names companies." Their own pilot (Cloudflare vs Runlayer, ~110 queries) measured
  companies-named-per-answer by prompt shape: "List the top 5 companies… by name" 3.7; "Who are
  the main players in X?" 2.5; "Give me a shortlist" 0.8; "How do I…" / "best X for Y" ≈0.1.
  Fisher's exact p≈0.04 on the list-vs-other split. Their generator was rewritten to enforce it.
- **Variation generator** (`VARIATION_SYSTEM`): two thirds of questions must explicitly demand
  named companies/vendors/providers; never ask for a "shortlist" or "how to choose"; never name
  the monitored brand; vary intent and seniority; label each question `general | mid | niche`
  (specificity ladder, roughly even mix); output JSON. Default 8 variations per topic, cap 20.
  **No de-duplication** against existing prompts anywhere in the code; **temperature is never
  set** in any provider call; there is no "control brand" concept for model drift.
- **Mention detection** is deterministic: brand + aliases, longest-alias-first, custom
  `(?<![A-Za-z0-9])…(?![A-Za-z0-9])` boundaries, case-insensitive; markdown-link labels count as
  prose unless the label is an address; bare URLs are blanked (length-preserving) so a citation
  is never a mention; **the domain label is never a term** (documented false-positive incident:
  you.com matching "you"). Output: `count` and `firstPosition` (offset/length, 0..1).
- **Enrichment** runs only on entities already detected, always on the provider's cheap model
  (`claude-haiku-4-5`, `gpt-4o-mini`, `gemini-flash-lite-latest`, `sonar`), answer truncated to
  6,000 chars, 3-way sentiment + boolean `recommended`, best-effort (never fails a run).
- **Formulas:** `mentionRate = distinct responses mentioning / total`; `shareOfVoice =
  entity mention count / all mention counts in the run`; `avgProminence = mean(1 −
  firstPosition)`; `recommendRate = recommended / responsesMentioned`; `sentimentScore = (pos −
  neg) / judged`; `ownedCitationRate = distinct responses citing an owned domain / total`;
  `informativeRate = responses naming any tracked entity / total`; every rate carries a **Wilson
  score interval** (z=1.96). A five-state `measurementVerdict`: `no-data | no-competitors |
  thin-sample (Wilson upper bound of informativeRate < 0.5) | real-gap | healthy`. A zero-mention
  brand row is synthesized so absence never disappears from the report.
- **Runs:** one (provider, model) per run, hand-rolled pool of 8, `replicates` 1–10 duplicates
  every prompt for independent samples, web search *forced* via `tool_choice` on Anthropic/OpenAI
  (Gemini grounding, Perplexity always grounded), per-provider retry budgets, a job failure never
  aborts the run. Cited sources are stored per response with `is_owned` = host or subdomain match
  against the brand's domains, which is exactly the "cited without being named" signal. Daily
  08:00 UTC cron sweep, `CRON_SECRET`, `pilot-client.ts` runs the pipeline without a DB.
- **Two currencies, named vs cited,** are tracked separately because they are uncorrelated in
  their data (a how-to answer cited runlayer.com while naming nobody). For a young brand the
  citation series is the leading indicator; their onboarding checklist says "expect months, poll
  `firstMentionAt`" and "run once, then set the competitor list from who actually appeared."

All of this drops into our existing `geo-monitor` (`scripts/lib/ai_visibility.py` already has the
provider adapters and multi-sample probing) without adopting their stack.

**What I could not verify.** Whether these three sites produce traffic. They are 6–102 days old;
a `site:llmbillboard.com` query returns nothing in the engine I can reach; the numbers on
phantomstory.com ("8,420 impressions, 41% share of voice") are a design mockup, not data. The
ground truth is in your Letterstory account: the six `phantom_seo` tools and
`get_phantom_geo_signals` return it, and with an API key those are a dozen `curl` calls.

### 8. adtech-world.com as the contrast case

Everything Letterstory's sites do, this site does the opposite of: blocks AI crawlers, monetizes
with AdSense, stock imagery, org byline, keyword-stuffed `meta keywords`, "0 views" counters,
`Quick Summary` box, `What You'll Learn` box, a table per article, H3 sub-structure, free
tools/certifications/newsletter as link bait, and JSON-LD dates of `2026-01-15` on a post
published 2026-09-09. It is a decent example of a *classic* programmatic-SEO content farm on an
aged domain, and a poor example of GEO. If someone told you it was a Letterstory phantom, it isn't.

### 9. What I could not see

The kernel prompts and the "adversarial voting" mechanics (external server), the exact scoring
formula behind `signal_breakdown` and the "KD-sensitive priority queue", the diagram renderer,
the topic-map generator prompt, and which image model minted the covers (the file metadata is
consistent with Gemini but not conclusive). Everything else in Sections 4–7 is either measured or
read from schema text.

### 10. Risk read (please read before Part 2)

- **Google spam policies.** Fresh domains (not expired), 1/day cadence, research-backed unique
  articles and no cross-linking keep this outside the obvious "scaled content abuse" and
  "expired domain abuse" patterns. The exposure is a manual "scaled content / low-value pages"
  action if quality slips, and E-E-A-T scrutiny of personas. adtech-world's aged-domain approach
  carries *more* risk than Letterstory's.
- **Fabricated personas with fabricated tenure** are the weakest link: a Person schema saying
  "has written for LLM Billboard since 2015" on an eleven-day-old domain is a falsifiable claim.
  It buys nothing measurable and is the first thing a journalist or a competitor screenshots.
- **Undisclosed sponsorship.** In the US the FTC Endorsement Guides apply to material connections
  in editorial content; the EU DSA/UCPD is stricter. Pregasen's own data point is that disclosed
  publications are cited "the same" and only *referenced* less. Disclosure at `/about` is cheap
  insurance.
- **Domain ownership.** If your phantom domains were bought through Letterstory, Letterstory is
  the registrant. Ask.
- **This repo's charter.** README and `red-flags.md` currently forbid "content-volume
  automation" and "off-site actions." Reverse-engineering Phantomstory means adding exactly that.
  Part 2 proposes doing it in a separate, explicitly opt-in namespace with disclosure and persona
  policies defaulted to the safe setting, and leaving the existing `seo-*`/`geo-*` skills as they
  are. That is your call, not mine; the plan works either way.

---

## Part 2 — Reverse-engineering plan

### Design stance

1. **Copy the mechanics, not the shortcuts.** Everything in Sections 4–7 is reproducible with
   scripts plus an agent. The two things I recommend *not* copying verbatim are fabricated author
   tenure and zero disclosure (defaults flip to labeled personas with real `started_at` and a
   one-line `/about` disclosure; both remain configurable).
2. **Reuse what this repo already has.** Crawler, sitemap parsing, RFC 9309 robots, JSON-LD
   validator, link graph, GSC client, DataForSEO/Ahrefs clients, Firecrawl, the credential-safe
   HTTP layer, and the LLM probing module all exist under `scripts/lib/`. Phantomstory's
   monitoring layer is largely our `geo-monitor` + `seo-rank-tracking` with better aggregation.
3. **Static site, no framework lock-in.** Their Lettersprite is Next.js on Vercel. Ours should
   be a plain static generator (Astro) driven by a `site.yml` manifest and a folder of markdown,
   so the output HTML matches their fingerprint byte-for-byte in the parts that matter (schema
   graph, feeds, llms.txt, sitemap priorities, meta) and deploys anywhere (Vercel, Cloudflare
   Pages, Netlify). We own the domains.
4. **BYOK everywhere, one pipeline shape.** Research → write → enhance → visuals → publish →
   relink → monitor, each a script with a JSON contract, each callable by an agent through a
   `SKILL.md`, matching the existing ten-heading skill skeleton in this repo.
5. **Keep the new work in its own namespace** (`pub-*` = "publication"), with a `pub-references`
   knowledge skill (this document, split into the anatomy spec and the policy addendum). Existing
   skills stay untouched except where they gain a general capability (relink pass, Wilson
   intervals, awaiting/receiving indexing proxy).

### Capability map: Letterstory → this repo

| Letterstory capability (tools) | What it does | Proposed home | Reuses |
|---|---|---|---|
| Strategy (56) | positioning, competitors → topics → keywords, brand context, ranking targets, landings, onboarding | **new `pub-strategy`**: `positioning.yml`, `scrape_competitors.py`, `infer_keywords.py`, `brand_context.py`, `suggest_targets.py` | `sitemaps`, `crawler`, `dataforseo`/`ahrefs`, `firecrawl`, `http_util` |
| Curate (19) + Seers (21) | topic map (pillars/spokes), suggestions scoring, series, event-driven headlines | **new `pub-curate`**: `build_topic_map.py`, `score_suggestions.py` (competitor / GEO / SEO / cluster / authority / cannibalization signals → headline + why + breakdown), `series.py`, `seers.py` (github_release, news_trend, spec_change only) | `seo-keyword-research` opportunity mining, `gsc_trends` |
| Phantom blogs (18) + Collections (10) | provision site, themes, authors bank, sections, domains, rebuild | **new `pub-site`**: `templates/publication/` (Astro), `site.yml` manifest, `scaffold_site.py`, `gen_authors.py`, `validate_site.py` (fingerprint parity checker), deploy notes | `schema_validate`, `robots`, `sitemaps` |
| Research agent (4) | plan/gather/read/direction/synthesize/verify → sourced outline | **new `pub-research`**: `research_outline.py` (source_urls ≤20, must_include, depth, direction gate, `paper_trail`) | `firecrawl`, `http_util`; add one BYOK web-search adapter |
| Writing kernels (5) + Templates (5) + Shredder (5) | brief → draft in a voice; shape templates; sentence-diversity pass | **new `pub-write`**: `kernels/*.md` (voice cards: Spruce/Juniper/Sequoia/Madrona equivalents), `templates/*.yml` (formatted/open/optional blocks), `write_article.py` (N candidates per section → judge → assemble = "adversarial voting"), `mention.py` (off/subtle/woven + rate + landings). Shredder: optional, off by default | `ai_visibility` provider adapters |
| Flows (6) + Landings (5) | enhance stages, relink, verifier | **new `pub-enhance`**: `enhance.py` stages `add_links → sources → visuals → keywords → verify → voice`, `relink.py` (retro-link older posts on publish, bump `dateModified`) | **extend `seo-internal-linking`** (suggest_link_opportunities already does the hard part) |
| Canvas & visuals (21) + Visual (6) | covers, diagrams, tables, venns | **new `pub-visuals`**: `gen_cover.py` (BYOK Gemini/OpenAI, house style prompt, 16:9, alt convention), `render_diagram.py` (deterministic SVG→PNG: stat callout, stepped flow, funnel, comparison; theme tokens; source line), `render_table.py`/`render_venn.py` | none (new) |
| Content (23) + Connectors (3) + Planner (2) | article record, publish gate, feeds, cadence, exports, webhooks | **new `pub-publish`**: `planner.py` (cadence slots, sourcing mode, approval mode), `publish.py` (frontmatter + assets → site repo → build), `export_article.py` (MDX/JSON for Webflow/Framer/Sanity), `build_feeds.py` (feed.xml, llms.txt, sitemap priorities) | `seo-indexing` (IndexNow, sitemap submit), `seo-metadata`, `seo-structured-data` (add Blog/ProfilePage/AboutPage/citation to `jsonld-library.md`) |
| Insights (20) + phantom_seo (6) + GEO (3) + Story (3) | GSC rollups, awaiting/receiving, pillar rollups, GEO rates with Wilson intervals, ramp phases, refresh triggers | **extend `geo-monitor`** (Lettertrace method: topic → prompt variations → multi-model runs → deterministic mention detection → LLM sentiment/recommended → visibility/SoV/prominence; source attribution; Wilson intervals), **extend `seo-rank-tracking`/`seo-maintain`** (per-site + per-pillar rollups, awaiting/receiving, previous-period deltas, refresh punch list) | `gsc`, `gsc_trends`, `ai_visibility`, `snapshots` |
| Account/Brand (21) | brand voice: colours, logo, writing_style, tone, client_mention | `.seo-engine/config.yml` gains a `brand:` block and a `publications:` list | `config` |

### Phases

**Phase 0 — Reference layer (docs only, ~half a day).**
`skills/pub-references/`: `phantom-anatomy.md` (Section 4–5 as a checklist with exact field
names), `letterstory-capability-map.md` (Section 6), `policy-addendum.md` (Section 10 +
disclosure/persona defaults), and a `red-flags.md` cross-reference. Acceptance: `check_docs.py`
passes; every claim links back to this report.

**Phase 1 — `pub-site` (the publication scaffold).**
Astro template reproducing the observed output: routes, head/meta, JSON-LD graph, RSS, llms.txt,
sitemap priorities, robots, theme tokens on `<html>`, section/author/about/search pages, "In this
article" TOC, Sources block with followed links + `citation[]`, share row, "More in section",
retro-link-safe `dateModified`. Plus `validate_site.py`: crawls a built site with our crawler and
diffs it against the anatomy checklist (fails on missing schema nodes, wrong priorities, images
without dimensions, AI crawlers blocked, cross-links to sibling publications). Improvements over
theirs, all cheap: `width/height` + `srcset` on images, self-hosted images (indexable), optional
`/about` disclosure line, `Person.sameAs` when a persona has a real profile. Acceptance: a demo
publication builds, deploys to Vercel preview, and passes the validator plus our existing
`seo-technical-audit`.

**Phase 2 — `pub-strategy` + `pub-curate` (the brain).**
`positioning.yml` (priority_topics / stances / avoid_topics / ranking_targets ≤5 with
mention_framing / landings with context / competitors with block_from_mentions).
`scrape_competitors.py` (sitemap → titles → inferred keyword + priority via LLM + DataForSEO msv/kd
where keys exist). `build_topic_map.py` (pillars = sections, spokes with angle/brief/keyword/kd/
client_relevance/source, status machine open→queued→covered). `score_suggestions.py` with the six
named signals and an explicit cannibalization check against our own topic map and GSC queries.
Acceptance: given thrad.ai + three competitor domains, produces a reviewable topic map and a
ranked headline queue with per-signal breakdowns; offline tests on fixture sitemaps.

**Phase 3 — `pub-research` → `pub-write` → `pub-enhance` (the article pipeline).**
Research: sourced outline JSON with `paper_trail` (URL, quote, claim), direction options, verify
pass. Write: voice cards + template blocks + candidate-and-judge loop; mention policy enforced
(degree/rate; landing selection by relevance; stat-anchored, nofollow inline, exactly like the
observed thrad link). Enhance: internal links from own sitemap (reuse `suggest_link_opportunities`),
Sources block + citation JSON-LD, numeric-anchor inline citations, verifier that re-checks every
number against its source, voice pass. `relink.py` runs on every publish across the back
catalogue. Acceptance: one end-to-end article from a spoke to a built page, with a JSON audit log
per stage; the verifier fails a planted wrong statistic in tests.

**Phase 4 — `pub-visuals`.**
Deterministic diagram renderer first (it is the visible house style and costs no API calls):
JSON spec → SVG → PNG at 2910×1350 with theme tokens, kicker, source line, alt `Diagram: … .
Visualizes: …` (brief trimmed, not the full prompt). Then BYOK cover generation with one house
prompt per publication and the `Cover illustration for “…”` alt convention. Tables/venns last.
Acceptance: golden-image tests for the renderer; covers optional when no image key is set.

**Phase 5 — `pub-publish` + monitoring.**
`planner.py` (cadence_per_week, launch burst then steady, jittered publish hour, approval modes
manual / review_window / autopilot), `publish.py` (write markdown + assets into the site repo,
build, IndexNow ping via `seo-indexing`, sitemap resubmit), `build_feeds.py`. Monitoring:
`geo-monitor` gains the Lettertrace method end to end (topics → variations → runs → detection →
metrics → trends, plus cited-source capture and Wilson intervals); `seo-rank-tracking` gains
per-publication/per-pillar GSC rollups with `awaiting | receiving` and previous-period deltas;
`seo-maintain` gains a refresh trigger (stale numbers, dropped queries) that queues a rewrite
spoke. Acceptance: a weekly report per publication with SEO + GEO rates and the punch list;
offline tests with fake GSC/LLM transports as the repo already does.

**Phase 6 — optional.** Shredder (sentence diversity across providers), Seers beyond
`news_trend`/`github_release`, CMS connectors (Webflow/Framer/Sanity mappings), social personas
(LinkedIn/X post generation per publication), the "marketing sandbox" A/B harness (format variants
across two phantoms with GSC/GEO readout).

### Decisions I need from you

1. **Charter.** OK to add the `pub-*` namespace to this repo with its own policy addendum, leaving
   the existing skills' "no content-volume automation / no off-site actions" wording scoped to
   `seo-*`/`geo-*`? (Recommended: yes.)
2. **Disclosure default.** One line on `/about` ("An independent publication supported by
   thrad") on by default, off per publication? (Recommended: on.)
3. **Persona policy.** Labeled recurring personas with real `started_at` and no invented cities
   or tenure? (Recommended: yes; it removes the single most falsifiable claim on the sites.)
4. **Providers.** LLM (Anthropic and/or OpenAI), image (Gemini or OpenAI), web search (Tavily,
   Exa, or Firecrawl search, which we already wrap), SEO data (DataForSEO, already wrapped),
   hosting (Vercel or Cloudflare Pages). All BYOK.
5. **Domains.** We register and own them. Confirm who currently owns llmbillboard.com and
   promptsignal.co.

### Immediate next steps

1. If thrad has a Letterstory API key, pull ground truth before building anything: the six
   `phantom_seo` tools and `get_phantom_geo_signals` via
   `POST https://app.letterstory.com/api/integrations/tools/{name}` with header
   `x-integrations-key`. That answers "is it actually creating traffic" in ten minutes.
2. Confirm the five decisions above.
3. I start with Phase 0 and Phase 1 (the reference layer and the site scaffold + validator), since
   everything downstream publishes into it.
