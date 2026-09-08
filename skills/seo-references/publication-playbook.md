# Publication Playbook: third-party editorial sites for SEO + GEO (2026)

> Read by: every `pub-*` skill, and by `geo-monitor` for the mention metrics. This is the
> reference behind the publication engine — the measured anatomy of a working phantom
> publication, the pipeline that produces it, and the rules this repo chose for it.
> Source of the measurements: the September 2026 teardown of Letterstory / Phantomstory and
> three live phantom sites (31 articles), plus Letterstory's public 218-tool API manifest and
> the MIT-licensed Lettertrace code. Full report: `research/letterstory-teardown-2026-09-08.md`.

## 1. What a publication is, and the charter that governs it

A **publication** is an independent-looking editorial site on its own domain (masthead,
sections, recurring bylines, one long article per day) whose topics sit around a client
brand's category and whose articles cite the client where the client is genuinely the source.
The thesis, in the vendor's words: assistants "know a brand will always rank itself #1, so they
trust third-party sources instead." Measured on the vendor's own data, a disclosed relationship
is "cited the same but referenced less"; an undisclosed one is referenced more. This repo's
choices (owner decisions, September 2026):

- Content-volume automation and third-party publications are **in scope** repo-wide. The old
  "no content-volume automation / no off-site actions" wording is retired (README).
- Disclosure is **off by default**, switchable per publication (`site.yml → disclosure`).
- Bylines **mirror the vendor**: generated recurring personas with role, city and a
  `started_at` that predates the site. `--author-tenure real` exists for owners who want the
  falsifiable claim gone.
- The client **registers and owns every domain** and deploys to its own Vercel account —
  Letterstory's `buy_domain` keeps the registrant record on Letterstory's side; ours does not.
- Quality floor is non-negotiable: research-backed, source-cited long reads at one to two per
  day per site, never batch dumps ([red-flags.md](red-flags.md) §7 spells out the line).

## 2. Site anatomy (measured, reproduce exactly)

Routes: `/`, `/posts/<slug>`, `/sections/<slug>`, `/authors/<slug>`, `/about`, `/search`
(noindex), `/feed.xml`, `/llms.txt`, `/sitemap.xml`, `/robots.txt`, `/icons/<icon>.svg`.

Every page: `<html lang data-theme style="--bg…--container-width;color-scheme">` (the whole
theme as CSS custom properties on the root), `meta robots: index, follow`, `meta googlebot:
index, follow, max-video-preview:-1, max-image-preview:large, max-snippet:-1`,
`application-name`, canonical, RSS alternate, full OG + `twitter:card summary_large_image`,
Google Fonts preconnect. JSON-LD `@graph` of `Organization` (`#organization`, logo = icon SVG)
and `WebSite` (`#website`, `publisher → #organization`, `inLanguage`).

Page-specific JSON-LD: home `Blog{blogPost[BlogPosting stubs]}`; article `BlogPosting` (see §3)
+ `BreadcrumbList` (Home → Section → Title); author `ProfilePage{mainEntity: Person{@id,
jobTitle, description, worksFor}, hasPart[]}`; about `AboutPage{mainEntity → #organization}`.
Our builder adds `CollectionPage` on sections and `wordCount` on articles.

Feeds: RSS 2.0 with `dc:creator`, `category` = section, `atom:link rel=self`. `llms.txt` is
`# Name`, `> tagline`, `## Posts`, one `- [title](url): dek` per post. Sitemap priorities:
home 1.0/daily, sections 0.5/weekly, authors 0.4/weekly, posts 0.7/monthly, ISO `lastmod`.
`robots.txt` allows everything (no AI crawler blocked), plus `Host:` and `Sitemap:`.

Themes: three measured token sets (`signal`, `forum`, `classic`) plus house themes, all in
`scripts/lib/publication.py → THEMES`. The vendor exposes 54 theme names; add yours to the
table rather than inventing ad hoc CSS.

Client side: no analytics or tracking scripts at all. Measurement is server-side (Search
Console via a `google-site-verification` TXT record per domain) and probe-side (§7).

Network hygiene: publications never link to each other, never link to the vendor or the
engine, and each targets a different buyer persona of the client's category.

Two deliberate improvements over the measured sites: images carry `width`/`height` (theirs
don't, a CLS risk) and are self-hosted under `/assets/` (theirs sit on Supabase storage that
answers `x-robots-tag: none`, so none of their imagery can rank in image search).

## 3. Article anatomy (measured on 31 posts)

