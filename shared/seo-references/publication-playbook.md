# Publication playbook

## 1. Purpose and limits

A publication is an optional, transparently owned editorial site. Start with the existing website and its users before creating another domain. Technical validity, crawl access and model citations are intermediate signals; this repository has no demonstrated causal traffic lift. Do not describe it as guaranteed growth for any website.

## 2. Site anatomy

Static HTML, useful navigation, canonical URLs, crawlable links, sitemaps and accurate structured data support discovery. Themes, TOCs, `llms.txt`, sitemap priorities and a particular article shape are product defaults, not proven ranking advantages. Google requires no special AI schema. See [Google AI guidance](https://developers.google.com/search/docs/fundamentals/ai-optimization-guide).

## 3. Article quality and cadence

Answer a documented reader need with original evidence, practical examples, a tool, data or expert analysis. Do not restate existing sources at scale. Length and public-source-count floors are optional publication policies, defaulting to zero; contextual editorial review remains mandatory. Match length and format to the question. A launch burst and six posts per week are configurable defaults without measured traffic evidence; empty slots are acceptable.

## 4. Pipeline and deployment

Queue a topic, fetch and compare sources, complete the [topic interview and proposed-use confirmation](content-interview.md), outline, write and enhance, then inspect final text and visuals. `review_article.py` records accountable review of reader need, distinct value and claim/source context. It checks approved attribution and disclosure limits and hashes content, evidence, permissions, assets and publication policy. Any subsequent change requires review again. `run_pipeline.py` resumes the prepared draft without rewriting it. Manual approval is separate from editorial review; review-window and autopilot modes also require an unchanged reviewed draft. Local publication transitions to building, then published after successful validation. This is not deployment. Deploy the built site through the website's authorized hosting workflow, verify production HTML and crawler access, and record the deployment date before evaluating outcomes. A refresh retains its URL, author and original date and supplies original text to research/writing; review that useful material survived.

## 5. Attribution and migration

Use actual contributors supplied by the publisher, or the default clearly identified editorial organization. Never invent people, credentials, locations or tenure. Scaffolding defaults to one organization author and today's start date. Backdating is rejected. Ownership disclosure is enabled. Legacy `--authors` and `--deterministic-authors` are migration flags; they do not generate people. For an existing scaffold, replace fictional author records and affected post bylines with accurate attribution, remove invented biographies/dates, enable ownership disclosure, record contextual claim review for each existing article using `review_article.py --posts --review-file`, and rebuild. Production builds reject missing or stale receipts; `--include-drafts` is a noindex preview only. Do not attribute old work to a real person without their involvement.

## 6. Mentions and links

Mention the business only when it helps the reader and is factually supported. Disclose the owner and commercial relationship; never present owned coverage as independent endorsement. Do not force keyword mentions or links to hit a quota. Paid placements require appropriate link qualification. Multiple domains, hidden ownership and mass paraphrases are not a growth strategy. See [Google spam policies](https://developers.google.com/search/docs/essentials/spam-policies).

## 7. Measurement

Measure Google clicks in Search Console and actual Google/ChatGPT referrals and meaningful conversions in analytics. Keep API model probes separate from consumer ChatGPT citations and visits. Missing credentials/data are unknown, never zero. Compare equal, nonoverlapping, mature windows for the same property, filters and cohorts. Track baseline, deployment, spend, uncertainty and rollback decisions. Observational changes cannot by themselves prove causality.

## 8. Writing references

The local human corpus provides writing techniques. It is separate from current topic evidence and approved company experience; never import its historical facts as product claims. Read the selected passages before drafting and preserve their recorded example IDs.
