# Website images

Use for article covers, inline illustrations, product screenshots, landing pages, product
pages, diagrams and social previews. Apply in both host-written and scripted content.
Images must help explain the page or deliberately express its brand; filling space is not a goal.

## 1. Establish the website's visual brief

During onboarding, inspect existing pages, asset folders, design tokens, CMS image fields and
image components. Save a concise `.seo-engine/visuals.md`: references to approved assets and
representative pages; photography/illustration style; palette, composition and typography;
logo/product depiction rules; preferred cover and social crops; sourcing permissions and
budget; existing optimization pipeline; unresolved choices. Keep this website's preferences
out of the reusable engine. Ask about gaps through the native question tool, not a new full
brand questionnaire. Reuse the brief on later runs and update it when the owner changes direction.
Publication `site.yml` `cover_style` is a rendering prompt derived from this brief, not its replacement.

## 2. Plan images before drafting

Read the visual brief with the topic research and approved contribution. Each article needs
a deliberate cover choice: a relevant factual image or an on-brand editorial illustration.
For each planned placement, record purpose, subject, source approach, aspect/crop requirements,
and the claim or section it supports. Add inline images only where they demonstrate or explain
something; there is no image-count quota. Other pages need images only where useful for their
particular reader task. Reuse the existing CMS/component conventions.

Product walkthroughs need real screenshots or approved product assets. A diagram should make
a supported process or dataset clearer. A conceptual article can use an original illustration
in the established visual style. Never fabricate a screenshot, result, testimonial, customer,
or photograph of an actual event. Identify conceptual mockups as such. Ask the operator only
for missing access, assets, factual clarification or permission that cannot be established.

For publications, store the plan in article frontmatter `visual_plan`, with `cover` and optional
`inline` entries. Cover `kind` is `existing`, `screenshot`, `licensed`, `generated` or `diagram`;
include `purpose`, `subject` and `aspect_ratio`. `gen_cover.py` only handles `generated` covers.
Host agents obtain the other kinds and set `cover.src` to the resulting local asset.
Keep plans free of private notes: frontmatter may eventually be shared with the website source.

## 3. Source or produce the image

Prefer a suitable existing approved asset. Next capture the real product or create an accurate
diagram from established evidence; source an external image with documented reuse permission
when appropriate. Generate a new illustration when that is the right treatment. Availability
in search results alone is not reuse permission. Record the original source and applicable
credit/license; do not invent them or hotlink without a supported permission/delivery arrangement.

Use the host's available native image search, browser/computer-use and image-generation tools
according to their tool instructions. Discover actual capabilities; do not assume a model
vendor guarantees a tool. Pass approved visual references to generation/editing tools when
supported. Otherwise use configured image APIs within existing spending authority. No extra
image API key is needed when a suitable host tool is available. Product screenshots may
legitimately contain UI text, logos and people; don't apply an abstract-cover ban to all images.
Inspect and redact private account/customer information before saving publishable screenshots.

Read the completed image, not just the prompt. Check actual subject, factual accuracy, visual
artifacts and brand fit. A missing tool/key is a sourcing blocker, not permission to silently
substitute generic artwork. A placeholder must be labelled as a draft and replaced before
publication unless the operator deliberately chooses it as the final decorative treatment.

## 4. Keep asset facts separate from placement metadata

Use existing CMS asset fields if available. Otherwise record asset metadata in a small site-local
manifest. For publications, use `image_assets` in article frontmatter, keyed by the same relative
filename used in `cover.src` or body Markdown. It holds shareable asset facts: `source_type`,
`source_url`, `creator` (`name` and `type`: Person or Organization), `credit_text`, `license_url`,
`copyright_notice`, `width`, `height`, `mime`, and, for generated work, `generator` and `created_at`.
Omit unknown/inapplicable rights fields; record unresolved permission privately and resolve before
use. Keep sensitive receipts, source access URLs and generation prompts in ignored workspace
notes. Public metadata describes the final redacted image, never its hidden original.

Placement metadata belongs with the page: role, context-specific `alt`, `decorative`, optional
`caption`, chosen crop and social variant. Informative alt conveys the image's useful meaning;
decorative images have `alt: ""`. Don't repeat the headline as a universal template or stuff
keywords into tags. Diagrams need a useful text explanation or table for their substantive data.
The same asset can need different alt text in different contexts. Linked images need an
accessible link name even when the image is decorative. See [W3C's alt decision tree](https://www.w3.org/WAI/tutorials/images/decision-tree/).

Publication example (fill only with verified values):

```yaml
image_assets:
  export-workflow.png:
    source_type: screenshot
    creator: {type: Organization, name: Acme}
    credit_text: Acme product screenshot
    width: 1600
    height: 900
    mime: image/png
cover:
  src: export-workflow.png
  alt: Export dialog with CSV selected and the date-range selector open
  decorative: false
  caption: Export settings in the current product.
  variants: [{src: export-workflow-640.png, width: 640}, {src: export-workflow.png, width: 1600}]
  sizes: "(max-width: 700px) 100vw, 704px"
  social: {src: export-social.jpg, alt: CSV export settings, width: 1200, height: 630}
```

Record a separate asset entry for a separate social file. The builder carries available
creator, credit, copyright and license fields into the cover's `ImageObject`. Captions are
separate from alt. `cover.social` overrides the article's OG/Twitter image; absent it, the
cover is reused. `cover.variants` and `sizes` render responsive attributes from real prepared
files (each variant uses the same crop/composition and its measured width). Inline figures use Markdown/HTML with placement-specific alt and captions;
use the site's image components for responsive variants. Asset records alone do not generate
inline licensing markup or responsive files. Add that markup when applicable to the page.

Use short descriptive filenames, accurate dimensions/MIME, compressed responsive variants and
stable crawlable URLs. Follow the existing framework's image pipeline rather than adding one
unnecessarily. Prioritize the actual hero/LCP image; lazy-load below-fold images. Provide raster
social previews when the destination needs them, especially for SVG covers. Use applicable
Article/Product/WebPage image properties. License/creator metadata or IPTC fields describe
verified rights; they are not keyword-ranking switches. Preserve useful attribution/provenance
while removing sensitive EXIF such as private GPS. See [Google image guidance](https://developers.google.com/search/docs/appearance/google-images)
and [image metadata](https://developers.google.com/search/docs/appearance/structured-data/image-license-metadata).

## 5. Review the rendered page

Before declaring content ready, inspect the actual page at desktop and mobile sizes: relevant
subject, truthful product/data depiction, permitted use, consistent style, legible details,
useful captions/alt, sensible crop, no sensitive data, and no missing/distorted assets. Verify
the delivered file dimensions/format/weight, responsive/loading behaviour, image URLs,
OG/Twitter previews and applicable structured data. Inspect the actual social crop too.
An API success or nonempty filename does not establish image quality.

Record a short `visual_review` in the publication's editorial review JSON (or website page's
existing review notes): assets/placements inspected, preview evidence, metadata/rights checked,
and fixes or unresolved limitations. Asset/metadata changes require another review; publication
receipts already hash local assets and frontmatter. If rendering tools are unavailable, record
that limitation and don't claim a visual check passed. Final publication/deployment still follows
the existing approval workflow; ordinary draft image work does not require a new approval round.
