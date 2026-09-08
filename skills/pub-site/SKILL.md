---
name: pub-site
description: Scaffolds, builds, and validates an independent editorial publication (a "phantom" third-party site): masthead, sections, recurring author bank, theme, and a static site whose pages reproduce the measured phantom anatomy (theme tokens, robots/OG meta, Organization+WebSite graph, BlogPosting with citation[], ProfilePage/AboutPage, RSS, llms.txt, priority sitemap). Invoke to create a publication, rebuild dist/ after publishing, or check a built or live site against the checklist. Not for writing (pub-write) or topics (pub-curate).
---

# pub-site

The container every other `pub-*` skill writes into. A publication lives at
`<publications_dir>/<slug>/` (default `publications/`) as `site.yml` + `posts/*.md` +
`assets/` + `static/`; `build_site.py` turns that into `dist/`, a static site you deploy as-is.
The rendered anatomy is the one measured on live Letterstory phantoms
(`publication-playbook.md` §2-§3), plus image dimensions and self-hosted images.

## When to use this skill

- "Launch a new publication for <category>" — run `scaffold_publication.py` (dry-run first).
- After any post is published or edited — run `build_site.py`, then deploy `dist/`.
- Before the first deploy, after a template change, or when a live site looks wrong — run
  `validate_site.py` (it also validates arbitrary saved HTML or a live URL, so it doubles as
  a competitor-anatomy checker).
- **Not** for topics (`pub-curate`), research/writing (`pub-research`, `pub-write`), visuals
  (`pub-visuals`), or scheduling (`pub-publish`).

## What it checks / does

### 1. `scripts/scaffold_publication.py` — identity, sections, authors, theme

Writes `site.yml` from flags, or proposes name/tagline/sections from `--from-domain` +
`--direction` when an LLM key is configured. Enforces the one hard naming rule: the masthead
is named after its subject and **may not contain the client name** (`--allow-client-name`
overrides). Generates a recurring author bank (`--authors`, default 8) — with an LLM when
available, otherwise from a seeded name bank so reruns are stable — using the measured bio
template; `--author-tenure backdated` (default, playbook §5) or `real`. Picks a theme from
`scripts/lib/publication.py → THEMES` (seeded unless `--theme`). Disclosure is off unless
`--disclosure`. Registers the publication in `.seo-engine/config.yml → publications` so the
validator knows the sibling set. `--dry-run` prints the plan and writes nothing.

### 2. `scripts/build_site.py` — render dist/

Markdown + frontmatter → HTML with: theme tokens on `<html>`, canonical, robots/googlebot
meta, OG/Twitter, the JSON-LD set (graph, Blog, BlogPosting + BreadcrumbList, ProfilePage,
AboutPage, CollectionPage), "In this article" TOC from H2s, inline external links marked
`nofollow`, a followed Sources list mirrored into `citation[]`, resolved `/assets/` images
with width/height, `feed.xml`, `llms.txt`, priority sitemap, `robots.txt`, `404.html`,
`vercel.json` (clean URLs). Drafts are skipped unless `--include-drafts`. `static/` is copied
verbatim (verification files, `og-default.png`).

### 3. `scripts/validate_site.py` — the anatomy checklist

Per page: lang, theme tokens, robots meta, canonical (absolute; equals the page URL in dist
mode), OG/Twitter, graph + page-kind JSON-LD, one H1, body H2 count, TOC, inline nofollow vs
followed Sources, `citation[]` mirror, image alt (error) and dimensions (warning), word floor
(`--min-words`), internal body links. Site-wide: robots.txt evaluated per crawler with RFC
9309 semantics (a blocked citation crawler is an error, a blocked training-only crawler a
warning), sitemap priorities/lastmod/coverage, RSS and llms.txt agree with the post count, no
links to sibling publications or the vendor, disclosure consistent with `site.yml`.

## Running it

> All commands run from the **target repo root** (the repo that contains the website and
> `.seo-engine/`). `${CLAUDE_SKILL_DIR}` is set by Claude Code to this skill's directory.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/scaffold_publication.py" --name "LLM Billboard" \
  --site-url https://llmbillboard.com --tagline "A blog on conversational AI advertising." \
  --sections "Advertiser Strategy,AI Search,Performance Benchmarks" \
  --client-name thrad --client-domain thrad.ai --theme signal --icon leaf --dry-run
python3 "${CLAUDE_SKILL_DIR}/scripts/scaffold_publication.py" --from-domain thrad.ai \
  --direction "how agency trading desks buy paid placements inside LLMs" \
  --site-url https://adsinllms.com --client-name thrad
