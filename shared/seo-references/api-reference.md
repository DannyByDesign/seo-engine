# API Reference (2026)

> Read by: every skill that calls `scripts/lib/*.py`. This is the ground truth for auth models,
> endpoints, and quotas the client library code implements. Where a detail could not be verified
> against a live/primary source in this research pass, it is marked **UNCERTAIN** — treat those
> specifically as "verify before depending on it in production," not as settled fact.
>
> All of these integrations are optional. `seo-engine` works with zero paid keys using the
> built-in crawler (`scripts/lib/crawler.py`) plus Google's free APIs (Search Console, PageSpeed
> Insights, CrUX). Everything below is worth-it, cost-scaled extension, not a requirement.

## Google Search Console API

**Auth:** OAuth 2.0 only — no API-key auth exists for this API. The correct pattern for **unattended
automation** (no human present to click through a consent screen):
1. Create a Google Cloud service account, download its JSON key.
2. In Search Console, on the already-verified property, go to **Settings → Users and permissions
   → Add user**, and add the service account's `client_email`
   (`name@project.iam.gserviceaccount.com`) as a verified Owner or full User.
3. Authenticate server-side via `google.oauth2.service_account.Credentials` — no interactive
   consent required from that point on.

The property itself must already be domain-verified through a standard method (DNS TXT, HTML file,
etc.) before this works — the service account rides on an already-verified property, it doesn't
perform verification itself.

**Client library:** `google-api-python-client`. Build the service as:
```python
from googleapiclient.discovery import build
service = build("searchconsole", "v1", credentials=creds)
```
Use the **`searchconsole` v1** service name — the legacy `webmasters` v3 service name is
deprecated (cutover completed ~Nov 2021). Note the underlying REST paths still use a
`webmasters/v3/...` prefix under the `searchconsole` v1 service — this is a naming quirk in
Google's own discovery document, not an error in client code that uses it.

**Key methods:**
| Method | HTTP | Purpose |
|---|---|---|
| `searchanalytics.query` | `POST webmasters/v3/sites/{siteUrl}/searchAnalytics/query` | Clicks/impressions/CTR/position by query, page, date, device, country |
| `sitemaps.submit` | `PUT webmasters/v3/sites/{siteUrl}/sitemaps/{feedpath}` | Submit a sitemap |
| `sitemaps.list` / `.get` / `.delete` | `GET`/`DELETE .../sitemaps[/{feedpath}]` | Manage sitemaps |
| `urlInspection.index.inspect` | `POST v1/urlInspection/index:inspect` | Index status, selected canonical, mobile usability, **rich results verdict** (`richResultsResult`), AMP status |

**Scopes:** `https://www.googleapis.com/auth/webmasters` (full) or
`https://www.googleapis.com/auth/webmasters.readonly` (read-only).

