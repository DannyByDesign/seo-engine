# Terminal research APIs

Vetted against official HTTP documentation on 2026-09-09. These are actual API clients and
terminal entry points, not instructions to inspect a vendor dashboard. Authentication/account
entitlement must be tested in the target environment; documentation verification and offline
transport tests are not a claim that this account made a live paid call.

## Select data by the question

| Question | Provider and terminal route | Authentication and limits | Interpretation |
|---|---|---|---|
| What queries already reach this site? | Existing GSC client and seo-keyword-research scripts | Google service account with property access | Actual observed clicks/impressions, not the whole market |
| What related searches should we investigate? | research_market.py: dataforseo / ideas | DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD; billable live POST | Keyword ideas and vendor volume/trends, including unranked/new sites |
| Who ranks and for what? | dataforseo / competitors and ranked-keywords | Same credentials; bounded result limit | Search competitors may differ from business competitors |
| What are the keyword metrics and competing domains in Ahrefs? | ahrefs / volume, competitors or ranked-keywords | AHREFS_API_KEY; API entitlement/units, country-level results | Modeled demand/rankings, not actual site visits; volume returns keyword overview metrics |
| What does Google return for this intent? | dataforseo / serp; volume for a demand estimate | Same credentials; country/location and language matter | Observed SERP and estimated searches, not predicted website traffic |
| What do customers/competitors say on the open web? | brave / search | BRAVE_SEARCH_API_KEY; account subscription/quota | Independent index; never label its results Google positions |
| What is on the source page, including rendered content? | firecrawl / search or scrape | FIRECRAWL_API_KEY for account credits; limited anonymous access documented and attempted when absent | Read content and context; extraction does not verify truth |
| Which conversations suggest problems? | Existing scripts/lib/sociavault.py, used by publication research | SOCIAVAULT_API_KEY; endpoint-specific entitlement | Anecdotal demand signals, not a representative market sample |
| What happened after we shipped? | traffic_report.py --ga4 and existing GSC scripts | GA4_PROPERTY_ID + Google credential/property permissions | Actual attributable observations, subject to coverage/consent |

Ahrefs is available through this collector; Semrush remains an existing client alternative.
Neither is required alongside DataForSEO. No additional vendor is added solely to duplicate the same
dataset. AI-provider probes remain diagnostics; there is no claim of a consumer ChatGPT
traffic API. This addition focuses on research gaps rather than multiplying subscriptions.

## Commands

Resolve GROWTH to the absolute installed seo-growth directory. Run from the target repository.
Derive query/target values from inspected business facts and previous research; the examples
are syntax, not a fixed niche. `--allow-paid` is passed by the agent under the owner's existing
scope and budget; do not ask again on each request.

```bash
python3 "$GROWTH/scripts/research_market.py" --provider dataforseo --operation ideas --query "equipment inspection checklist" --location 2840 --language en --limit 10 --allow-paid
python3 "$GROWTH/scripts/research_market.py" --provider dataforseo --operation competitors --target competitor.example --location 2840 --language en --limit 10 --allow-paid
python3 "$GROWTH/scripts/research_market.py" --provider dataforseo --operation ranked-keywords --target competitor.example --location 2840 --language en --limit 10 --allow-paid
python3 "$GROWTH/scripts/research_market.py" --provider dataforseo --operation serp --query "equipment inspection checklist" --location 2840 --language en --allow-paid
python3 "$GROWTH/scripts/research_market.py" --provider ahrefs --operation volume --query "equipment inspection checklist" --country US --allow-paid
python3 "$GROWTH/scripts/research_market.py" --provider ahrefs --operation competitors --target competitor.example --country US --limit 10 --allow-paid
python3 "$GROWTH/scripts/research_market.py" --provider ahrefs --operation ranked-keywords --target competitor.example --country US --limit 10 --allow-paid
python3 "$GROWTH/scripts/research_market.py" --provider brave --operation search --query "equipment inspection checklist problems" --country US --language en --limit 5 --allow-paid
python3 "$GROWTH/scripts/research_market.py" --provider firecrawl --operation scrape --target https://competitor.example/guide --allow-paid
```