python3 "${CLAUDE_SKILL_DIR}/scripts/build_site.py" --publication llm-billboard
python3 "${CLAUDE_SKILL_DIR}/scripts/validate_site.py" --publication llm-billboard
python3 "${CLAUDE_SKILL_DIR}/scripts/validate_site.py" --url https://llmbillboard.com --max-pages 6
cd publications/llm-billboard && vercel deploy dist/   # preview; promote to production from the Vercel CLI/dashboard after validation
```

Flags: `scaffold_publication.py` `--name`, `--slug`, `--site-url` (required), `--tagline`,
`--direction`, `--from-domain`, `--client-name`, `--client-domain`, `--sections`, `--authors`,
`--author-tenure`, `--deterministic-authors`, `--theme`, `--icon`, `--language`,
`--disclosure`, `--allow-client-name`, `--publications-dir`, `--dry-run`, `--force`;
`build_site.py` `--publication`, `--all`, `--out`, `--include-drafts`, `--publications-dir`;
`validate_site.py` `--publication`, `--dist`, `--html-dir`, `--url`, `--max-pages`,
`--min-words`, `--strict`, `--publications-dir`.

## Expected output

`scaffold_publication.py` (JSON): `plan.site` (the exact `site.yml` content), `plan.notes`
(what was defaulted or LLM-proposed), and on write `applied.site_yml` + `next_steps`.

`build_site.py`: `builds[].{publication, site_url, posts, sections, authors, pages[], warnings[]}`
— warnings name posts with missing alt text or skipped drafts.

`validate_site.py`:
```jsonc
{ "checked": true, "mode": "dist", "pages_checked": 14, "posts_checked": 9,
  "summary": { "errors": 0, "warnings": 3, "info": 1 },
  "findings": [ { "severity": "warning", "page": "/posts/…", "check": "img-dimensions", "message": "…" } ],
  "verdict": "pass", "report_file": ".seo-engine/reports/pub-site-validate-<stamp>.json" }
```
Exit code 1 on errors (or warnings with `--strict`).

## State files

| File | Role | Written by | Read by |
|---|---|---|---|
| `publications/<slug>/site.yml` | masthead, sections, authors, theme, disclosure, client | `scaffold_publication.py` | every `pub-*` skill |
| `publications/<slug>/posts/*.md`, `assets/`, `static/` | content and files rendered into the site | `pub-publish`, `pub-enhance`, `pub-visuals` | `build_site.py` |
| `publications/<slug>/dist/` | build output — deploy this | `build_site.py` | `validate_site.py`, your deploy step |
| `.seo-engine/config.yml → publications, publications_dir` | registry of publications (sibling set) | `scaffold_publication.py` | `validate_site.py`, `pub-publish` |
| `.seo-engine/reports/pub-site-validate-<stamp>.json` | dated validation report | `validate_site.py` | calling agent |

## How to interpret results

- **A scaffold plan is a proposal.** Read the name against the "independent outlet named
  after its subject" rule, the sections against the topic map you intend to build, and the
  authors against `publication-playbook.md` §5 before writing.
- **`ai-crawlers` errors are the one finding that voids the whole exercise** — a publication
  no citation crawler can read cannot earn citations. Fix `robots.txt` before anything else.
- **`network-footprint` errors** mean two of your publications link to each other or a page
  links to the vendor; both are footprints the measured sites avoid entirely.
- **Warnings are the measured norm, not law.** A 900-word post or a five-section article is
  allowed; the warning tells you it is outside what was observed working.
- **`citation-mirror` / `sources-followed`** — the Sources list is the one place external
  links are followed; keep inline citations nofollow.

## Safe to auto-apply vs. human review

- **Safe without asking:** `--dry-run`, `build_site.py`, `validate_site.py`, rebuilding
  `dist/` after content changes.
- **Ask first:** writing `site.yml` for a new publication (name, personas and disclosure are
  owner-level choices), overwriting with `--force`, deploying to production, buying or
  pointing a domain.
- **Never silently:** turning disclosure off on a publication where it was on, or naming a
  publication after the client with `--allow-client-name`.

## Guardrails

- The masthead never contains the client name unless the owner explicitly overrides.
- Publications never interlink and never link to the vendor or this engine.
- `robots.txt` never blocks a citation crawler (geo-playbook §4 lists what each bot gates).
- Nothing here changes content; the builder renders what `posts/` contains.
- Deploy `dist/` only after `validate_site.py` passes with zero errors.

## References

- [publication-playbook.md](../seo-references/publication-playbook.md) §1 (charter and owner
  decisions), §2 (site anatomy this builder reproduces), §3 (article anatomy the validator
  checks), §5 (personas and sections).
- [geo-playbook.md](../seo-references/geo-playbook.md) §4 (per-crawler effects behind the
  robots check), §11 (why the site is static HTML with no client-side rendering).
- [red-flags.md](../seo-references/red-flags.md) §7 (third-party publications: the rules
  that keep this on the right side of the scaled-content and disclosure lines).
- [common-setup.md](../seo-references/common-setup.md) — paths, config, publications layout.

## Graceful degradation

No API key is required for any script. Without an LLM key, `scaffold_publication.py` needs
`--name` (and ideally `--tagline`/`--sections`) and uses the seeded author bank; with one, it
proposes identity from `--from-domain`/`--direction` and generates authors, falling back to
the bank if the model returns too few. `build_site.py` and `validate_site.py` never touch
the network except in `--url` mode. If `.seo-engine/` is unreachable, `validate_site.py`
still prints the full report to stdout (no report file).
