---
name: pub-strategy
description: Sets and maintains a publication's editorial positioning (strategy.yml) — client facts measured from its site, the steering direction, priority topics, stances, avoid-list, up to five ranking targets with mention framing, citable landing pages, tracked competitors, brand voice and the mention policy — and scrapes competitor content inventories into keyword-tagged topic files. Invoke right after pub-site scaffolds a publication, whenever positioning changes, or to refresh competitor coverage. Not for choosing the next article (pub-curate).
---

# pub-strategy

The brain's inputs. Everything downstream — topic map, headline scoring, research briefs, the
writer's voice and its mention policy — reads `publications/<slug>/strategy.yml`. This skill
proposes it (LLM), measures the client site to ground it, validates it, and keeps the
competitor inventory that several other skills score against.

## When to use this skill

- First thing after `pub-site` scaffolds a publication: set client, direction, then
  `--measure-brand --suggest`, review, `--apply`.
- The client repositions, launches a product, or the owner wants different stances or targets.
- Weekly (or from `pub-publish`'s pipeline): `scrape_competitors.py` to keep the competitor
  inventory fresh for `pub-curate`.
- **Not** for picking topics or headlines (`pub-curate`) or for the first-party site's own
  keyword research (`seo-keyword-research`).

## What it checks / does

### 1. `scripts/positioning.py`

Explicit sets (`--client-domain`, `--client-name`, `--direction`, `--mention-degree`,
`--mention-rate`) write immediately. `--measure-brand` reads the client homepage and sitemap
(description, slogan, logo, socials, a dozen citable page titles). `--suggest` asks the LLM
for a full draft — priority topics, stances, avoid topics, ranking targets (≤5, each with a
basis of `already_strong | white_space | positioning` and a `mention_framing`), competitors,
landings with "when to cite" context — grounded in the measurement, the publication identity,
existing posts and scraped competitor titles. Both produce a **proposal**; nothing lands in
`strategy.yml` until `--apply`, and owner-marked entries (`source: user`) survive every apply.
`--validate` enforces the five-target cap, mention fields, bare competitor domains and absolute
landing URLs (`--check-urls` fetches each landing).

### 2. `scripts/scrape_competitors.py`

For each competitor: robots-honoring sitemap discovery → article URLs (prefers
`/blog|/posts|/articles|…` paths) → title, description, publish date for up to `--max-pages`
pages → LLM-inferred primary keyword and `high|medium|low` priority against the client
description (title heuristics with `--no-llm`) → optional DataForSEO volume/difficulty.
Writes `competitors/<domain>.json`; skips domains scraped within `--max-age-hours` unless
`--force`. `--fresh-posts` prints the newest posts across competitors (the "Competitor Fresh
Posts" feed).

## Running it

> Run from the target repo root. `${SKILL_DIR}` is this skill's directory.

```bash
python3 "${SKILL_DIR}/scripts/positioning.py" --publication llm-billboard \
  --client-domain thrad.ai --client-name thrad \
  --direction "how brands and agencies buy and measure ads inside LLM assistants"
python3 "${SKILL_DIR}/scripts/positioning.py" --publication llm-billboard --measure-brand --suggest
python3 "${SKILL_DIR}/scripts/positioning.py" --publication llm-billboard --measure-brand --suggest --apply
python3 "${SKILL_DIR}/scripts/positioning.py" --publication llm-billboard --validate --check-urls
python3 "${SKILL_DIR}/scripts/scrape_competitors.py" --publication llm-billboard --domain adexchanger.com
python3 "${SKILL_DIR}/scripts/scrape_competitors.py" --publication llm-billboard --fresh-posts
```

Flags: `positioning.py` `--publication`, `--client-domain`, `--client-name`, `--direction`,
`--mention-degree`, `--mention-rate`, `--measure-brand`, `--suggest`, `--apply`, `--validate`,
`--check-urls`, `--show`, `--publications-dir`; `scrape_competitors.py` `--publication`,
`--domain` (repeatable), `--max-pages`, `--max-age-hours`, `--force`, `--no-llm`,
`--no-volume`, `--fresh-posts`, `--publications-dir`.

## Expected output

`positioning.py` (JSON): `strategy_file`, optional `brand_measurement`, optional `proposal`
(the exact lists an `--apply` would write), `applied`/`written` flags, `validation[]` with
severities, and `notes` (e.g. "proposal only — rerun with --apply").

`scrape_competitors.py`: per competitor `{domain, skipped, topics, new_topics, file, notes}` and
a `fresh_posts` list. Topic files hold `{url, title, description, published_at,
inferred_keyword, keyword_priority, msv, kd}` per article.

## State files

| File | Role | Written by | Read by |
|---|---|---|---|
| `publications/<slug>/strategy.yml` | positioning, targets, landings, competitors, mention policy | `positioning.py` (and by hand) | `pub-curate`, `pub-research`, `pub-write`, `pub-enhance`, `pub-monitor` |
| `publications/<slug>/competitors/<domain>.json` | scraped competitor inventory with keywords | `scrape_competitors.py` | `positioning.py --suggest`, `pub-curate` |
| `.seo-engine/state/http-cache/` | cached competitor page fetches (7 days) | `scrape_competitors.py` | itself |

## How to interpret results

- **The direction string is the steering wheel.** A vague direction produces a generic topic
  map; write it as "<what the publication covers>, for <whom>, with the view that <stance>".
- **Ranking targets are few on purpose.** Five is the cap the vendor also enforces; each one
  spawns GEO probes and steers mention framing, so more targets means diluted measurement.
- **Landings are the only URLs an article may link to on the client site.** Their `context`
  is what the writer matches against a section; a landing with no context is never linked.
- **`--suggest` proposals need a human read** for factual claims about the client — the
  prompt forbids fabrication, the owner confirms.
- **Competitor keyword priority is relative to the client**, not to search volume; a
  high-volume but off-category title is `low`.

## Safe to auto-apply vs. human review

- **Safe without asking:** `--measure-brand`, `--suggest` (proposal), `--validate`, scraping
  competitors, `--show`.
- **Ask first:** `--apply` (positioning is an owner decision), changing `--mention-degree` or
  `--mention-rate`, adding a competitor with `block_from_mentions: true`.

## Guardrails

- Never write invented client facts into `strategy.yml`; proposals cite the measured source.
- Never exceed five ranking targets.
- Competitor scraping honors robots.txt with RFC 9309 semantics, one request per second per
  host, cached for a week — never a full-site crawl.
- `mention.degree` and `rate` are the article-level ceiling (`publication-playbook.md` §6);
  this skill sets them, it never bypasses them.

## References

- [publication-playbook.md](../../shared/seo-references/publication-playbook.md) §4 (the strategy
  substrate and how each field is consumed), §6 (mention policy fields), §8 (the vendor's
  Strategy capability this mirrors).
- [red-flags.md](../../shared/seo-references/red-flags.md) §7 (mentions stay honest; competitors named
  fairly or not at all).
- [api-reference.md](../../shared/seo-references/api-reference.md) — DataForSEO volume/difficulty,
  OpenRouter model configuration.
- [common-setup.md](../../shared/seo-references/common-setup.md) — paths, config, publications layout.

## Graceful degradation

No key: explicit sets, `--measure-brand`, `--validate`, and competitor scraping with heuristic
keywords all work. `OPENROUTER_API_KEY` unlocks `--suggest` and keyword inference; DataForSEO adds
volume/difficulty. A competitor without a sitemap yields an empty inventory with a note rather
than a crawl.