- **Length** 2,200–2,650 displayed words ("Long read" kicker), read time ≈ words / 220.
- **Structure** H1 → dek → byline (persona, role, date, read time, "Updated …" when
  `dateModified` differs) → share row → cover → "In this article" TOC → 6–8 H2 sections (mean
  11.7 words, declarative, colon in about 1 in 10, rarely questions; the last one often "What
  should X do…?") → Sources → "Filed under" → author box → next story → "More in <Section>".
  No H3s in the body. About 40 paragraphs of ~65 words, 2–4 bulleted lists, no tables.
- **Opening** on a cited statistic; second paragraph states the thesis and names a framework;
  the close returns to the opening number and issues sequenced "if X is the gap, do Y" advice.
- **Citations** 2–34 external links per post (median 12), **57% anchored on the number
  itself** ("$2.08 billion", "18%"), inline links `rel="noopener noreferrer nofollow"
  target=_blank`. A numbered **Sources** list closes the piece with **followed** links, mirrored
  into `BlogPosting.citation[]`.
- **Internal links** 0–5 descriptive partial-match anchors per post. **Older posts are
  retro-linked when new ones publish** and their `dateModified` bumps (13 of 44 body links
  pointed at later posts). We call the pass `relink`.
- **Diagrams** 1–2 per post, PNG 2910×1350, house style (small-caps kicker title, one big
  number or a stepped flow, `Source: …` footer). Alt text = `Diagram: <title>. Visualizes:
  <brief>`. Cover: generated 16:9 illustration per headline, alt `Cover illustration for
  “<title>”`, served at 1600 px for the hero.
- **Brand mention** 1 of 31 posts linked the client, as a statistic anchor ("$25 to $60" CPM)
  pointing at a client guide, nofollow, no pitch. See §6.
- **Voice** third person, no "we", blunt imperatives, hedges cut, dense with named sources.

## 4. The pipeline (Curate → Research → Write → Enhance → Visuals → Publish → Relink → Monitor)

The vendor's per-article sequence ("Auto-Pen"): `outline{depth barebones|fleshed_out,
direction_gate}` → positioning → `kernel{family}` → `mention{degree off|subtle|woven, rate}`
→ verifier → `enhance{flow}` → shred (optional) → relink. Research runs
`plan → gather → read → direction → synthesize → verify` with up to 20 seed URLs and 40
must-cover subsections; writing kernels take a brief and return a draft; the Enhance flow
runs `add_links` (internal, crawled from the site's own sitemap) → external sources → visuals.
Research plus writing takes 20–40 minutes per article on their stack.

Ours, skill by skill:

| Stage | Skill / script | Contract |
|---|---|---|
| Strategy | `pub-strategy/positioning.py` | `strategy.yml`: priority_topics, stances, avoid_topics, ranking_targets (≤5, each with mention_framing), landings (url + when-to-cite context), competitors (with block_from_mentions), brand voice |
| Curate | `pub-curate/build_topic_map.py`, `score_suggestions.py`, `seers.py` | `topic-map.yml` pillars (= sections) → spokes {subtopic, angle, brief, status open→queued→covered, client_relevance, source ai/user/geo/social, seo_keyword/msv/kd}; headline queue scored on competitor, GEO, SEO, cluster-alignment, authority, cannibalization, social |
| Research | `pub-research/research_outline.py` | outline + `paper_trail` (url, quote, claim) + direction options; verify pass |
| Write | `pub-write/write_article.py` | voice card + template blocks + candidate-and-judge → markdown with frontmatter; mention policy applied |
| Enhance | `pub-enhance/enhance_article.py`, `relink.py` | internal links, Sources + citation JSON-LD, numeric anchors, number verifier, voice pass; back-catalogue relink on publish |
| Visuals | `pub-visuals/render_diagram.py`, `gen_cover.py` | deterministic SVG/PNG diagrams; BYOK cover with fallback |
| Publish | `pub-publish/planner.py`, `publish_article.py`, `run_pipeline.py` | cadence slots, approval modes, publish + build + IndexNow |
| Monitor | `pub-monitor/report_performance.py`, `geo-monitor/track_brand_mentions.py` | §7 metrics |

## 5. Personas and sections

The vendor's author bank: 8–14 recurring authors per site, combinatorial name bank, roles from
{Staff Writer, Senior Writer, Features Editor, Editor at Large, Columnist, Reporter,
Correspondent, Contributing Editor}, a city, and the bio template *"<Name> is a <role> at
<Site> covering <section>. Based in <City>, <First> has written for <Site> since <Year>."*
Posts are distributed across the bank by topic affinity ("assign … mode=auto"). Sections are
the topic-map pillars' display names (2–4 per site). The masthead must not contain the client
name (rejected server-side in their API; `scaffold_publication.py` enforces the same).

## 6. Mention policy

`mention.degree`: `off` (never name the client), `subtle` (a statistic or fact attributed to a
client page, anchored on the number, nofollow, at most once per article, only when the topic
is genuinely about what the client builds), `woven` (a natural sentence naming the client plus
a link to the most relevant landing page). `rate` caps how many articles in a collection carry
any mention at all — the measured live rate was 1 in 31. Landings are URL + free-text "when
it is worth citing"; the writer picks a landing only when its context matches the section
being written, and `last_mentioned_at` spreads mentions across landings. Competitors flagged
`block_from_mentions` are never named. Ranking targets (≤5 phrases like "best payroll
software") each carry `mention_framing` guidance the writer follows when the target's phrase
is in play.

## 7. Monitoring metrics (what "is it working" means)

SEO layer (Search Console, per publication): rolling 14/30/90-day windows with the previous
equal window for deltas; `clicks, impressions, ctr, impression-weighted position` per site,
post, query and pillar; a per-post indexing proxy `awaiting | receiving` keyed on the first
day GSC served an impression; "deterministic insights" — claims with the numbers spelled out.

GEO layer (Lettertrace method, open source): topics → 8 prompt variations per topic, two thirds
of which must **explicitly demand named companies** ("List the top 5 … by name"; never "give
me a shortlist", never how-to), labeled `general | mid | niche`; each prompt run against each
configured assistant with web search forced, `replicates` 1–10 for independent samples;
deterministic mention detection (brand + aliases, never the domain label, link targets
blanked, labels kept); cheap-model enrichment for `sentiment` (3-way) and `recommended`;
metrics `mentionRate`, `shareOfVoice` (mention counts / all mention counts), `avgProminence =
mean(1 − first_position)`, `recommendRate`, `sentimentScore = (pos − neg) / judged`,
`ownedCitationRate` (answers citing an owned domain / answers), `informativeRate` (answers
naming any tracked entity / answers). **Every rate carries a Wilson interval**; a five-state
verdict `no-data | no-competitors | thin-sample | real-gap | healthy` keeps a 0% from being
misread. Named and cited are separate currencies; for a young publication the citation series
is the leading indicator. Expect months. The vendor's own pilot: prompt *shape* decides whether
answers name anyone (3.7 companies per answer for "list the top 5", ~0.1 for "how do I").

## 8. Letterstory capability map (for anyone extending this engine)

218 tools in 14 capabilities, all reachable over REST (`POST /api/integrations/tools/{name}`,
header `x-integrations-key`), MCP (`/api/mcp`, manifest public) and a CLI: Content 23,
Collections 10, Canvas & visuals 21, Flows 6, Seers 21 (github_pr, github_release,
notion_activity, spec_change, news_trend, regulation_change; modes suggest|auto; a holding pen
for ungrounded drafts), Research agent 4, Writing kernels 5 (nine voices; "adversarial
voting"), Connectors 3 (Webflow, Framer, Google Docs, Contentful), Phantom blogs 18
(provision, 54 themes, buy/connect domain capped at 2 per org and $30, configure
strategy→visuals→enhance→kernel→planner→map, seed posts), Strategy 56, Insights 20 (GSC),
Shredder 5 (sentence-level multi-provider rewrite, structure preserved, per-provider share
ceilings), Landings 5, Account 21. Planner: `cadence_per_week` (phantom default 6, client 3),
`sourcing_mode topic_map|curate_first|curate_only`, `approval_mode
autopilot|review_window|manual`, `steering_prompt`. Pricing: Letterstory $0/$100/$300/$1,000
per month by credits; Phantomstory $500–$1,000 per month for one to three sites.

## Sources

- Teardown report and captured HTML: `research/letterstory-teardown-2026-09-08.md`
- Lettertrace source read (prompts and formulas verbatim): `research/lettertrace-source-report-2026-09-08.md`
- Letterstory MCP manifest: https://app.letterstory.com/api/mcp (218 tool schemas)
- Phantomstory: https://phantomstory.com/ and the Product Hunt launch thread
- Lettertrace: https://github.com/letterstory/lettertrace (MIT)