Each accepted collection writes an immutable timestamped response/failure file, provider,
query/target, requested and applied locale, collection time and reported cost when available.
Invalid arguments, missing authorization or exhausted call allowance are rejected before
collection; missing provider credentials produce a durable failure without consuming allowance.
CLI output includes a bounded preview and artifact path; inspect relevant saved fields rather
than dumping the full response. Use that path as a strategy snapshot, citing an actual excerpt.
Firecrawl search sends `--country` and optional textual `--search-location`; its endpoint does
not accept the generic language or numeric location fields, which the receipt marks unsupported.
Brave sends country/search language; DataForSEO sends numeric location and supported language.
Ahrefs sends lowercase `--country`; language and location options are recorded as unsupported.
Domain reports use the current UTC snapshot date; keyword overview uses current metrics.
Ahrefs `volume` accepts up to `--limit` comma-separated keywords; domain routes bound returned
rows by that limit. Ahrefs API units are not reported as dollar cost. This collector does not
yet expose Ahrefs keyword ideas or SERP overview; use the documented DataForSEO routes for those.
An empty valid response is a bounded result, not evidence of no demand. A queued task, quota
error, auth error or timeout never becomes a completed market study. Read original pages
before making claims based on search snippets. Do not send private customer text to a vendor
unless the operating scope covers it; derive non-sensitive search terms instead.

The collector reserves each logical call before network access. Default allowance is twenty
calls across providers per UTC day; set `growth.research.daily_call_limit` according to the
authorized scope. Rejected/uncertain attempts consume allowance so restart cannot silently
reset spending. Existing low-level clients/other scripts do not share this collector allowance;
use this entry point for unattended market research. Provider account dollar caps remain
separate because endpoint tariffs and credits vary. Do not automatically raise either cap.

## Official references and vetting scope

- Ahrefs (checked 2026-09-23): [keyword overview](https://docs.ahrefs.com/en/api/reference/keywords-explorer/get-overview), [organic competitors](https://docs.ahrefs.com/en/api/reference/site-explorer/get-organic-competitors), [organic keywords](https://docs.ahrefs.com/en/api/reference/site-explorer/get-organic-keywords). Bearer-authenticated GET; overview uses `difficulty`, competitors use `keywords_common`; domain reports require country/date.
- [DataForSEO keyword ideas](https://docs.dataforseo.com/v3/dataforseo_labs-google-keyword_ideas-live/): live POST, one task array, keywords/location/language/limit; category-related expansions.
- [DataForSEO ranked keywords](https://docs.dataforseo.com/v3/dataforseo_labs-google-ranked_keywords-live/): domain/page rankings with keyword and SERP data. Vendor updates are not necessarily live observations.
- [DataForSEO competitors](https://docs.dataforseo.com/v3/dataforseo_labs-google-competitors_domain-live/): domain overlap; use the current Google namespace, not the legacy endpoint.
- [Brave web search](https://api-dashboard.search.brave.com/documentation/services/web-search): GET, X-Subscription-Token, country/search_lang, bounded count. Native HTTP works from Python or curl; no browser plugin is required.
- [DataForSEO sandbox](https://docs.dataforseo.com/v3/appendix/sandbox/): useful for schema exploration; sandbox outputs are samples, not research evidence. This collector uses production endpoints only.
- [Firecrawl search](https://docs.firecrawl.dev/features/search) and [scrape](https://docs.firecrawl.dev/features/scrape): existing HTTP client, useful for source retrieval.

No new dependency is required. API verification in this revision covers documented auth,
method/path/parameters and offline request/response/error behavior. Run a small authorized
collector call in the target to verify its credentials and inspect the saved response before
recurring research. Missing keys produce a specific blocker; use another configured source.
Firecrawl currently documents anonymous search/scrape; the collector can attempt it without
a key. An anonymous quota/denial is a recorded failure, never an assumption of unlimited free access.
