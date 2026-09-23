# Select work for the actual website

These are implementation recipes, not claims of tested traffic effectiveness.

| Site | Demand and contribution | Source and verification |
|---|---|---|
| SaaS/product | Buyer questions, comparison intent, onboarding failures; demonstrate actual product behavior | Existing product/pricing/docs routes and shared templates; preserve pricing facts and conversion paths |
| Ecommerce | Product/category intent, actual catalog and availability; original product details and useful categories | Product/CMS templates, feed and structured-data generators; verify rendered price/stock and canonical filters; avoid indexing every search/facet permutation |
| Local service | Actual service-area questions, genuine locations and operating evidence | Service/location/contact pages and business data; verify address/hours; never fabricate city pages or reviews |
| Docs/API | Support questions and reproducible tasks; working examples tied to supported versions | Documentation content and renderer; execute examples, validate generated anchors and version navigation |
| Editorial | Unanswered information need and original reporting/data | Existing content pipeline; retain sources, author accountability, citations and useful existing text |
| Client-rendered app | A genuine public information need plus raw/rendered visibility evidence | Existing SSR/prerender/build route; inspect raw HTML and a browser, preserve app functionality |

For a cold-start site, inspect real customer questions and dated SERPs for seed queries.
Record geography/language, search intent, competing result types, content already owned and
what the business can uniquely substantiate. Paid seed discovery is optional and explicit;
unknown volume is not zero demand. Compare improving a current page, adding a genuinely new
page/tool, and doing nothing if evidence or contribution is insufficient. Do not create a
second URL that competes with an existing answer to the same intent.

The executable integration tests currently exercise static HTML, a server-rendered product route driven by structured data, and command-based
agent handoff. Framework/CMS recipes require the target repo's actual build/test/deploy commands.
A missing CMS write interface, private-only site, unknown deployment target or absent analytics
is an explicit limitation, not a successful universal integration.
