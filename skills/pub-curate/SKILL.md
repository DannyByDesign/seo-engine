---
name: pub-curate
description: Decides what a publication writes next: builds the topic map (pillars = sections, spokes = candidate articles with angle, brief, relevance, keyword data and open/queued/covered status), scores open spokes into a ranked headline queue on competitor, GEO, SEO, cluster, authority, social and cannibalization signals, and runs Seers (news, regulation, social conversations, GitHub releases/PRs, spec changes, Notion) that turn events into suggestions or drafts. Invoke after pub-strategy, weekly, or from the pipeline.
---

# pub-curate

The vendor's "Curate" step, reproduced: a topic map that doubles as the site's information
architecture, a scored suggestion queue with a per-signal breakdown, and event-driven Seers.
Everything it produces is a *candidate*; `pub-publish`'s planner is what queues a slot.

## When to use this skill

- Right after `pub-strategy` writes `strategy.yml`: `build_topic_map.py` (first build).
- Weekly or on every pipeline run: `score_suggestions.py` to refresh the queue,
  `build_topic_map.py --mark-covered` after publishing, `seers.py` to poll signals.
- The owner wants a specific piece: `build_topic_map.py --add "<subject>" --pillar <slug>`.
- **Not** for positioning (`pub-strategy`), writing (`pub-write`) or scheduling (`pub-publish`).

## What it checks / does

### 1. `scripts/build_topic_map.py`

Pillars are the publication's sections (`site.yml`), flagged `is_priority` by overlap with
`priority_topics`. Spokes are proposed per pillar by the LLM from direction, stances,
avoid-list, client description, the competitor inventory and everything already published
(never a repeat); without an LLM key they come from competitor titles mapped to pillars by
term overlap plus the priority topics. Near-duplicates are folded (`overlap ≥ 0.6`); existing
spokes keep their status across `--refresh`. DataForSEO volume/difficulty is attached to
spokes with an `seo_keyword` when configured. `--mark-covered` reconciles the map with
`posts/` and `drafts/` by `spoke_id` (frontmatter) or title overlap. `--add`/`--dismiss`
edit single spokes.

### 2. `scripts/score_suggestions.py`

For every `open` spoke: competitor (0.15), GEO gap (0.20), SEO (0.15), cluster (0.15),
authority (0.15), social (0.10), minus a cannibalization penalty (drop at ≥ 0.6 overlap with
anything published or drafted, −0.3× between 0.4 and 0.6). The social signal queries
SociaVault only for the plausible top of the list and caches for a day. Top `--target`
spokes get LLM headlines in the measured title style (or the subtopic as-is) and a `why`.
Writes the queue to state; queued items from the previous run are preserved.

### 3. `scripts/seers.py`

`--propose` drafts seers from the strategy (LLM, or one `news_trend` per priority topic plus a
`social_trend`); `--apply` writes `seers.yml`. Running it polls every due seer, dedupes by
event key, and in `suggest` mode appends a suggestion (`source_type: seer:<provider>`), in
`auto` mode also writes `drafts/<slug>.md` with the brief and the source URL for the pipeline.
Providers: `news_trend`, `regulation_change` (Firecrawl search, else SociaVault Google
search), `social_trend` (SociaVault), `github_release`, `github_pr` (public API, token
optional), `spec_change` (hash + sentence diff of a page), `notion_activity` (`NOTION_TOKEN`).

## Running it

> Run from the target repo root. `${CLAUDE_SKILL_DIR}` is this skill's directory.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/build_topic_map.py" --publication llm-billboard
python3 "${CLAUDE_SKILL_DIR}/scripts/build_topic_map.py" --publication llm-billboard --refresh --spokes-per-pillar 6
python3 "${CLAUDE_SKILL_DIR}/scripts/build_topic_map.py" --publication llm-billboard --mark-covered
python3 "${CLAUDE_SKILL_DIR}/scripts/build_topic_map.py" --publication llm-billboard \
  --add "Deal ID structures for private AI publisher supply" --pillar campaign-setup --brief "Buyers need a deal taxonomy that survives conversational inventory."