**Rate limits (per Google's discovery doc / limits page):** Search Analytics — 1,200 QPM per
site/user, 40,000 QPM & 30,000,000 QPD per project. URL Inspection — 600 QPM / 2,000 QPD per site,
15,000 QPM / 10,000,000 QPD per project.

**Property identifiers are not site URLs.** `siteUrl` must be either
`sc-domain:example.com` (domain property — the most common modern setup) or a URL-prefix
property **including its trailing slash** (`https://example.com/`); the slash-stripped form
403s. `scripts/lib/gsc.resolve_property()` discovers the right identifier from `sites.list()`
and caches it in `.seo-engine/config.yml` (`gsc_property`).

**Dates are America/Los_Angeles days.** Search-analytics rows are bucketed in Pacific-time
days regardless of the caller's timezone — window math must use `gsc.gsc_today()`, never the
machine-local date, or window boundaries shift by up to a day. Data also lags ~2-3 days.

**Env vars:** `GOOGLE_APPLICATION_CREDENTIALS` (path to service-account JSON) or
`GSC_SERVICE_ACCOUNT_JSON` (inline JSON, for environments that can't mount a file).

## PageSpeed Insights API v5

**Auth:** API key as a query parameter — optional for light use, strongly recommended for
automation (unlocks higher quota and avoids shared-IP throttling).

**Endpoint:** `GET https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url={URL}&key={KEY}`
Additional params: `strategy=mobile|desktop`, `category=performance|accessibility|best-practices|seo`.

**Quota:** commonly cited at ~25,000 requests/day and ~400 queries/100 seconds with a key — this
figure is **UNCERTAIN**, it is widely repeated but was not confirmed against an official Google
Cloud quota page in this research pass. Build in backoff/retry (already handled generically by
`scripts/lib/http_util.py`) rather than hardcoding a specific ceiling.

**Note on field data:** `loadingExperience` / `originLoadingExperience` (real-user CrUX data) are
still present in the current PSI v5 response per official reference docs. A claim that Google
plans to remove field data from PSI in favor of the dedicated CrUX API **could not be confirmed**
and is likely a misattributed/outdated fragment — do not build logic that assumes PSI will stop
returning field data. Use PSI for both lab (Lighthouse) and field data today; use the CrUX API
separately when you need historical trends or origin-level (not just single-URL) aggregation.

**Env var:** `GOOGLE_PSI_API_KEY`

## Chrome UX Report (CrUX) API

**Auth:** API key via `?key=` query parameter (obtain at `https://goo.gle/crux-api-key` — same
Google Cloud project/key as PSI works fine).

**Record API:** `POST https://chromeuxreport.googleapis.com/v1/records:queryRecord`
Body: `{"origin": "https://example.com"}` or `{"url": "https://example.com/page"}`, optionally
`"formFactor": "PHONE"|"DESKTOP"|"TABLET"`, `"metrics": [...]`.

**History API:** `POST https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord` — same
auth/body shape, adds `collectionPeriodCount`; data refreshes weekly in rolling 28-day windows.

**Quota:** 150 queries/minute per Google Cloud project for both endpoints, free.

**Env var:** reuses `GOOGLE_PSI_API_KEY` (same key works for both PSI and CrUX).

## Structured data validation

- **No public Rich Results Test API exists.** Google's Rich Results Test is UI-only
  (`search.google.com/test/rich-results`); the old Structured Data Testing Tool API was
  deprecated with no replacement. The only programmatic path to Google's actual rich-results
  verdict is `urlInspection.index.inspect`'s `richResultsResult` field — and that only works for
  URLs that are **already indexed on an already-verified GSC property**, so it can't validate
  staging/pre-publish content.
- **validator.schema.org** is a web form only; no documented API.
- **Offline/CI validation pipeline (Python, no external API calls):**
  1. `extruct` — extracts JSON-LD, Microdata, RDFa, OpenGraph, and Microformats from raw HTML.
     Extraction only, not validation.
  2. `pyld` / `rdflib` — normalizes extracted JSON-LD into an RDF graph per the W3C JSON-LD spec.
  3. `pyshacl` — validates the RDF graph against SHACL shape constraints. Schema.org does not ship
     official SHACL shapes, so this requires either community shape sets or hand-authored shapes
     for the specific types this system cares about (Article, Organization, FAQPage, Product,
     BreadcrumbList, etc.) — `seo-structured-data` ships a minimal shape set for the common types
     and validates required-property presence + type-correctness locally before anything is
     pushed live.

## Ahrefs API v3

**Auth:** Bearer token — `Authorization: Bearer {API_KEY}` plus `Accept: application/json`. Keys
are created in Account Settings → API Keys (owner/admin role required), each expires after 1 year,
up to 1,000 keys per account.

**Base URL:** `https://api.ahrefs.com/v3/` — REST, per-resource paths (not GraphQL). Each endpoint
takes a `select` query parameter (comma-separated field list) to control which columns are
returned — this is how field-selection works instead of a GraphQL query body.

**Key endpoints:**
| Path | Purpose |
|---|---|
| `GET /site-explorer/domain-rating` | Domain Rating (params: `target`, `date`) |
| `GET /site-explorer/domain-rating-history` | DR over time |
| `GET /site-explorer/all-backlinks` | Full backlink list |
| `GET /site-explorer/broken-backlinks` | Backlinks pointing to now-broken pages |
| `GET /site-explorer/pages-by-backlinks` | Top pages by backlink count |
| `GET /site-explorer/organic-keywords` | Keywords a domain ranks for |
| `GET /site-explorer/organic-competitors` | Organic competitor overlap |
| `GET /keywords-explorer/overview` | Keyword volume/difficulty overview |
| `GET /keywords-explorer/volume-history` | Search volume trend |
| `/web-analytics/*` | Separate product area (34 endpoints) — Ahrefs' own site-analytics data (traffic, pages, geography, user agents), distinct from Site Explorer |

Site Audit exists as a distinct product area in the docs navigation, but exact v3 endpoint paths
for it could not be independently verified in this research pass — **UNCERTAIN**, confirm against
`docs.ahrefs.com` directly before building a Site Audit integration.

**Plan gating:** available from the **Lite** plan and up (no longer Enterprise-only, a change from
historical gating). Monthly API-unit allowances: Lite 100,000 / Standard 400,000 / Advanced
1,000,000 / Enterprise 2,000,000 units.

**Rate limits / cost model:** default **60 requests/minute** (HTTP 429 on excess); minimum charge
**50 units per request**; actual cost scales with rows returned × fields selected. Max rows per
single request scales by plan (Lite 100, Standard 250, Advanced 500, Enterprise unlimited). Some
endpoints (Rank Tracker reads, account management, public data) are free (0 units).

**Env var:** `AHREFS_API_KEY`

## DataForSEO

**Auth:** HTTP Basic Auth — `Authorization: Basic base64(login:password)`. These are dedicated API
credentials generated in the DataForSEO dashboard, **distinct from your account login password** —
never send them as URL query parameters.

**Base URL:** `https://api.dataforseo.com/v3/`, organized by namespace: `serp/`, `keywords_data/`,
`dataforseo_labs/`, `on_page/`, `backlinks/`, `content_analysis/`, `business_data/`, `merchant/`,
`app_data/`, `ai_optimization/`. Response format suffix (`.json` default) selectable per call.
Rate-limit state is exposed via `X-RateLimit-Limit` / `X-RateLimit-Remaining` response headers —
read these rather than hardcoding a client-side limit.

**Live (synchronous) vs. task-based (queued) — confirmed per-namespace, do not assume uniformity:**

| Namespace | Mode | Key endpoints |
|---|---|---|
| SERP | Both | Live: `POST /serp/google/organic/live/advanced` (up to 2,000 calls/min supported); Task-based: `POST /serp/google/organic/task_post` → `GET /serp/google/organic/task_get/{id}` |
| Keywords Data | Both | Live: `POST /keywords_data/google_ads/search_volume/live` (max 1,000 keywords/request, 12 req/min on this specific endpoint); task variant also available |
| Backlinks | **Live-only** | `POST /backlinks/summary/live`, `/backlinks/backlinks/live`, `/backlinks/domain_pages_summary/live`, `/backlinks/domain_intersection/live`, `/backlinks/page_intersection/live` |
| On-Page | **Task-based only** | `POST /on_page/task_post` (params: `target`, `max_crawl_pages`, optional `pingback_url` webhook) → `GET /on_page/summary/{id}`, `/on_page/pages/`, `/on_page/resources/`, `/on_page/links/` |
| Domain/competitor analytics | Live | Lives under `dataforseo_labs`, not `domain_analytics`: `POST /dataforseo_labs/google/domain_intersection/live`, `/dataforseo_labs/google/competitors_domain/live` (Google and Bing variants both exist) |

**Pricing:** pure pay-as-you-go, **no subscription tier gate at all** — $50 minimum account
deposit, $1 free credit on signup. Confirmed sample rates: SERP Standard queue $0.0006/query,
Priority $0.0012/query, Live $0.002/query; Backlinks API $0.02/request + $0.00003/row (max
1,000 rows/request). Keywords Data per-call pricing was not independently confirmed with hard
numbers — **UNCERTAIN**, check `dataforseo.com/pricing-list` directly before budgeting.

**Env vars:** `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD`

## Semrush API

**Auth:** two mechanisms coexist, chosen by endpoint family:
- Core SEO/Analytics API (domain/keyword/backlink reports): API key as a **query parameter**
  (`?key={API_KEY}`).
- Newer Projects API (which now includes **Site Audit** and Position Tracking) and Listing
  Management API: **header** `Authorization: Apikey {API_KEY}`.
- Map Rank Tracker API and some legacy endpoints: OAuth 2.0 Bearer token.

**Base URL / structure:** `https://api.semrush.com/?key={KEY}&type={report}&export_columns=...&domain=...&database=us`
— a single endpoint with the report selected via `type=`. Returns CSV. Confirmed unit cost example:
Domain Organic Search Keywords report = 10 units/line (live data) / 50 units/line (historical).
Other per-report unit costs vary — check `developer.semrush.com/api/basics/units` live before
budgeting a specific report type.

**Plan gating:** requires a **Business plan** (SEO Toolkit tier) as prerequisite for API access at
all; API-unit balance starts at **zero** even after upgrading and must be purchased as a separate
add-on. Reported figures like "~$50 per 10,000 units" are **UNCERTAIN** — sourced from third-party
blogs, not confirmed against an official current Semrush pricing page.

**Site Audit via API:** contrary to older assumptions that Site Audit was UI-only, current docs
show a dedicated Site Audit section under the Projects API
(`developer.semrush.com/api/projects/site-audit/`) — confirmed as existing, but the full endpoint
list/parameters were not independently verified; treat as a real but under-documented capability
in this client library.

**Env var:** `SEMRUSH_API_KEY`

## Bing Webmaster Tools API

**Auth:** API key as query parameter `?apikey={KEY}` (OAuth 2.0 Bearer token is also offered as an
alternative, described by Microsoft as "recommended," but the simple API-key path remains
functional).

**Base pattern:** `https://ssl.bing.com/webmaster/api.svc/json/{Method}?apikey={KEY}&{params}`

**Methods:** `SubmitSitemap`, `SubmitUrl` / `SubmitUrlbatch`, `GetCrawlStats`, `GetQueryStats`
(query/keyword performance — not a keyword-volume research tool).

**Status:** documentation pages carry metadata dates of 2019/2022 — this API is **de facto frozen**,
not actively evolving. Microsoft has steered submission use cases toward IndexNow for years; treat
this API as useful only for crawl-stats/query-stats **reads**, and use IndexNow (below) for URL
submission.

**Env var:** `BING_WEBMASTER_API_KEY`

## IndexNow

**Protocol (not vendor-specific — one key works across all participating engines):**
- Single URL: `GET https://{searchengine}/indexnow?url={url}&key={key}`
- Batch: `POST /indexnow` with JSON body `{"host": "...", "key": "...", "keyLocation": "...", "urlList": [...]}` (up to 10,000 URLs per call).
- The key is an 8-128 character hex string, hosted as a plain-text verification file at
  `https://{host}/{key}.txt` (or a custom location declared via `keyLocation`).

**What it actually guarantees (per IndexNow's own FAQ):** submitting a URL **does not guarantee
immediate indexing** — it only signals that a URL changed and increases the likelihood of a
prioritized (not immediate) crawl visit. The engine still applies its own quality/crawl-quota
gating. **Submitted URLs count toward the site's normal crawl quota** — indiscriminate submission
can waste crawl budget rather than save it. Use IndexNow for genuinely new/changed/deleted URLs,
not as a blanket "resubmit everything" mechanism.

**Participants:** Bing, Yandex, Naver, Seznam.cz, Yep, Amazon (Cloudflare offers infrastructure-level
support for participating sites); Bing's own materials additionally list Yahoo. **Google and Baidu
do not participate** — this is well-corroborated by secondary sources, though a fresh 2025/2026
primary Google restatement was not found in this research pass; treat Google's non-participation as
highly likely but not freshly reconfirmed. **For Google, use Search Console (sitemaps +
`urlInspection`) instead of IndexNow.**

**Env var:** `INDEXNOW_API_KEY`

## Firecrawl

**Auth:** API key as a Bearer token (`Authorization: Bearer {KEY}`); limited use is available
without a key.

**Endpoints:**
| Endpoint | Purpose |
|---|---|
| Scrape | Single URL → clean markdown, HTML, structured JSON extraction, or screenshot |
| Crawl | Recursive site crawl following links |
| Map | Near-instant full URL discovery for a domain (no content fetch) |
| Search | Web search returning Firecrawl-formatted results |
| Interact | Scripted browser interaction (clicks, forms) for JS-heavy flows |

**Pricing:** credit-based — 1 credit/page for Scrape, Crawl, Map, and Monitor; 2 credits per 10
results for Search; 2 credits per browser-minute for Interact. Free tier: 1,000 credits/month.
Failed fetches are not charged.

**Why this system uses it:** raw `requests.get()` HTML frequently misses content that only
appears after client-side JavaScript execution (React/Vue/Next.js hydration) — exactly the class
of bug `seo-technical-audit` needs to catch (see [red-flags.md](red-flags.md) §4, JS-rendering
traps). Firecrawl (or an equivalent rendering-capable scraper) lets an audit diff "what a naive
HTTP GET sees" against "what a real rendered browser sees" for a sample of pages, surfacing
JS-dependent content that may be invisible to some crawlers.

**Env var:** `FIRECRAWL_API_KEY`

The `pub-*` skills also use Firecrawl's **search** endpoint (`POST /v2/search`, `query`, `limit`,
optional `tbs` recency filter) as the web-search step of `pub-research` and for `news_trend`
seers, and its scrape endpoint to read sources and competitor catalogues. Without the key,
research falls back to the URLs it is given (`--source-url`, landings, cached research).

## AI-visibility tracking (commercial landscape)

This category is overwhelmingly **dashboard-first** in 2026 — most vendors gate API access behind
Enterprise/custom pricing or don't expose one at all. `scripts/lib/ai_visibility.py` is built
primarily around **direct calls to the AI vendors' own official APIs** (OpenAI, Anthropic,
Perplexity, Gemini — see [geo-playbook.md](geo-playbook.md) §9 for the DIY citation-probing
approach, which is the sustainable, always-available core of this skill), with the two commercial
trackers below wired in as **optional** supplementary sources since they're the only two with
real, somewhat-accessible APIs:

| Tool | API access | Notes |
|---|---|---|
| **Profound** (tryprofound.com) | Public API (beta), official Python/JS SDKs, API-key auth, 600 req/hr | `visibility` endpoint returns a `visibility_score` by category/date/dimension. Pricing: Starter $99/mo (ChatGPT only, 50 prompts), Growth $399/mo (+Perplexity/AI Overviews, 100 prompts), Enterprise custom. |
| **Otterly.AI** (otterly.ai) | Public REST API + official MCP server (OAuth 2.0) | Tracks ChatGPT, Perplexity, AI Overviews, Copilot (Gemini/AI Mode as paid add-ons). Pricing: Lite $29/mo (no API), Standard $189/mo (2,000 req/mo API), Premium $489/mo (5,000 req/mo API). |
| Peec AI | Enterprise-only, explicitly "in beta" | Not self-serve confirmed. |
| Scrunch AI, AthenaHQ, Brandlight, Goodie AI | API reserved for higher/Enterprise tiers, or no API at all | Dashboard-only for typical self-serve plans. |
| Ahrefs Brand Radar, Semrush AI Visibility Toolkit | No public API found | Dashboard add-ons to existing Ahrefs/Semrush subscriptions. |

**Env vars:** `PROFOUND_API_KEY` (optional), `OTTERLY_API_KEY` (optional) — both integrations
degrade gracefully to "not configured" if absent, since the DIY-via-vendor-APIs approach is the
primary mechanism.

## LLM provider APIs — GEO citation-probing

| Provider | Feature | Auth | Notes |
|---|---|---|---|
| OpenAI | Responses API `web_search` tool | `OPENAI_API_KEY` | Citations in `annotations` (`type: "url_citation"`) |
| Anthropic | Claude API `web_search` tool (`web_search_20250305`) | `ANTHROPIC_API_KEY` | Citations inline per text block; supports `allowed_domains`/`blocked_domains` |
| Perplexity | Sonar API | `PERPLEXITY_API_KEY` | `citations` + `search_results` in every response |
| Google | Gemini API grounding | `GOOGLE_GEMINI_API_KEY` | `groundingMetadata` — this is the Gemini API's own grounding, not the same system as AI Mode/AI Overviews in Search, which have no public API |

`geo-monitor`'s brand-mention tracker (`track_brand_mentions.py`) uses the same four with web
search forced on, then detects mentions deterministically (name + aliases, links blanked, never
the domain label) and scores sentiment/recommendation with the cheap tier below.

## LLM provider APIs — content generation (the `pub-*` skills)

Bring-your-own-key text generation in `scripts/lib/llm.py`. Select a configured provider with
`LLM_PROVIDER` or the command's provider option. A single configured provider works without
a selector; multiple configured providers require an explicit choice, with no vendor priority.
Every call goes through `http_util` with the JSON body and a single retry on malformed JSON.

| Provider | Endpoint | Quality model (default) | Cheap model (default) | Override |
|---|---|---|---|---|
| Anthropic | `POST https://api.anthropic.com/v1/messages` (`anthropic-version: 2023-06-01`; `output_config.effort` when `LLM_EFFORT` is set, never on Haiku) | `claude-opus-5` | `claude-haiku-4-5` | `LLM_MODEL_ANTHROPIC`, `LLM_CHEAP_MODEL_ANTHROPIC` |
| OpenAI | `POST https://api.openai.com/v1/responses` (`instructions` + `input`; `text.format json_object` for JSON) | `gpt-5` | `gpt-5-mini` | `LLM_MODEL_OPENAI`, `LLM_CHEAP_MODEL_OPENAI` |
| Google | `POST https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent` (`systemInstruction`; `responseMimeType application/json`) | `gemini-2.5-pro` | `gemini-2.5-flash` | `LLM_MODEL_GEMINI`, `LLM_CHEAP_MODEL_GEMINI` |

Who uses which tier: research synthesis, article candidates, the judge and the voice pass use
the quality tier; topic-map expansion, keyword suggestions, mention sentiment and seer summaries
use the cheap tier. The Shredder rotates providers on purpose (one voice per sentence run is
the point). A `refusal` stop reason or an empty body is surfaced as `LlmError`, never retried
blindly. Perplexity is probing-only (no content generation).

## Image generation APIs (`pub-visuals gen_cover.py`)

| Provider | Endpoint | Default model | Override | Output |
|---|---|---|---|---|
| OpenAI | `POST https://api.openai.com/v1/images/generations` | `gpt-image-1` | `IMAGE_MODEL_OPENAI` | base64 JPEG, `size` 1536×1024 |
| Google | `POST …/models/<model>:generateContent` with image response modality | `gemini-2.5-flash-image` | `IMAGE_MODEL_GEMINI` | `inlineData` (base64) |

`IMAGE_PROVIDER` (`openai` | `gemini`) picks when both keys exist; with neither key the skill
renders a deterministic SVG cover so the pipeline never blocks on art. Diagrams are pure SVG
(no API) rendered from the research outline's `diagrams` specs.

## SociaVault (social-conversation search)

Consumer-social scraping API used by `pub-curate` for the **social** signal (what younger
audiences are actually asking on Reddit, X, TikTok, YouTube, Instagram) and the `social_trend`
seer. Docs: docs.sociavault.com.

- **Base URL:** `https://api.sociavault.com/v1`; **auth:** `X-API-Key` header; **billing:**
  credit packs, 1 credit per request (`GET /credits` returns the balance). A failed scrape
  returns `success: false` with a message and still costs a credit.
- **Endpoints used:** `GET /scrape/reddit/search` (`query`, `sort`, `timeframe`, `trim`),
  `GET /scrape/twitter/search` (`query`, `type` Top|Latest), `GET /scrape/tiktok/search/keyword`
  (`query`, `date_posted`, `sort_by`, `region`), `GET /scrape/youtube/search` (`query`,
  `uploadDate`, `sortBy`), `GET /scrape/tiktok/trending` (`region`). Instagram hashtag search and
  transcripts exist but are not wired in.
- **Quirks:** collections often come back as index-keyed objects (`{"0": {…}, "1": {…}}`)
  rather than arrays — `scripts/lib/sociavault.py` normalizes both; per-platform failures are
  reported in `errors[]` without failing the whole search.
- **Scope rule:** read-only listening for topic discovery. Nothing in this system posts,
  replies, or creates social accounts (red-flags §7).

**Env var:** `SOCIAVAULT_API_KEY`

## GitHub REST API (seers)

`github_release` and `github_pr` seers read `GET https://api.github.com/repos/{owner}/{repo}/releases`
and `/pulls` (public repos only). Unauthenticated calls share a 60 requests/hour IP quota;
`GITHUB_TOKEN` (a fine-grained token with public-repo read scope, or none) lifts it to 5,000/hour
and is sent as `Authorization: Bearer`. Nothing is written.

**Env var:** `GITHUB_TOKEN` (optional)

## Notion API (seers)

`notion_activity` polls `POST https://api.notion.com/v1/search` (`Notion-Version: 2022-06-28`,
filtered to pages, sorted by `last_edited_time`) for pages a Notion **internal integration** has
been shared with — the client's own roadmap or research workspace, used as a "something changed,
consider an article" trigger. Create the integration in Notion's developer settings and share
only the pages that should be visible. Nothing is written.

**Env var:** `NOTION_TOKEN`

## Env var summary

See [.env.example](../../.env.example) for the complete, documented list with placeholder values.
