# JSON-LD example library

Minimal, valid examples for every `@type` `validate_schema.py` recognizes, plus where to insert
the tag per framework. Extra properties (e.g. `dateModified`, `publisher`, `aggregateRating`) are
encouraged where genuinely true — the properties shown here are the validation floor, not a ceiling.

In every case: **build the JSON-LD from the same data the visible page already renders.** A
second, independently-maintained data source for structured data is exactly how `headline`/
`datePublished`/`author` drift out of sync with the visible page and start failing the validator.

## Product

```json
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Product name as shown on the page",
  "image": "https://example.com/images/product.jpg"
}
```
Add `offers`, `sku`, `aggregateRating` etc. only with real, current data — Google's
Merchant/product-rich-result policies require accuracy.

## Organization (homepage / global)

```json
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "name": "Acme Corp",
  "url": "https://example.com"
}
```

## FAQPage

Only on pages that visibly render the Q&A as page content — never hidden/duplicate FAQ blocks
injected purely for the schema; that reads as manipulative markup, not genuine content. Google
retired FAQ rich results for most sites (info-severity in the validator, not an error) — the
markup remains valid and worth having for entity comprehension, just don't expect a visual
treatment outside well-known health/government sites.

```json
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {
      "@type": "Question",
      "name": "Question exactly as displayed",
      "acceptedAnswer": {"@type": "Answer", "text": "Answer exactly as displayed"}
    }
  ]
}
```

## BreadcrumbList

```json
{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://example.com"},
    {"@type": "ListItem", "position": 2, "name": "Blog", "item": "https://example.com/blog"}
  ]
}
```

## LocalBusiness

Address/geo data must match the business's actual, verifiable address — never infer or template
a location.

```json
{
  "@context": "https://schema.org",
  "@type": "LocalBusiness",
  "name": "Acme Coffee — Downtown",
  "address": {
    "@type": "PostalAddress",
    "streetAddress": "123 Main St",
    "addressLocality": "Portland",
    "addressRegion": "OR",
    "postalCode": "97201",
    "addressCountry": "US"
  }
}
```

## HowTo

Google retired HowTo rich results (info-severity, not an error — same reasoning as FAQPage above).

```json
{
  "@context": "https://schema.org",
  "@type": "HowTo",
  "name": "How to do the thing",
  "step": [
    {"@type": "HowToStep", "name": "Step 1", "text": "Do this first."},
    {"@type": "HowToStep", "name": "Step 2", "text": "Then do this."}
  ]
}
```

## VideoObject

```json
{
  "@context": "https://schema.org",
  "@type": "VideoObject",
  "name": "Video title",
  "description": "Video description",
  "thumbnailUrl": "https://example.com/thumb.jpg",
  "uploadDate": "2026-07-05T09:00:00-07:00"
}
```

## Person (author/team bio page)

```json
{
  "@context": "https://schema.org",
  "@type": "Person",
  "name": "Jane Doe"
}
```

## WebSite (usually paired with Organization on the homepage)

```json
{
  "@context": "https://schema.org",
  "@type": "WebSite",
  "name": "Acme Corp",
  "url": "https://example.com"
}
```

## Recipe

```json
{
  "@context": "https://schema.org",
  "@type": "Recipe",
  "name": "Recipe name as shown on the page",
  "image": "https://example.com/images/recipe.jpg",
  "recipeIngredient": ["1 cup flour", "2 eggs"],
  "recipeInstructions": [
    {"@type": "HowToStep", "text": "Mix the ingredients."},
    {"@type": "HowToStep", "text": "Bake at 350F for 20 minutes."}
  ]
}
```

## Where to insert the tag, per framework

The tag itself is always the same:
`<script type="application/ld+json">{...}</script>` — the difference is purely where the
framework wants it and how the JSON gets serialized safely.

- **Next.js (App Router):** in the relevant `page.tsx`/`layout.tsx`, render
  `<script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />`
  inside the returned JSX. Put `Organization`/`WebSite` in the root `layout.tsx` (site-wide,
  once); put page-specific types (`Article`, `Product`, `FAQPage`, ...) in the individual
  `page.tsx`, built from the same data the page already renders (frontmatter, CMS fetch result,
  DB row) — never a second, separately maintained copy of the data.
- **Next.js (Pages Router):** same `<script>` pattern inside the page component's returned JSX,
  or in `_app.tsx`/`_document.tsx` for site-wide types.
- **Astro:** `<script type="application/ld+json" set:html={JSON.stringify(jsonLd)}>` in the
  `.astro` component's template — the relevant layout for site-wide types, the page component for
  page-specific types.
- **Hugo:** a partial (e.g. `layouts/partials/jsonld.html`) rendering
  `<script type="application/ld+json">{{ . | jsonify }}</script>` using the page's existing
  front-matter/`.Params`, included from the relevant layout template.
- **Plain HTML / static site generators without templating logic:** the same literal
  `<script type="application/ld+json">` tag hand-written (or generated at build time) directly in
  each page's `<head>` or before `</body>`.