python3 "${CLAUDE_SKILL_DIR}/scripts/score_suggestions.py" --publication llm-billboard --target 10
python3 "${CLAUDE_SKILL_DIR}/scripts/seers.py" --publication llm-billboard --propose --apply
python3 "${CLAUDE_SKILL_DIR}/scripts/seers.py" --publication llm-billboard
```

Flags: `build_topic_map.py` `--publication`, `--spokes-per-pillar`, `--refresh`, `--no-llm`,
`--no-volume`, `--mark-covered`, `--add`, `--pillar`, `--brief`, `--dismiss`,
`--publications-dir`; `score_suggestions.py` `--publication`, `--target`, `--no-llm`,
`--no-social`, `--refresh-social`, `--publications-dir`; `seers.py` `--publication`,
`--seer`, `--force`, `--propose`, `--apply`, `--dry-run`, `--publications-dir`.

## Expected output

`build_topic_map.py`: `{spokes_added, marked_covered, summary: {pillars, spokes, open,
queued, covered, dismissed}, notes}`.

`score_suggestions.py`:
```jsonc
{ "open_spokes_scored": 34, "dropped_as_cannibalizing": 2, "social_api_calls": 8,
  "suggestions": [ { "id": "sg-0001", "spoke_id": "sp-0012", "pillar": "ai-search",
    "headline": "Keyword-to-Prompt Translation for Search Advertisers Entering AI Channels",
    "why": "…", "score": 0.61,
    "signal_breakdown": { "competitor": 0.7, "geo": 0.0, "seo": 0.42, "cluster": 1.0, "authority": 0.8, "social": 0.3, "cannibalization": 0.1 },
    "evidence": { "competitor": "adexchanger: …", "social": "14 posts across reddit, twitter; engagement 322" } } ] }
```

`seers.py`: per seer `{events_detected, new_events, produced, mode, notes, events[]}`; with
`--propose`, `proposals[]`.

## State files

| File | Role | Written by | Read by |
|---|---|---|---|
| `publications/<slug>/topic-map.yml` | pillars + spokes with statuses | `build_topic_map.py` | `score_suggestions.py`, `pub-publish` planner, `pub-research` |
| `publications/<slug>/seers.yml` | seer definitions | `seers.py --apply` (and by hand) | `seers.py` |
| `.seo-engine/state/pub-suggestions-<slug>.json` | ranked headline queue (+ seer items) | `score_suggestions.py`, `seers.py` | `pub-publish` planner |
| `.seo-engine/state/pub-seers-<slug>.json` | seer cursors, seen keys, poll times | `seers.py` | `seers.py` |
| `.seo-engine/state/pub-social-cache-<slug>.json` | SociaVault conversation signal cache (24h) | `score_suggestions.py` | itself |
| `.seo-engine/state/pub-geo-opportunities-<slug>.json` | GEO gaps (competitor named, client not) | `pub-monitor` | `score_suggestions.py` |
| `publications/<slug>/drafts/*.md` | auto-mode seer drafts with a brief | `seers.py` | `pub-research`, `pub-write` |

## How to interpret results

- **The breakdown is the point.** A high score with `geo` at 0 and `competitor` at 1 is a
  catch-up piece; one with `geo` high is a piece the assistants are already asking for and
  competitors are winning — usually the better bet.
- **Cannibalization drops are correct behavior**, not lost opportunities: write the update
  into the existing post (`pub-enhance`), do not add a second one.
- **`authority` pulls toward thin pillars on purpose** — an even topic map is what topical
  authority looks like; override with `--add` when a pillar should stay thin.
- **A seer event is a signal, not a mandate.** `suggest` mode is the default because most
  news deserves a paragraph in an existing piece, not an article.
- **Heuristic (no-LLM) maps are honest but shallow**; treat them as a starting list to prune.

## Safe to auto-apply vs. human review

- **Safe without asking:** building/refreshing the map, scoring, polling seers in `suggest`
  mode, `--mark-covered`.
- **Ask first:** switching a seer to `auto` (it creates drafts unattended), dismissing spokes
  in bulk, changing the signal weights in the script.

## Guardrails

- A spoke never becomes an article without a `brief` that names the reader benefit
  (red-flags §1, §7).
- Never propose a subject on the `avoid_topics` list or one that duplicates published work.
- SociaVault credits are spent only on the top candidates and cached; `--no-social` is
  always available.
- Seers never publish; the strictest thing they do is write a draft file.

## References

- [publication-playbook.md](../seo-references/publication-playbook.md) §4 (topic map and
  Curate contracts), §8 (the vendor's Curate/Seers capabilities mirrored here).
- [red-flags.md](../seo-references/red-flags.md) §1 (scaled content: the brief is the
  reader-benefit test), §7 (publication rules).
- [geo-playbook.md](../seo-references/geo-playbook.md) §5 (why cited statistics and
  specificity drive citation — the reason spokes carry an angle).
- [api-reference.md](../seo-references/api-reference.md) — SociaVault, Firecrawl search,
  DataForSEO, GitHub, Notion.

## Graceful degradation

Zero keys: heuristic topic map from competitor titles + priority topics, scoring without GEO/
SEO/social signals, seers limited to `github_*` (public API) and `spec_change`. LLM keys add
generated spokes and headlines; DataForSEO adds volume/difficulty; SociaVault adds the social
signal and `social_trend`; Firecrawl (or SociaVault) enables `news_trend`/`regulation_change`;
`NOTION_TOKEN` enables `notion_activity`. Every missing capability is named in `notes`.
