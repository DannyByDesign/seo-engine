# 05 Execute

For substantive content, follow [Topic research and interview](../shared/seo-references/content-interview.md):
research existing answers, interview for this topic, confirm proposed use, then outline and write.

Implement the selected intervention in the website's actual source and existing design system.
The host agent writes copy and code; scripts do not manufacture strategy by filling templates.
Use the copy brief and inspect every important claim against its source. New landing pages,
comparisons, tools, templates and guides are supported when they serve a distinct reader task.
Use technical, metadata, schema, indexing, performance and internal-linking skills where needed.
Treat the existing publication pipeline as an optional channel, not the default website adapter.

Before composing, read [seo-copywriting/SKILL.md](../05-execute/seo-copywriting/SKILL.md), including its frozen human passages.
Select a packet with `writing_examples.py --mode landing|article|docs|news|essay --seed TOPIC`.
Use at least three source texts and two available genres; record the example IDs and the techniques
chosen. The article writer supplies these references automatically. First-party host agents
use the same packet explicitly. Source facts still come exclusively from the research brief.

After drafting, use `seo-copywriting/scripts/check_writing.py` for LanguageTool proofreading.
Fix real grammar/spelling errors, assess style suggestions against the intended voice, and
rerun after changes. Record accepted/rejected suggestions with the final report and any reason
for proceeding with an unavailable checker. No zero-match quota or automatic prose replacement.
Automatic article checks cover body text. Check visible titles and summaries separately with
`check_writing.py --file visible-metadata.txt --format text`; Markdown frontmatter is excluded.

Copy must explain the offering concretely, answer the intended task, address relevant objections
and offer a working next action. Evaluate clarity and originality, evidence fit, search intent,
discovery paths and conversion behavior. An agent can do this review; do not invent a mandatory
human signoff where the user's scope already authorizes autonomous edits. Specialized factual
questions still need their actual source, not an agent's invented confidence score.

Run the project's meaningful tests/build. Inspect rendered desktop/mobile output and actual
links/forms/tools for changed behavior; source string matching is insufficient. Add focused
regressions for calculations or interactions. Check indexability, self-canonical URLs, crawl
access, internal links and sitemap inclusion for new pages. Preserve valuable URLs on refresh.

Use `run_growth.py` to validate, deploy within existing authorization, and verify production.
Record durable intent before external mutation; an uncertain deployment is inspected, not
blindly retried. Without deployment access, leave a validated patch and precise blocker while
continuing independent research. Credentials alone do not authorize publication or outreach.

Owned-publication visuals use isolated asset bundles for refresh drafts. Cover and diagram
commands fork the prior bundle before writing; the published article keeps its reviewed bundle
until the refreshed article passes review and replaces it. Direct edits to published assets
are refused. Rendering uses the bundle recorded in article metadata while preserving its URL.

## Tools in this directory

[geo-optimize](../05-execute/geo-optimize/SKILL.md), [pub-enhance](../05-execute/pub-enhance/SKILL.md), [pub-publish](../05-execute/pub-publish/SKILL.md), [pub-site](../05-execute/pub-site/SKILL.md), [pub-visuals](../05-execute/pub-visuals/SKILL.md), [pub-write](../05-execute/pub-write/SKILL.md), [seo-content-optimize](../05-execute/seo-content-optimize/SKILL.md), [seo-copywriting](../05-execute/seo-copywriting/SKILL.md), [seo-indexing](../05-execute/seo-indexing/SKILL.md), [seo-internal-linking](../05-execute/seo-internal-linking/SKILL.md), [seo-metadata](../05-execute/seo-metadata/SKILL.md), [seo-performance](../05-execute/seo-performance/SKILL.md), [seo-redirects](../05-execute/seo-redirects/SKILL.md), [seo-structured-data](../05-execute/seo-structured-data/SKILL.md).
