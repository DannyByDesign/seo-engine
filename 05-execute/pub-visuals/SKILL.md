---
name: pub-visuals
description: Plan, source, generate and review publication imagery under the website image workflow. Reuse approved assets, capture real product screenshots, source licensed imagery, or generate on-brand illustrations; render evidence-based diagrams and set asset and placement metadata. Use after outlining and before publication review. Other website pages follow the same shared image workflow in their existing stack.
---

# pub-visuals

Read the [website image workflow](../../shared/seo-references/images.md) and the target's
`.seo-engine/visuals.md`. This skill obtains the images planned with the outline, implements
their metadata, and inspects the result. Generation is one sourcing option.

## When to use this skill

Use when planning or producing publication imagery, and again before final visual review.
For host-written website pages, use the shared image workflow with their existing components.

## What it checks / does

1. Read article `visual_plan` and approved disclosure boundaries. Inspect existing assets first.
   Choose a factual image for product/evidence coverage or a relevant on-brand illustration.
2. Obtain each asset using the available native tools or configured APIs within existing scope.
   Follow the shared sourcing rules. Never synthesize evidence or a real product screenshot.
3. Inspect the actual image, record `image_assets` facts and placement-specific `cover`/inline
   metadata, and create suitable responsive/social variants using the site's existing tooling.
4. Render desktop/mobile previews and inspect the social crop. Record `visual_review` with the
   editorial review. Fix artifacts, weak relevance, missing attribution and bad crops before release.

A generated image prompt is not proof of what its output depicts. Write informative alt only
after viewing it; decorative images use empty alt. Logos, UI text and faces are legitimate in
appropriate factual assets; don't apply illustration prompt restrictions to screenshots/photos.

## Scripted helpers

### `scripts/gen_cover.py`

Handles `visual_plan.cover.kind: generated` using the plan's `subject`, website-derived
`site.yml` `cover_style` and theme. Other kinds must be obtained by the host and assigned to
`cover.src`. Existing covers are preserved unless `--force` is explicit. Native image tools
can generate an asset directly; write its metadata instead of calling the API helper again.

Scripted generation uses `OPENROUTER_API_KEY`, with `--model` overriding `IMAGE_MODEL`.
Choose a model available through OpenRouter's Image API. No key means a blocker;
`--provider svg` explicitly requests a decorative draft fallback. The helper
records source type, generator, timestamp, measured dimensions and MIME in `image_assets`.
It does not claim visual review or invent image descriptions. Inspect the output, finish alt,
caption and social placement metadata, and crop/resize with existing tools to the planned ratio.
Actual dimensions are recorded; a requested ratio is not assumed to match model output.

### `scripts/render_diagram.py`

Renders `pub-enhance` JSON specs as SVG diagrams (stat callout, stepped flow, funnel,
comparison, timeline), using theme colours and a source footer. `--png` also exports raster
when `cairosvg` or `rsvg-convert` is available. Check every figure and label against evidence,
then inspect the drawing. Provide meaningful alt and a nearby textual explanation/table for
complex data. Record each diagram in `image_assets`; do not treat a rendered spec as verified data.

## Running it

Run from the website root; `SKILL_DIR` is this canonical skill directory.

```bash
python3 "$SKILL_DIR/scripts/render_diagram.py" --publication PUBLICATION --slug ARTICLE --png
python3 "$SKILL_DIR/scripts/gen_cover.py" --publication PUBLICATION --slug ARTICLE
python3 "$SKILL_DIR/scripts/gen_cover.py" --publication PUBLICATION --slug ARTICLE --provider openrouter --model google/gemini-2.5-flash-image --force
python3 "$SKILL_DIR/scripts/gen_cover.py" --publication PUBLICATION --slug ARTICLE --provider svg
```

Flags: `render_diagram.py` `--publication`, `--slug`, `--spec` (repeatable), `--png`,
`--publications-dir`; `gen_cover.py` `--publication`, `--slug`, `--posts`, `--provider`,
`--model`, `--force`, `--publications-dir`. Published posts cannot be changed directly;
work in an isolated refresh draft.

## Expected output

`render_diagram.py` returns `rendered` paths, type and dimensions, plus PNG status when requested.
`gen_cover.py` returns `cover`, file and title, or an explicit blocker with `checked: false`.

## State files

Assets live in the draft's `assets/<article>/` directory (refreshes use their isolated asset
version). `cover` stores placement metadata; `image_assets` stores shareable asset facts.
See the [metadata example](../../shared/seo-references/images.md#4-keep-asset-facts-separate-from-placement-metadata).
The builder renders cover captions/credits, Article image metadata and OG/Twitter variants.

## How to interpret results

The helper reports `requires_visual_review`; success means a file was produced, not that it
is relevant, correctly cropped, licensed for the intended use, or ready to publish.

## Safe to auto-apply vs. human review

Prepare draft assets and metadata within existing permissions and spending scope. Ask only for
missing access, source rights, brand decisions or additional spending. Publication and changes
to live assets remain subject to the website's existing approval workflow.

## Guardrails

Use the planned source type; never generate factual evidence. Preserve existing assets on
refresh, redact private data, and inspect final pixels and placement before recording review.

## References

The [shared image workflow](../../shared/seo-references/images.md) defines sourcing and metadata.
[API setup](../../shared/seo-references/api-reference.md) documents scripted providers.

## Graceful degradation

If tooling/access is missing, report the exact blocker and use another permitted source.
A deliberate SVG fallback is a draft placeholder until reviewed and accepted as the final
brand treatment. Use an appropriate raster social variant where required. No automatic
image-provider switch should conceal a missing selected key or spend on another account.
