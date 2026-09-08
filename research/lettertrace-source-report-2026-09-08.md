# Lettertrace — Reverse-Engineering Report

Repo: `lettertrace` (Letterstory / The Letter Company), MIT licensed, BYOK "AI visibility" monitor.
Stack: Next.js 14 App Router, Supabase (Postgres + RLS), Vercel Cron, vitest. No `temperature` parameter is set anywhere in any provider call (verified by repo-wide grep) — every call runs at each provider's API default.

All source line numbers refer to files under the cloned repo root. The entire provider/LLM layer (adapters, gateway routing, prompt generation, sentiment analysis, competitor/topic suggestion) lives in **one file**: `lib/llm/index.ts` (1978 lines) — there is no `lib/llm/anthropic.ts`, `openai.ts`, `google.ts`, `perplexity.ts`, `gateway.ts`, `sources.ts`, or `analysis.ts`; only their `*.test.ts` files exist as separate files, all testing exports out of `index.ts`.

---

## 1. Prompt-variation generation

**Route:** `app/api/topics/[id]/generate/route.ts` → calls `generateVariations()` in `lib/llm/index.ts`.

### Flow (route.ts)
- Auth via Supabase session; loads the project and the topic (`topics` row scoped to `project_id`).
- `count` comes from request body (`{ count?: number }`), floored, clamped: `count = Math.max(1, Math.min(20, count))`, **default 8**.
- Resolves an API key via `resolveKey()` (lib/trial) — "lenient resolution on purpose: generated prompts are drafts the user edits, not measurements, so any key they hold will do" (own key, trial key, or fails with 400/402 if none/exhausted).
- Calls:
```ts
const { variations, tokens } = await generateVariations({
  provider: key.provider,
  model: key.model,
  apiKey: key.apiKey!,
  topicName: topic.name,
  topicDescription: topic.description,
  brandDescription: project.description,
  count,
});
```
- Inserts each variation as a `prompts` row: `{ project_id, topic_id, text: v.text, source: "ai", is_active: true, specificity: v.specificity }`.
- **No de-duplication against existing prompts in the topic.** There is no code path anywhere (route, `generateVariations`, or the DB schema) that checks a newly generated prompt's text against prompts already stored for that topic. The only "uniqueness" pressure is the system prompt's own instruction to generate "distinct" questions, and `.slice(0, opts.count)` to cap the count. (Contrast with `suggestFromSite`, which *is* told about `existingTopics` to avoid re-suggesting topics — but that's topic-level, not prompt-text-level, and only applies during re-analysis, not to this generate endpoint.)
- The manual single-prompt endpoint (`app/api/prompts/route.ts`, `POST`) likewise does no dedup — it just inserts whatever text is posted.

### `generateVariations()` (lib/llm/index.ts:1525-1592)

**Model used:** whatever `key.model`/`key.provider` resolved to (the project's `default_provider`/`default_model`, or the trial's default — see §7 for the model catalog). Not hardcoded to a specific model — it uses the same engine the project is configured to run.

**System prompt** (`VARIATION_SYSTEM`, lib/llm/index.ts:1505-1520), quoted verbatim:

```
You generate the questions a brand-monitoring tool will ask an AI assistant (ChatGPT, Claude) to discover which companies get named in answers about a topic.

A question is only useful if the answer to it names specific companies. Questions that read naturally but get answered with explanation instead of names measure nothing. That is the most common failure and the one to avoid.

Rules:
- At least two thirds of the questions must explicitly demand named companies. Shapes that work: "List the top 5 companies that…", "Name the specific vendors that…", "Rank the leading providers of… by name", "Which companies sell…? Just the company names." Use the words "companies", "vendors", or "providers", and ask for them by name.
- Never ask for "a shortlist" or for how to choose/evaluate. Both get answered with advice about making a decision rather than with the options themselves.
- Keep the remaining questions in a buyer's own words ("What's the best X for Y?", "Who are the main players in X?") so the set reflects real usage, but keep them the minority.
- Do NOT name any specific brand in the questions unless the brand is part of the topic itself.
- Vary buyer intent and seniority, not just the wording.
- Spread the questions across a specificity ladder and label each one:
  "general" = the broad category question anyone might ask ("List the top 5 payroll companies by name.")
  "mid" = qualified by a segment or use case ("Which providers handle payroll for a 20-person startup? Just company names.")
  "niche" = a specific buyer situation, narrow enough that smaller or newer companies can realistically be named ("Name payroll vendors that support contractor payouts to Brazil for a seed-stage startup.")
  Aim for a roughly even mix of the three tiers. The named-companies rule applies at every tier.
- Return ONLY a JSON array of objects shaped {"question": string, "specificity": "general" | "mid" | "niche"}. No commentary.
```

For non-Anthropic wire shapes, the system prompt is amended (still the same rules, different output-format hint), because OpenAI-compatible `response_format: json_object` can't return a bare array:
```ts
const system =
  shape === "anthropic"
    ? VARIATION_SYSTEM
    : shape === "openai-chat" || shape === "openai-responses"
      ? VARIATION_SYSTEM +
        '\nReturn a JSON object shaped { "questions": [{ "question": string, "specificity": string }] }.'
      : VARIATION_SYSTEM + "\nReturn a JSON array of the objects described above.";
```

**User prompt template** (verbatim, with interpolation points shown as they appear in source):

```
Topic: ${opts.topicName}${opts.topicDescription ? `\nContext: ${opts.topicDescription}` : ""}${opts.brandDescription ? `\nThe company being monitored (context only — NEVER name it in the questions): ${opts.brandDescription}` : ""}

Generate ${opts.count} distinct questions a person might ask an AI assistant related to this topic. Return a JSON array of ${opts.count} strings.
```

Note the mismatch: the user message says "Return a JSON array of ${count} strings," but the system prompt demands `{question, specificity}` objects — the parser (below) tolerates both shapes.

**"Intent categories/personas/formats" actually enforced:**
- **No explicit persona field.** The only structured taxonomy captured in the output schema is `specificity: "general" | "mid" | "niche"` (the "specificity ladder"). "Buyer intent and seniority" is mentioned only as a prose instruction ("Vary buyer intent and seniority, not just the wording") — it is never captured as a field, never validated, and not stored anywhere.
- **Format enforcement:** "at least two thirds... must explicitly demand named companies," using specific phrasings ("List the top 5 companies...", "Name the specific vendors...", "Rank the leading providers... by name", "Which companies sell...? Just the company names"); explicitly bans "a shortlist" and "how to choose/evaluate" phrasings.
- **Brand-naming constraint:** never name the monitored brand in the question, unless the brand is literally the topic.

**Output parsing** (lib/llm/index.ts:1563-1591):
- `extractJson<T>()` strips markdown code fences, and clips to the outermost `[`/`{` ... `]`/`}` before `JSON.parse`.
- If the parsed value is a bare object (not array), it's unwrapped via `.questions ?? []`.
- Tolerates a **pre-ladder shape** — bare strings — mapped to `{ text, specificity: null }`.
- Objects are mapped `{ question, specificity }` → `{ text, specificity }`, where `specificity` is validated against `SPECIFICITY_VALUES = new Set(["general", "mid", "niche"])`, else `null`.
- Final `.slice(0, opts.count)` — a model that over-produces is truncated, not resampled or rejected.
- **Count is never validated as met** — if the model returns fewer than `count` (or zero), the route returns whatever came back; zero variations returns a 400 ("The model returned no variations, try again.").

---

## 2. `docs/prompt-playbook.md` — full summary

This is the team's own internal methodology doc, based on live runs (2026-07-26/27) against two real clients: **Cloudflare** (huge/established) and **Runlayer** (MCP-security startup, out of stealth Dec 2025) — ~110 queries against Claude Opus 4.8 and GPT-4o with web search on, ~$15 spend.

**The one rule:** *"A monitored prompt only measures something if the answer names companies."* Measured company-names-per-answer by prompt shape:

| Prompt shape | Companies named/answer | Client hit rate |
|---|---|---|
| "List the top 5 companies…" / "Rank the leading vendors by name" | 3.7 | 50% |
| "Who are the main players in X?" | 2.5 | 0% |
| "Give me a shortlist with names" | 0.8 | 0% |
| "How do I…" / "best X for Y" / "which vendors offer X" | ~0.1 | 0% |

"Give me a shortlist" is flagged as the sharpest trap — it *sounds* like a request for names but reliably returns decision-making advice.

**Recommended prompt shapes** (write like): `List the top 5 companies selling <category>...`, `Name the specific vendors that sell <product>. Just the company names.`, `Rank the leading <category> providers by name.`, `Which companies provide <capability>? Just the company names.`

**Avoid:** how-to questions, "best X for Y", "which vendors offer X" (surprisingly still no names), "give me a shortlist", "how should I evaluate X".

States plainly: *"Lettertrace's generator was rewritten to follow this (`VARIATION_SYSTEM` in `lib/llm/index.ts`)"* — i.e., §1 above is the direct codification of this doc.

**Cloudflare vs. Runlayer results:** Cloudflare hit 19/20 (95%) — "hits on anything," which the doc says proves nothing about configuration quality because a high-authority brand looks good regardless of prompt shape. Runlayer hit only 1/20 (5%) in the first pilot despite web search running on 19/20 queries — "the models went and looked, and still didn't name them." Across 66 total Runlayer queries in every experiment, named only 4 times (~6%).

**Three controlled experiments documented in full** (every prompt + hit/miss verbatim), showing:
- Exp 1 (naming the protocol/tools/framing): **0 for 24** — specificity doesn't help at all.
- Exp 2 (demanding a list vs. shortlist vs. "who are the players"): explicit-list tier hit 3/6 vs. 0/10 everywhere else; the doc computes **Fisher's exact test p≈0.04**, calling it "strong enough to write prompts by, not strong enough for a client deck without a confirmatory run."
- Exp 3 (rewritten generator's actual output on a bare topic string): 3.0 companies named/answer, up from ~0.1, even though Runlayer itself still didn't appear — reframed as "competitive intelligence" rather than a wasted run.

**Reading a result** — a decision table distinguishing three causes of a 0% mention rate: prompts wrong shape (low `informativeRate`) vs. too little data (wide CI) vs. a real competitive gap (`informativeRate` high, tight CI). This maps directly onto `measurementVerdict()` in `lib/metrics.ts` (§5).

**Two currencies: named vs. cited** — being named in prose and being cited as a source are separate, uncorrelated events (a how-to question cited runlayer.com while naming nobody; Cloudflare was named 6/6 but cited only 1/6). Says this is the leading indicator for young brands.

**Don't trust auto-suggested competitors** — for Runlayer, the app's `suggestCompetitors` proposed Portkey, Cloudflare AI Gateway, Lasso Security, Prompt Security, Zenity, Witness AI, Nightfall AI — but the companies that actually dominated the category in live answers (MintMCP: 10 mentions, TrueFoundry: 9) were never suggested; only Lasso appeared on both lists. Conclusion: "run once, read the answers, then set the competitor list from who actually appeared."

**Onboarding checklist** (7 steps): set every brand domain; write prompts that demand named companies; run once with placeholder competitors then correct the list; check `informativeRate` before trusting mention rate; set `replicates` ≥3 for low-authority clients; track citations not just mentions; expect months, poll `firstMentionAt`.

**Reproduction:** `scripts/pilot-client.ts` runs the full pipeline against a live brand without writing to the DB (`npx tsx scripts/pilot-client.ts <key> --max-prompts 10 --providers anthropic,openai`); a 40-query two-client pilot cost ~$3.80.

Closing caveat: numbers are "from a single week of runs against two clients... re-measure before treating any specific percentage as durable."

---

## 3. Mention detection — `lib/mentions.ts`

**Regex construction** (`buildRegex`, lines 16-28):
```ts
function buildRegex(terms: string[]): RegExp | null {
  const cleaned = terms
    .map((t) => t.trim())
    .filter((t) => t.length >= 2)
    .map(escapeRegex);
  if (cleaned.length === 0) return null;
  cleaned.sort((a, b) => b.length - a.length);
  const pattern = `(?<![A-Za-z0-9])(?:${cleaned.join("|")})(?![A-Za-z0-9])`;
  return new RegExp(pattern, "gi");
}
```
- Terms shorter than 2 chars are dropped.
- Terms sorted **longest-first** so multi-word aliases match before fragments.
- "Word boundary" is a custom negative lookbehind/lookahead on `[A-Za-z0-9]` (not `\b`), deliberately chosen because it still works when the term itself contains punctuation (e.g. "Notion.so") — `\b` would misbehave there.
- Case-insensitive, global (`gi`).

**Aliases:** `brandTerms(brandName, aliases) = [brandName, ...aliases]` — **domain labels are explicitly never added as terms.** The file documents a real incident: adding a domain-derived label (e.g. "you" from you.com) caused you.com to read a ~100% mention rate off the pronoun "you" in ordinary prose; also broke on "monday"/"zoom"/"slack"/"box". Measured before removing it: across 22 projects / 1000 stored answers, the domain-label heuristic was the *sole* cause of a detection in only 2 answers total (one alias case — "OpenHands" vs. "Open Hands"). Documented trade-off: "An inflated mention rate is the failure this product exists to prevent... a missed spelling shows up as a zero the owner goes looking into. Given a choice of error, take the visible one."

**Link-surface stripping** (`stripLinkSurfaces`, lines 39-45, and `markdownLink`/`isAddress`, lines 67-89) — run before matching:
- Markdown links `[label](target)`: the **label is kept as prose** (a brand name that's always rendered as a ranked-list link must still count as named) **unless the label itself reads as an address** (`isAddress`: starts with `https?://`/`www.`, or matches `/^[\w-]+(?:\.[\w-]+)+(?:\/\S*)?$/` — i.e. `vercel.com` or `vercel.com/docs`), in which case the whole link is blanked (a citation, not a naming).
- Bare URLs (`\bhttps?:\/\/[^\s<>"')\]]+`) and scheme-less `www.` hosts are always blanked.
- All blanking is **length-preserving** (replaced with spaces of equal length) so `firstPosition` offsets computed on the transformed text remain valid against the original.

**Detection** (`detectMention`, lines 91-113):
```ts
export function detectMention(text: string, terms: string[]): MentionHit {
  const absent: MentionHit = { mentioned: false, count: 0, firstPosition: -1 };
  if (!text) return absent;
  const re = buildRegex(terms);
  if (!re) return absent;
  text = stripLinkSurfaces(text);
  let count = 0;
  let firstIndex = -1;
  const matches = Array.from(text.matchAll(re));
  for (const match of matches) {
    count++;
    if (firstIndex === -1) firstIndex = match.index ?? -1;
  }
  if (count === 0) return absent;
  const len = Math.max(text.length, 1);
  return {
    mentioned: true,
    count,
    firstPosition: firstIndex >= 0 ? Math.min(firstIndex / len, 1) : 0,
  };
}
```
- **Count** = total regex matches after link-stripping (URL/link-target occurrences are excluded; a brand named once in prose next to a link to its own site counts as `count: 1`, not more).
- **Prominence / "first position"** = `firstIndex / textLength`, a **normalized 0..1 value where 0 = start of the answer**. This is *not* itself "prominence" — `firstPosition` is inverted downstream in `lib/metrics.ts`: `avgProminence = 1 - first_position`, so prominence is high when the mention is early. Absent → `firstPosition: -1`.

**Edge cases explicitly handled (each with a test in `lib/mentions.test.ts`):**
- Brand name inside a markdown link *target only* (not the visible label) → citation, not a mention.
- Prose naming next to a URL still counts (`count` unaffected by the URL text).
- Brands whose *name itself* is a domain (`You.com`) still match in prose.
- A brand whose name is an ordinary English word (`Zoom`, `Monday`) will still false-positive on that word in prose — documented as a known, accepted limit ("cannot save a brand whose own name is an ordinary word").
- Aliases can cover spelling variants an exact name misses (`"Open Hands"` + alias `"OpenHands"`).
- Markdown link labels with surrounding prose (`"[Vercel — the hosting platform](...)"`) still count as prose (whole label kept, since it isn't purely an address).
- Empty markdown label (`[]( url )`) handled without shifting offsets.

---

## 4. LLM enrichment (sentiment + recommendation) — inside `lib/llm/index.ts` (there is no separate `analysis.ts`)

**System prompt** (`ANALYZE_SYSTEM`, line 1605-1608), verbatim:
```
You analyze how brands are portrayed inside an AI assistant's answer. For each entity you are given, decide:
- sentiment: how the answer talks about it, "positive", "neutral", or "negative".
- recommended: true if the answer actively recommends / suggests / endorses it, otherwise false.
Only judge based on the provided answer text. Return ONLY JSON.
```

**Scale:** sentiment is a **3-point categorical scale** — `"positive" | "neutral" | "negative"` — no numeric scale, no intensity. `recommended` is a separate boolean, not derived from sentiment (a brand can be sentiment-neutral yet `recommended: true`, or vice versa).

**User prompt template** (`analyzeResponse`, lines 1683-1694), verbatim:
```
QUESTION ASKED:
${opts.question}

AI ASSISTANT ANSWER:
"""
${opts.responseText.slice(0, 6000)}
"""

ENTITIES TO JUDGE:
${entityList}

Return a JSON object: { "results": [ { "key": "<key>", "sentiment": "positive|neutral|negative", "recommended": true|false } ] } with one entry per entity.
```
where `entityList` is built as: `` `- key="${e.key}" name="${e.name}"` `` joined by newlines. The answer text is truncated to the first 6000 characters.

**Output schema:** `{ "results": [ { "key": string, "sentiment": "positive"|"neutral"|"negative", "recommended": boolean } ] }`.

**Model used:** always the provider's **cheap/fast model**, regardless of which model answered the question — `analysisModelFor(provider)` (lib/models.ts:167-189):
```ts
const ANALYSIS_MODEL_DEFAULT: Record<Provider, string> = {
  anthropic: "claude-haiku-4-5",
  openai: "gpt-4o-mini",
  google: "gemini-flash-lite-latest",
  perplexity: "sonar",
};
```
overridable per-provider via env vars `ANALYSIS_ANTHROPIC_MODEL` / `ANALYSIS_OPENAI_MODEL` / `ANALYSIS_GOOGLE_MODEL` / `ANALYSIS_PERPLEXITY_MODEL`. Called with `maxTokens=700`, `json=true`, and only ever for entities *already detected* as mentioned by `detectMention` (never runs on non-mentioned entities — "saves tokens; an entity not in the text has no sentiment").

**`parseAnalysis()` — key/name resolution** (lines 1622-1663): this is the load-bearing correctness fix in this module. Different providers echo different identifiers back — Claude returns the supplied `key`, but gpt-4o-mini "routinely returns the entity's *name* instead" (e.g. `"Cloudflare"` rather than `"brand"`). The parser builds two lookup maps (`byKey`, `byName`, both lower-cased/trimmed), and for each raw result row tries `[o.key, o.name, o.entity]` in order against `byKey` then `byName`; **key match always wins over name match** if both a key and a name in the entity set collide with the same string. Rows matching neither are **dropped, not guessed**. Duplicate rows for the same entity: only the first is kept (`seen` Set). Unrecognized `sentiment` values silently default to `"neutral"`; `recommended` is coerced with `Boolean(...)`.

**Failure handling:** wrapped in try/catch — "Sentiment is best-effort enrichment; never fail a run over it" — on any exception, every entity defaults to `{ sentiment: "neutral", recommended: false }` with `tokens: 0`.

---

## 5. Metrics — `lib/metrics.ts` (exact formulas)

**Wilson score interval** (`wilsonInterval`, lines 25-37) — used everywhere a rate is reported, specifically chosen over a normal approximation because it doesn't degenerate at 0 successes or small n:
```ts
export function wilsonInterval(successes: number, trials: number, z = 1.96): Interval {
  if (trials <= 0) return { low: 0, high: 1 };
  const hits = Math.min(Math.max(successes, 0), trials);
  const p = hits / trials;
  const z2 = z * z;
  const denominator = 1 + z2 / trials;
  const centre = p + z2 / (2 * trials);
  const margin = z * Math.sqrt((p * (1 - p)) / trials + z2 / (4 * trials * trials));
  return {
    low: Math.max(0, (centre - margin) / denominator),
    high: Math.min(1, (centre + margin) / denominator),
  };
}
```
z defaults to 1.96 (95% CI). Test-file expected values (`lib/metrics.test.ts`): `wilsonInterval(0,1).high > 0.7` (a single zero could plausibly be a common mention) vs. `wilsonInterval(0,30).high < 0.15` (looks genuinely absent); `wilsonInterval(0,0) === {low:0, high:1}` (empty sample ⇒ full uncertainty, no divide-by-zero).

**Entity stats** (`computeEntityStats`, lines 65-143) — grouped by `entityKey(m) = m.entity_type === "brand" ? "brand" : (m.competitor_id ?? m.entity_name)`:
- `responsesMentioned` = distinct `response_id` count for the entity.
- `mentionRate = responsesMentioned / totalResponses`.
- `totalMentionCount` = sum of `mention_count` across rows (raw occurrence count, not response-deduped).
- **`shareOfVoice` = `totalMentionCount(entity) / grandTotalMentions`**, where `grandTotalMentions = sum of mention_count over ALL mention rows in the run` (across every entity). I.e. share of voice is computed on raw mention counts, not on distinct-response mention rates.
- **`avgProminence`** = mean of `(1 - first_position)` over rows where `first_position >= 0`; i.e. `firstPosition` from `lib/mentions.ts` (0 = very start of text) is inverted so **higher `avgProminence` = earlier/more prominent**. Rows with no valid position are excluded from the average (not treated as 0).
- `recommendRate = recommended-row-count / responsesMentioned` (rate **among mentioned** responses, not among all responses).
- `sentiment = {positive, neutral, negative}` counts; **`sentimentScore = (positive - negative) / (positive + neutral + negative)`**, range -1..1, 0 if nothing judged.
- **Synthetic zero-row:** if `brandName` is passed and no brand row exists in the mention data (brand never mentioned), a zero-valued brand `EntityStat` is synthesized (with a real Wilson interval on 0/`totalResponses`) so the brand never silently disappears from a report exactly when its absence is the finding.
- Sort: brand always first, then competitors descending by `shareOfVoice`.

**Run summary** (`computeRunSummary`, lines 157-174): thin wrapper pulling the brand row's `mentionRate`/`mentionRateInterval`/`shareOfVoice`/`sentimentScore`/`avgProminence` out of `computeEntityStats`, defaulting to a zero/`wilsonInterval(0, totalResponses)` when absent.

**Citation stats** (`computeCitationStats`, lines 197-211): `ownedCitationRate = responsesWithOwnedSource / totalResponses` where `responsesWithOwnedSource` is the **distinct-response** count of sources flagged `is_owned` (multiple owned citations in one answer count once); `distinctOwnedUrls` = distinct URL count among owned sources.

**Measurement quality** (`computeMeasurementQuality`, lines 236-249): `informativeRate = responsesNamingSomeone / totalResponses`, where "naming someone" = distinct `response_id`s that have *any* mention row at all (brand or competitor) — i.e. answers that failed to name any tracked entity are "uninformative," not "misses." `LOW_INFORMATIVE_RATE = 0.5` is the floor constant.

**Measurement verdict** (`measurementVerdict`, lines 274-296) — a 5-state classifier: `"no-data" | "no-competitors" | "thin-sample" | "real-gap" | "healthy"`:
```ts
if (input.totalResponses === 0) return "no-data";
if (input.competitorsTracked === 0) return "no-competitors";
const thin =
  input.informativeBasis && input.informativeBasis > 0
    ? wilsonInterval(Math.round(input.informativeRate * input.informativeBasis), input.informativeBasis).high < LOW_INFORMATIVE_RATE
    : input.informativeRate < LOW_INFORMATIVE_RATE;
if (thin) return "thin-sample";
if (!input.brandMentioned) return "real-gap";
return "healthy";
```
When `informativeBasis` (sample size behind the rate) is supplied, "thin" is decided by the **Wilson upper bound** of informativeRate falling under 0.5 (interval-aware — a 0.47 point-rate on n=30 can still resolve "real-gap" if the upper CI clears 0.5); without a basis it falls back to a naive point-rate comparison (for backward compatibility with old reports).

**Per-URL citation rate** (`computePageStats`, `pageKey`): `pageKey(url)` reduces a URL to `host+path`, dropping scheme/`www`/query/fragment/trailing-slash, path lowercased (deliberately, favoring recall over RFC 3986 correctness). `citedRate = responsesCiting / totalResponses` scoped to prompts carrying a `target_url`.

**Per-topic** (`computeTopicStats`): brand-only mention rate scoped by `topic_id`.

**Per-prompt entity breakdown** (`computePromptEntityStats`): re-runs `computeEntityStats` scoped to each prompt's own responses; sorted by the top competitor's mention rate descending (the "questions competitors win that we don't" queue).

**Per-prompt competitor citations** (`computeCompetitorCitations`, `hostKey`): matches cited source hosts against competitor domains including subdomains (`host === c.host || host.endsWith('.' + c.host)`), counting **distinct responses** citing each competitor's domain per prompt.

**Trends across runs:** there is no separate "trend" computation function in `lib/metrics.ts` — the file only computes statistics *within* one run's data (or one call's worth of rows). Trend-over-time is assembled by callers: the CLI's `history <project>` command / `GET /v1/projects/:id/history` (in `lib/api-service.ts`, not shown in full here) fetches a series of runs and reports each run's point (`brandMentionRate`, `ownedCitationRate`, `createdAt`, `model`) plus `firstMentionAt`/`everMentioned` flags — i.e. "trend" = a client-assembled sequence of per-run `RunSummary`/`CitationStat` snapshots, not a statistical trend model (no smoothing/regression).

**Test-asserted expected values** (`lib/metrics.test.ts`, selected):
- `wilsonInterval(0,1)`: low 0, high > 0.7. `wilsonInterval(0,30)`: low 0, high < 0.15.
- Zero-mention brand row test: 12 responses, 0 brand mentions ⇒ `mentionRate === 0`, `mentionRateInterval.high < 0.3`.
- `computeRunSummary([mention()], 8, "Acme")` ⇒ `brandMentionRate ≈ 0.125` (1/8).
- `computeCitationStats`: two owned citations in one response ⇒ counted once (`responsesWithOwnedSource: 1`), but `distinctOwnedUrls: 2`.
- `measurementVerdict`: `informativeRate: 0.47, informativeBasis: 30` ⇒ `"real-gap"` (Wilson upper ~0.64 clears 0.5); `informativeRate: 0.2, informativeBasis: 30` ⇒ `"thin-sample"` (Wilson upper ~0.36); without a basis, `0.47` alone ⇒ `"thin-sample"` (point-rate-only fallback).
- `pageKey("https://www.acme.io/Blog/Best-CRM/?utm_source=openai#top") === "acme.io/blog/best-crm"`.
- `hostKey("BLOG.Acme.com") === "blog.acme.com"`.

---

## 6. Engine / run orchestration — `lib/engine.ts`

**Concurrency:** `CONCURRENCY = 8` (comment: "Low enough to stay under provider rate limits, high enough that a full-size run finishes inside the 300s invocation ceiling: 60 answers with web search on a slow engine run ~20s each, and at 4-wide that exact workload was killed at the cap three times... 8-wide it clears the ceiling with half left over.") Implemented via a hand-rolled `mapPool()` (lines 73-88) — a fixed pool of `min(limit, items.length)` async workers pulling from a shared cursor, not a library.

**Retries:** retry logic lives per-provider-adapter in `lib/llm/index.ts`, not in the engine loop itself:
- Anthropic/OpenAI SDK clients: `CLIENT_OPTS = { maxRetries: 4, timeout: 60_000, fetch: globalThis.fetch }` (routed through `globalThis.fetch`/undici rather than the SDKs' default node-fetch, because node-fetch throws "Premature close" on some gateways' large grounded responses).
- Google: custom retry loop, `GOOGLE_MAX_ATTEMPTS = 4`, retryable statuses `{429,500,503,504}`, honors the provider's own `RetryInfo.retryDelay` (capped at `GOOGLE_MAX_RETRY_WAIT_MS = 45_000`ms per wait, `GOOGLE_RETRY_BUDGET_MS = 90_000`ms total sleep budget per call).
- Perplexity: same shape, `PERPLEXITY_MAX_ATTEMPTS = 4`, retryable `{429,500,502,503,504}`, honors `Retry-After` header, same 45s/90s caps.
- OpenAI's Responses (web-search) path retries only 5xx, up to 3 attempts, and deliberately does **not** retry a deterministic "incomplete"/empty-answer failure, since a single grounded gpt-5.6 call can already cost 30-60k tokens — retrying a guaranteed-to-fail call would re-bill it for nothing.
- At the **engine level**, a single job's failure never aborts the run: caught per-job in `mapPool`, recorded as `hardError` (first error only becomes the run's stored error message) and via `recordOpsError`; the run is marked `"failed"` only if **zero** answers were stored, `"completed"` otherwise.

**Per-model:** one `(provider, model)` pair per run — set once at `prepareRun`/`executeRun` call time (from the project's configured engine or the caller's override); every job in the run uses that same pair. There's no per-prompt model switching within a run.

**Replicates (sampling repetition):** `replicates = Math.min(Math.max(Math.trunc(project.replicates ?? 1), 1), 10)` (clamped 1-10, project-level setting, DB `check (replicates between 1 and 10)`, default 1). `jobs = prompts.flatMap(p => Array.from({length: replicates}, () => p))` — i.e. each active prompt is literally duplicated `replicates` times into the job list, and each duplicate becomes its own independent `responses` row / mention detection pass. This is how the product gets multiple *independent samples* per question (used for the Wilson-interval confidence math in §5) rather than any explicit statistical sampling parameter.

**Web search on/off:** `project.use_web_search` (boolean, DB default `true`) is passed straight through to `runQuery({..., webSearch: project.use_web_search})`. Provider-specific behavior:
- Anthropic/OpenAI: web search is **forced** via `tool_choice` when the project has it on (not merely offered) — see §7.
- Google: `webSearch` toggles grounding for a plain Gemini model; the `"google-ai-overviews"` pseudo-model *always* grounds regardless of the toggle.
- Perplexity: always grounded; ignores the toggle entirely (its API isn't offered ungrounded for monitored runs since "an ungrounded Sonar answer doesn't correspond to anything a real user of Perplexity ever sees").

**Source attribution capture (fields + "own site as source" detection):**
- `sources` table columns: `response_id, run_id, project_id, url, domain, title, snippet, is_owned`.
- `is_owned` is computed in `engine.ts` at insert time: `ownedHosts.some(h => isOwnedDomain(s.domain, h))`, where `ownedHosts = project.brand_domains.map(hostOf).filter(Boolean)` (every domain the brand owns, not just the primary) and:
```ts
export function isOwnedDomain(sourceDomain: string, ownedHost: string): boolean {
  if (!ownedHost || !sourceDomain) return false;
  return sourceDomain === ownedHost || sourceDomain.endsWith(`.${ownedHost}`);
}
```
  i.e. exact host match or subdomain match.
- **Sources come from two places, merged and deduped:** (1) the provider's own structured citation list (`sources` returned by `runQuery`), and (2) `extractInlineLinks(answer)` — a regex scan (`\bhttps?:\/\/[^\s<>"')\]]+`) over the raw answer text for markdown/bare links the provider didn't repeat in its structured citation list ("ChatGPT especially" is called out as under-reporting structured citations for inline markdown links). Inline links are deduped against structured ones by `pageKey` (host+path) before insert, both get `is_owned` computed the same way.
- **"Own site used as source even when not named" detection** — this is exactly `is_owned`: a source row can be `is_owned: true` on a response where `detectMention()` (the brand-name text scan) found **zero** brand mentions in the prose. `lib/metrics.ts`'s `computeCitationStats` explicitly treats this as a separate, earlier-arriving signal from prose mentions ("a how-to question cited runlayer.com as a source while naming nobody at all"). There is no other/implicit mechanism — it's purely: source domain (or subdomain) === a `brand_domains` entry.

**Run lifecycle / abandonment handling:** `prepareRun()` creates the `runs` row (`status: "running"`) and logs `run.started` before any prompts execute (so a client doesn't have to hold an HTTP connection for minutes); `resumeRun()`/`resumeRunMeasured()` actually executes the job pool and settles the row. `ABANDONED_RUN_MS = 20 * 60 * 1000` (20 min) — comfortably above the 800s/13.3min `maxDuration` any route can run for — is the threshold past which a `"running"` row is presumed to belong to a dead invocation; `sweepAbandonedRuns()` (called at the top of every cron tick) finds and force-fails such rows with a shared message (`INTERRUPTED_RUN_ERROR`), guarded by `.eq("status", "running")` so it can't race a run that's legitimately still executing.

**Budget ceiling:** `budgetMicros` (only set for operator/trial-funded runs, never for BYOK) is checked *between* jobs, not up front (`overBudget()` called at the top of each job's closure) — in-flight jobs already dispatched are allowed to finish and are kept ("a stored answer is real data, and throwing it away would waste money we have already spent"); the run is marked with `budgetStopped: true` and a `budgetNote` explaining the shortfall, not treated as a failure.

**Progress reporting:** `runs.completed_count` is checkpointed every `PROGRESS_EVERY = 4` processed jobs (or on the final job), not on every single job, to avoid hammering the DB.

---

## 7. Provider adapters (`lib/llm/index.ts`)

### Anthropic
- **Model IDs offered** (`lib/models.ts`): `claude-opus-4-8` (default/most capable), `claude-sonnet-5`, `claude-sonnet-4-6` (balanced), `claude-haiku-4-5` (fast/cheap, and the analysis-model default).
- **Plain chat:** `anthropicChat()` — `client.messages.create({ model, max_tokens: ANSWER_MAX_TOKENS=1200 (UTILITY_MAX_TOKENS=1500 for utility calls), system?, messages: [{role:"user", content}] })`, text extracted by filtering `content` blocks to `type === "text"` and joining.
- **Web search enablement (`anthropicWebSearch`, lines 694-766):** forced via a server-side tool:
```ts
tools: [{ type: "web_search_20250305", name: "web_search", max_uses: WEB_SEARCH_MAX_USES /* = 5 */ }],
tool_choice: { type: "tool", name: "web_search" },
```
  Explicitly pinned to the **older** `web_search_20250305` tool version rather than `web_search_20260209`, because the newer one "runs dynamic filtering through code execution and returns results in a shape this parser doesn't read: measured... it produced 0 inline citations (vs 11) for 2.6x the tokens."
- **Source/citation extraction:** reads `content` blocks structurally (not via SDK types, since the shapes are newer than the pinned SDK version): `type: "text"` blocks carry `citations: [{url, title, cited_text}]` (the *cited* sources — primary signal); `type: "web_search_tool_result"` blocks carry `content: [{url, title}]` (*retrieved-but-maybe-uncited* — fallback only). Final `sources = dedupeSources(cited.length > 0 ? cited : retrieved)` — prefer what the model actually cited inline, fall back to raw search results only if it searched but cited nothing.
- **Verify-key probe model:** `claude-haiku-4-5`.

### OpenAI
- **Model IDs offered:** `gpt-4o` (default, "legacy flagship," kept first for measurement continuity), `gpt-5.6-sol` ("ChatGPT's paid default"), `gpt-5.6-luna` ("ChatGPT's free default"), `gpt-4o-mini` (fast/cheap, analysis-model default), `gpt-4-turbo`.
- **Plain chat:** `openaiChat()` via `chat.completions.create`, using `max_completion_tokens` (not `max_tokens` — gpt-5.6 rejects `max_tokens` with a 400).
- **Web search enablement (`openaiWebSearch`, lines 786-935):** raw `fetch` to the **Responses API** (`/v1/responses`), not the SDK, specifically to read fields (`web_search_call.action.sources`) the SDK types don't expose. Forced via:
```ts
tools: [{ type: "web_search_preview" }],
tool_choice: { type: "web_search_preview" },
include: ["web_search_call.action.sources"],
max_output_tokens: OPENAI_SEARCH_MAX_OUTPUT_TOKENS /* = 8000 */,
```
  `max_output_tokens` is raised to 8000 (vs. 1200 for plain answers) because gpt-5.6's reasoning + search both draw from the same output budget as the visible answer; 1200 was measured to fail 4/4 real grounded prompts with `status: "incomplete"`.
- **Source extraction:** prefers inline `url_citation` annotations attached to `content` items (`cited`); falls back to `action.sources` on the `web_search_call` item (`searched`) when the model browsed but attached zero inline citations — measured to happen "~30% of the time" on gpt-5.6. `sources = dedupeSources(cited.length > 0 ? cited : searched)`.
- **Failure semantics:** an `"incomplete"` status or empty text throws rather than storing a truncated/partial answer (same rationale as Gemini's `MAX_TOKENS` guard below).
- **Verify-key probe model:** `gpt-4o-mini`.

### Google (Gemini + AI Overviews)
- **Model IDs offered:** `gemini-pro-latest`, `gemini-flash-latest` (also the AI-Overviews backing model), `gemini-flash-lite-latest` (analysis default), plus the pseudo-model `google-ai-overviews` (`GOOGLE_AI_OVERVIEWS_MODEL`). Deliberately **rolling aliases, not pinned dated versions** — the pinned 2.5 ids the project originally shipped with were rejected as "no longer available to new users" on a fresh project.
- **AI Overviews is not a separate model** — it's the `gemini-flash-latest` model (`AI_OVERVIEWS_BACKING_MODEL`) called with a synthetic system prompt (`AI_OVERVIEW_SYSTEM`, quoted below) and forced grounding, exposed in the catalog/UI as a distinct answer engine.
- **Transport:** raw `fetch` against `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` — no SDK.
- **Web search enablement:** `body.tools = [{ google_search: {} }]` when `grounding` is requested — but *offering* the tool alone doesn't force use (measured: 0/2 grounded on a memory-answerable question without the extra instruction, 2/2 with it), so grounding is additionally **pushed by system-prompt instruction**:
```
- ALWAYS search the web before answering, even if you believe you already know the answer. Your answer must reflect current search results, not memory.
```
  (`ALWAYS_SEARCH`, line 1222-1223.)
- **AI_OVERVIEW_SYSTEM** (full system prompt for the `google-ai-overviews` engine, lines 1225-1230, verbatim):
```
You are Google's AI Overview, the AI-generated summary shown at the top of a Google Search results page. Given the user's search query, write the overview Google would surface.
- Answer directly and immediately. No preamble, no "as an AI", no restating the question.
- Synthesize current information from the web. Name the specific brands, products, tools, companies, or sources that are genuinely relevant to the query.
- Keep it tight: a short paragraph or two, or a brief bulleted list, the way an AI Overview reads.
- Neutral, informational tone.
- ALWAYS search the web before answering, even if you believe you already know the answer. Your answer must reflect current search results, not memory.
```
- **Source extraction (`googleGroundingSources`, lines 1193-1213):** Gemini's `groundingMetadata.groundingChunks[].web` gives `{uri, title}` where `uri` is always a Google redirect host (`vertexaisearch.cloud.google.com`) and `title` is actually the real source **domain** (e.g. `"uefa.com"`) — the code takes the URL from `uri` (kept clickable) but the attribution `domain` from `title` via `domainFromTitle()` (regex-validates it looks like a hostname). If `title` doesn't parse as a hostname *and* the raw URL's own host is the redirect host, the chunk is dropped entirely rather than mis-attributed to Google's own redirect domain ("a wrong domain is worse than a missing row").
- **Special failure handling:** Gemini "thinking" tokens are billed as output and draw from the same budget as the visible answer; `GOOGLE_THINKING_HEADROOM = 4096` floors `maxOutputTokens`; a response with `finishReason: "MAX_TOKENS"` is **thrown as an error**, not stored, because the surviving text can be "mid-sentence deliberation" rather than an answer (measured: 46 answer tokens survived after 1150 thinking tokens on a 1200 budget). JSON-mode + Search-grounding combined silently returns a candidate-less 200 (billed, no error) — the code documents this and never combines them.
- **Verify-key probe model:** `gemini-flash-lite-latest`.

### Perplexity (Sonar)
- **Model IDs offered:** `sonar-pro` (most capable), `sonar` (fast/cheap, analysis default), `sonar-reasoning-pro` (chain-of-thought). `sonar-deep-research` deliberately excluded — it runs for minutes per question, exceeding the 300s/run route ceiling.
- **Transport:** raw `fetch` to `https://api.perplexity.ai/v1/sonar` (not the OpenAI-compatible `/chat/completions` alias, specifically to get `search_results`/`citations` fields untyped by the OpenAI SDK).
- **Web search enablement:** always on for monitored `runQuery` calls (`perplexityRunQuery` never passes `disable_search`); utility calls (`perplexityChat`) always pass `disable_search: true` so classification/suggestion work never spends on live search or lets a search result "contaminate" a judgment about supplied text.
- **Source extraction (`perplexitySources`):** prefers `search_results[]` (`{url, title, snippet}` — the richer, newer field); falls back to bare `citations: string[]` only if `search_results` is empty/absent (older API responses).
- **Reasoning-model output cleanup:** `sonar-reasoning-pro` emits chain-of-thought inline wrapped in `<think>...</think>` ahead of the real answer; `stripReasoning()` strips it via `/<think>[\s\S]*?<\/think>/gi` before the text is stored — otherwise the model's own musing about competitors ("the user might be thinking of Cloudflare") would be scanned as a mention the answer never actually made.
- **Token accounting quirk:** `citation_tokens` and `reasoning_tokens` are billed on top of, and not included in, `completion_tokens` — the fallback token sum explicitly adds all four fields back.
- **Verify-key probe model:** `sonar`.

### LLM-gateway routing (Concentrate / OpenRouter / Merge — not a "provider" but relevant to §7's "how search is enabled")
A router is modeled as a **credential**, never a `Provider` — `runs.provider` always records the underlying engine (e.g. `anthropic`), with the gateway recorded separately in `runs.route`. Full per-router-per-provider support matrix is in `lib/routers.ts` (`ROUTERS` const): `shape` (`"anthropic" | "openai-chat" | "openai-responses"`), `search` (`"passthrough" | "none"`), and per-model `slugPrefix`/`slugOverrides`. Web search through a router is only ever trusted after `probeRouterSearch()` (a live forced-search probe run at credential-save time) confirms real sources come back — stored per-credential as `router_keys.search_verified`. Perplexity has **no** router entries (its search is the product, not a parameter, and can't be normalized). OpenRouter cannot force OpenAI's own native web search at all ("Use engine 'auto' or 'exa' instead" — both third-party, so refused for grounded runs); none of the three routers pass Google's *native* grounding through except Concentrate.

---

## 8. Data model — `supabase/schema.sql`

No `create view` statements exist — the schema is tables + Postgres functions (RPCs) only; "aggregation" happens in application code (`lib/metrics.ts`), not in SQL views.

**Core monitoring tables:**
- **`projects`** (= "organizations" in the UI) — `user_id, name, brand_name, brand_aliases text[], brand_domains text[]` (index 0 = primary domain, rest = "phantom sites," all count for citation ownership), `description, default_provider, default_model, schedule ('off'|'daily'|'weekly'), last_run_at, use_web_search bool default true, replicates int 1-10 default 1, results_seen_at`.
- **`competitors`** — `project_id, name, aliases text[], domain`. Unique index `(project_id, lower(name))` (case-insensitive, one per project) — added via a data-migration block that first re-points orphaned `mentions.competitor_id` rows onto a canonical (oldest) duplicate, then deletes redundant mention rows, then deletes the duplicate competitor rows, before creating the constraint.
- **`topics`** — `project_id, name, description`.
- **`prompts`** — `project_id, topic_id, text, source ('ai'|'manual'), is_active, target_url` (page a prompt was written to surface — drives `computePageStats`), `specificity` (nullable; `check (specificity in ('general','mid','niche'))`).
- **`runs`** — `project_id, status ('pending'|'running'|'completed'|'failed'), provider, model, prompt_count, completed_count, error, started_at, finished_at, replicates, route` (nullable; `check (route in ('concentrate','openrouter'))` — note: `merge` router is *not* in this check constraint, even though it's a supported router elsewhere in the code — a latent gap in this schema file).
- **`responses`** (= "answers") — `run_id, project_id, prompt_id, topic_id, provider, model, response_text`.
- **`mentions`** — `response_id, run_id, project_id, topic_id, entity_type ('brand'|'competitor'), competitor_id, entity_name, mentioned, mention_count, first_position double precision default -1, sentiment ('positive'|'neutral'|'negative'), recommended bool`.
- **`sources`** — `response_id, run_id, project_id, url, domain, title, snippet, is_owned bool default false`.

**Credentials:**
- `provider_keys` (BYOK, one per `(user_id, provider)`, `provider in ('anthropic','openai','google','perplexity')`, encrypted at rest, only `key_hint` shown).
- `router_keys` (BYOK gateway credential, one per `(user_id, router)`, `router in ('concentrate','openrouter','merge')`, plus `search_verified text[]` — the providers this specific key's native search was actually observed passing through, per §7).
- `search_keys` (Brave web-search key for the "web mentions" feature, `provider in ('brave')`).
- `api_keys` (Lettertrace's own programmatic-access keys for REST v1 / MCP — SHA-256 hash only).

**OAuth 2.1 authorization server** (full RFC 8628 device flow + PKCE + rotating refresh tokens): `oauth_clients` (seeds a first-party `lt_cli` public client with loopback redirect URIs), `oauth_authorizations` (standing user↔client grants), `oauth_pending_requests`, `oauth_authorization_codes` (single-use, `resource in ('v1','mcp')` — RFC 8707 audience-bound), `oauth_access_tokens` (scopes can never be empty or `'*'`), `oauth_refresh_tokens` (rotating, family-based reuse detection), `oauth_device_codes`, `oauth_rate_limits`.

**Team/collaboration:** `project_members` (owner stays `projects.user_id`; membership is additive, single role `'member'` today), `project_invites` (opaque token stored only as SHA-256 digest, one-pending-per-address-per-project via a partial unique index).

**Telemetry/ops (staff-only, RLS-default-deny):** `activity_logs` (per-account, denormalized, append-only feed of every run/setting-change/API call across dashboard/api/mcp/cli/cron), `ops_events` (hour-bucketed operational counters keyed by `(kind, signature, hour)` with an atomic upsert RPC `record_ops_event`, deliberately carries **no customer content** — provider/model yes, prompt text/brand names/answers/domains never), `outbound_clicks` (cross-product conversion tracking to sibling Letter Company products).

**Third-party web-mentions (Reddit etc., a separate, weekly, opt-in signal):** `web_mention_watch` (per-project config: `sites text[] default '{reddit.com}'`, `exclude_terms`, `query_budget`), `web_mention_runs` (collection events), `web_mentions` (one row per `(project_id, page_key)`, `kind in ('brand','topic')`, tracks `seen_count`/`first_seen_at`/`last_seen_at` so re-sightings don't inflate a "new chatter" trend).

**Trial/billing metering (on `profiles`):** `trial_tokens_used`, `trial_spend_micros`, `trial_runs_used`, each with atomic increment/consume RPCs (`increment_trial_tokens`, `increment_trial_spend`, `consume_trial_run` — single `UPDATE ... WHERE trial_runs_used < max_runs RETURNING`, race-safe), plus `_for(uid, ...)` variants restricted to `service_role` only (used by the cron scheduler, which has no `auth.uid()`).

**RLS:** every customer-facing table has row-level security; a `can_access_project(project_id)` / `is_project_owner(project_id)` pair of `SECURITY DEFINER` helper functions (to avoid RLS-policy recursion between `projects` and `project_members`) gates almost every child-table policy. Trigger-based guards (not just column grants, since "Supabase re-grants table privileges to `authenticated`") prevent clients from resetting their own `trial_runs_used`/`trial_tokens_used` (`guard_profiles`) or reassigning `projects.user_id` to steal billing (`guard_projects`).

---

## 9. Scheduling

**Cron endpoint:** `app/api/cron/run/route.ts`, exported as both `GET` and `POST` (`GET` for Vercel Cron's native invocation, `POST` for manual curl), `maxDuration = 800` (seconds, ≈13.3 min — the ceiling `ABANDONED_RUN_MS` in `lib/engine.ts` is set safely above).

**`vercel.json`:**
```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "crons": [
    { "path": "/api/cron/run", "schedule": "0 8 * * *" },
    { "path": "/api/cron/letterprove-health", "schedule": "0 */6 * * *" }
  ]
}
```
i.e. the monitoring sweep runs **once daily at 08:00 UTC** (not truly "daily/weekly" per-project at arbitrary times — see below); a separate health-check cron for a `letterprove` integration runs every 6 hours (out of scope for this report).

**`CRON_SECRET`:** authenticated via a constant-time comparison to prevent timing attacks:
```ts
function authorized(header: string | null, secret: string | undefined): boolean {
  if (!header || !secret) return false;
  const a = Buffer.from(header);
  const b = Buffer.from(`Bearer ${secret}`);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}
```
checked against `Authorization: Bearer $CRON_SECRET` (Vercel Cron sends this header automatically for a configured cron path). `.env.example` declares `CRON_SECRET=replace-with-a-random-secret`.

**How daily/weekly actually works:** the single 08:00-UTC tick is a **sweep**, not a per-project scheduler — every project with `schedule != 'off'` is evaluated on every tick, and `isDue()` decides whether that specific project should actually run *this* tick:
```ts
function isDue(project: Project, now: number): boolean {
  if (project.schedule === "off") return false;
  if (!project.last_run_at) return true;
  const last = new Date(project.last_run_at).getTime();
  const interval = project.schedule === "weekly" ? WEEK_MS : DAY_MS;
  return now - last >= interval;
}
```
So "daily" means "at least `DAY_MS` (24h) since `last_run_at`, checked once a day at 08:00 UTC," and "weekly" means the same with `WEEK_MS` (7×24h). A project created with `schedule: 'daily'` and no prior `last_run_at` is due immediately on the next tick.

**Per-tick sequence** (`sweepAndRun`, `app/api/cron/run/route.ts`):
1. `sweepAbandonedRuns()` — unconditionally, before anything else.
2. Fetch every project where `schedule != 'off'`.
3. For each due project: resolve a runnable key via `resolveRunKey()` (own key → trial, exactly like a manual run); if the account only has trial coverage, atomically `consume_trial_run_for(uid, max_runs)` before executing (skips with reason `"exhausted"` if the allowance is gone); calls `executeRun()` with `context: { channel: "cron", actorType: "cron", actorId: "scheduler", actorLabel: "Scheduler" }`.
4. Wraps the whole tick in one OpenTelemetry span (`cron.run`) with counts (`scheduled`, `processed`, `skipped`, `failed`, `swept`) as attributes.

New projects created via onboarding default to `schedule: "daily"` ("cadence from the onset" — see `app/api/onboarding/complete/route.ts` line 135) — trial-funded until the allowance runs out, then gated on the user bringing their own key.

---

## 10. CLI (`cli/`) and MCP server (`app/api/mcp`)

### CLI — `cli/lettertrace.mjs` (+ `args.mjs`, `config.mjs`, `http.mjs`, `mcp.mjs`, `oauth.mjs`, `output.mjs`, `secret.mjs`, `brand.mjs`)
Published to npm as `lettertrace` (bin) / `@letterstory/lettertrace`. **Auth is OAuth 2.1 only — no API-key flag.** First command needing access opens a browser (loopback redirect, `127.0.0.1` or `--ipv6` → `[::1]`), stores tokens in `~/.lettertrace/config.json`, auto-refreshes, and — critically — **refuses to attempt browser login when not running in an interactive TTY** (`canLoginInteractively()`), throwing a clear error rather than hanging forever (important for CI/cron/agent use). Base URL resolution order: `--url` flag → `$LETTERTRACE_URL` → URL saved at last login → `https://lettertrace.com`.

**Commands (from `printHelp()` / the `commands` object):**
- **Auth:** `login [--mcp] [--both] [--ipv6] [--scope <s>]`, `logout` (revokes stored tokens server-side too), `whoami [--json]`.
- **Provider keys (BYOK):** `keys` (list, masked), `keys set <provider> [--key-file <p>] [--label <l>]`, `keys remove <provider>`. The secret is **never accepted as a CLI flag** — any of `--key`/`--api-key`/`--apikey`/`--secret` throws a hard refusal ("a key on the command line leaks into shell history and process lists... Rotate that key"); the key is read from `--key-file` (or `-` for stdin), `$LETTERTRACE_KEY`-style env var (via `secret.mjs`'s `SECRET_ENV`), piped stdin, or a hidden interactive prompt.
- **Router keys:** `routers` (list, shows per-engine `search_verified` status), `routers set <router> [--key-file] [--label] [--base-url]` (same secret-handling rule; runs the live `probeRouterSearch` check server-side and prints a per-engine verdict: not reachable / reachable-but-search-not-confirmed / measurable-with-web-search), `routers remove <router>`.
- **Data (REST v1):** `projects` / `projects create --name <n> --brand <b> [--domains a,b] [--description] [--provider] [--model]`; `prompts <project>` / `prompts add <project> --text <t> --topic <top>` / `prompts toggle <promptId> --on|--off`; `competitors <project>` / `competitors add <project> <name...>` or `--name/--domain/--aliases` / `competitors remove <competitorId>` / `competitors discovered <project>` (companies the run answers already named that nobody tracks yet); `runs <project> [--limit n]` / `runs trigger <project> [--provider] [--model]` / `runs get <runId>` (share-of-voice summary) / `runs responses <runId>` (raw answers/sources/mentions); `history <project> [--limit n]` (visibility-over-time / first-mention); `logs [--channel] [--category] [--status] [--days] [--q] [--limit]` (the account activity feed).
- **MCP passthrough:** `mcp tools` (lists the MCP server's tools), `mcp call <tool> [--arg value ...]` — speaks MCP directly to `/api/mcp`, "exactly as an AI assistant would."
- **`<project>` resolution:** every data command accepts a full UUID, a project name, a brand name, or an unambiguous hex-id prefix (≥4 chars) — resolved via `resolveProject()` against `GET /projects`, erroring with the disambiguation list on multiple matches.
- Every command supports `--json` for machine-readable output.

### MCP server — `app/api/mcp/[transport]/route.ts`
Built on `mcp-handler` (`createMcpHandler` + `withMcpAuth`), Streamable HTTP only (`disableSse: true`, stateless — no Redis needed), `maxDuration = 300`. Auth: Bearer token — either a classic Lettertrace API key or an OAuth access token minted with `resource: "mcp"` audience (a token minted for the REST API, `aud=v1`, is explicitly rejected here via `allowsAudience(auth, "mcp")`, so a token can only ever drive the surface it was consented for). Every scope check mirrors the REST API's guards (`requireScope`).

**Tools exposed** (all read/trigger-only — "Lettertrace... deliberately offers no recommendations"):
1. **`list_projects`** (scope `projects:read`, no input) — organizations with brand name, domain, last-run time.
2. **`list_runs`** (scope `runs:read`) — inputs: `project_id: uuid` (required), `limit: 1-100` (optional, default 20). Lists recent runs (status/model/prompt counts/timestamps).
3. **`get_share_of_voice_report`** (scope `runs:read`) — inputs: `run_id: uuid` (optional) **or** `project_id: uuid` (optional, uses that project's latest completed run if `run_id` omitted). Returns the full share-of-voice report: brand/competitor mention rate, share of voice, prominence, sentiment, recommendation rate, **plus** `promptEntities` (per-prompt entity breakdown — §5's `computePromptEntityStats`) and `competitorCitations` (per-prompt cited-competitor-domain breakdown — §5's `computeCompetitorCitations`), explicitly described as "find questions rivals win that you don't."
4. **`trigger_run`** (scope `runs:trigger`) — input: `project_id: uuid`. Executes a run now, on the account's own key or one free trial run.
5. **`list_activity`** (scope `projects:read`) — inputs: `q` (free-text), `channel` (enum: dashboard/api/mcp/cli/cron/system), `category`, `status` (enum: success/failure/info/pending), `days` (1-365), `limit` (1-200, default 50). Reads the same `activity_logs` feed the dashboard's Logs page shows.

Every tool call is itself logged into `activity_logs` (`category: "mcp_tool"`, `channel: "mcp"`), attributed either to the OAuth client (via `clientLabel`) or `"API key"`.

---

## 11. Onboarding — `lib/onboard.ts` + `app/api/onboarding/*`

Two entry points share this module's logic so they can't drift: the dashboard wizard (`POST /api/onboarding/suggest` → `POST /api/onboarding/complete`) and the API's one-shot `POST /api/v1/onboard`.

### Step 1 — read the site
`app/api/onboarding/suggest/route.ts`: `scrapeDomain(domain)` (Firecrawl when configured, per `lib/scrape.ts` — not read in full for this report) pulls page text/title/`og:site_name`/description/image. This route has a hard **35-second internal deadline** (`SUGGEST_DEADLINE_MS`) shorter than its 60s route budget, specifically so a slow/congested Gemini call can't also cost the user their page identity (title/description/icon), which was already resolved in ~1s from page metadata alone and needs no model call.

### Step 2 — derive the brand name
`brandNameFromSite()` (`lib/brand-name.ts`), in priority order:
1. The page's declared `og:site_name`, if present (truncated to 60 chars).
2. Else the page `<title>`, split on `TITLE_SEPARATORS = /\s*[:|]\s+|\s+[–—·\-]\s+/` (colon/pipe flush against the brand, em/en-dash/middle-dot/hyphen requiring surrounding spaces so a hyphenated brand name isn't split), taking the first segment — unless that segment is in `GENERIC_TITLES = {home, homepage, welcome, index, untitled, landing page}`.
3. Else derived from the domain itself: strip scheme/path/query/port/`www.` (`hostOf()`), split into labels, drop the TLD, additionally drop a second-level label if it's a known public-suffix-like token (`PUBLIC_SLDS = {co, com, net, org, gov, edu, ac, or, ne}` — so `acme.co.uk` → "Acme," not "Co"), then title-case the remaining label, splitting on `-`/`_` (`well-known-co` → "Well Known Co").

### Step 3 — suggest topics + prompts + competitors (`suggestFromSite`, lib/llm/index.ts:1726-1797)
**System prompt** (`SUGGEST_SYSTEM`, lines 1712-1714, verbatim):
```
You help set up brand-monitoring. Given a company name and text scraped from its website, infer what the company does, then propose monitoring topics and the company's direct competitors. For each topic, write realistic questions a real person would type into an AI assistant (ChatGPT or Claude) where a company like this could be recommended, compared, or mentioned. Do NOT mention the company's own name in the questions.

For competitors, act as a strict judge: only name real companies/products you are confident exist and genuinely compete for the same buyers in the same category. Prefer well-known, currently active competitors over obscure or defunct ones. Never include the company itself. Fewer, correct suggestions beat a padded list. Return ONLY JSON.
```
**User prompt template** (verbatim):
```
Company: ${opts.brandName}
${opts.description ? `\nWhat the company says it does: ${opts.description}\n` : ""}
Website text:
"""
${siteText || "(the site could not be read — work from the company name and description above)"}
"""
${opts.existingTopics?.length ? `\nTopics already being monitored (do NOT repeat these or close variants of them — propose what's missing):\n${opts.existingTopics.map(t => `- ${t}`).join("\n")}\n` : ""}
Return a JSON object of this shape:
{
  "description": "one concise sentence describing what the company does",
  "topics": [
    { "name": "short topic label", "prompts": ["question 1", "question 2", "question 3", "question 4"] }
  ],
  "competitors": [
    { "name": "Competitor Inc", "aliases": ["short name"], "domain": "competitor.com" }
  ]
}
Provide 3 or 4 topics, each with 4 to 6 natural questions. Never put the company's own name in the questions.
Provide up to 5 competitors. "aliases" are other names an AI answer might use for it (short name, product name, former name). Empty array if none. "domain" is its primary website domain, lowercase, no protocol or path. Null if unsure. Return an empty array if you cannot name real competitors with confidence.
```
(`siteText` truncated to 6000 chars; called with `maxTokens=2000, json=true`.) **Note:** unlike `generateVariations` (§1), this prompt has **no specificity-ladder / "must demand named companies" instructions** — it's the older, simpler "realistic questions" instruction. The prompt-playbook (§2) is effectively documenting that this onboarding-suggestion prompt is *weaker* than the topic-generate prompt at producing name-eliciting questions.

Onboarding-specific competitor de-dup/exclusion: `normalizeCompetitorList()` (`lib/competitors.ts`) strips blank names, drops anything matching `exclude` (brand name + its aliases, case-insensitive) or `seen` (case-insensitive dedup, first occurrence wins), and truncates to a `limit`.

### Step 4 — pick the engine (`pickProjectEngine`)
Computes `coveredProviders({direct: <providers with a stored BYOK key>, routers: <router coverage>, webSearch: true})`; picks the environment default provider (`pickDefaultProvider()`, `lib/trial.ts`) if it's in the runnable set or if nothing is runnable yet (fresh account, will run on trial), else the first runnable provider — "runs never substitute another provider's key, so defaulting purely on the operator's trial config would hand a BYOK user a project whose first monitor can't execute."

### Step 5 — persist (`persistOnboarding`)
Inserts **competitors first, then topics + their prompts** — order matters because `executeRun` reads `competitors` at run time to detect rival mentions, so seeding them after the first run would leave that run's share-of-voice with nothing to compare against.

### Step 6 — the first sweep (`firstSweep`)
Not a single run — **one run per engine the account can fund**, launched in parallel (`Promise.allSettled`): every provider the owner's own keys cover, plus every trial-covered provider while the trial allowance is active (deduped via a `Set`), sorted so the project's own `default_provider` leads. Each trial-funded engine **atomically consumes one free run** (`meter.consume()`) sequentially before its run starts, so a 3-engine sweep against a 15-run trial allowance spends 3, and the sweep stops granting further engines exactly where the allowance runs out (consumed runs count even if the run later fails — "the same deal as the Run button"). Trial-funded runs **share** the remaining spend budget (`budgetMicros / trialRuns`) rather than each claiming the full cap. `background: true` (the default for the dashboard's onboarding-complete flow) returns as soon as the run rows exist, with the actual execution continuing via `fireAndForget()` after the HTTP response — "a sweep takes minutes."

### Handing an onboarded org to its real owner (`resolveOnboardingAccount`, `mintApiKey`)
Used by API-driven onboarding (e.g. an agent onboarding a brand on someone else's behalf): looks up (or creates, passwordless, `email_confirm: true`) a Supabase user by email, then `mintApiKey()` (max 10 keys/user) returns a plaintext Lettertrace API key exactly once — the new owner reaches the account via normal password-reset/magic-link, and "everything set up for them is already there... That IS the transfer."

---

## 12. Control brands / model-drift handling / sampling repetition / temperature

- **"Control brand" concept: does not exist.** A repo-wide case-insensitive grep for `control.brand`/`controlBrand` returns zero hits. There is no mechanism for tracking a known-stable reference brand to calibrate/normalize a run's numbers against.
- **Temperature: never set.** A repo-wide grep for `temperature` (across `.ts`/`.mjs`) returns **zero hits** anywhere in the codebase. Every provider call (Anthropic `messages.create`, OpenAI `chat.completions.create`/Responses API, raw Gemini/Perplexity `fetch` bodies) omits the parameter entirely, so every answer is generated at whatever default temperature/sampling setting the provider applies server-side. This is consistent with the product's framing (measuring what a *real* consumer-facing assistant would answer, at its default settings) but is worth flagging as a possible source of run-to-run noise that `replicates` (below) is the only mitigation for.
- **"Sampling repetition":** implemented as `projects.replicates` (integer, 1-10, default 1, `check` constraint in schema) — see §6. Each active prompt is duplicated `replicates` times into the run's job list; each duplicate is answered, stored, and mention-detected **independently**, giving `replicates` i.i.d. samples of the same question. This is the *only* sampling-repetition mechanism — there's no separate "N-of-M voting" or majority-consensus logic; each replicate's answer is simply another row feeding the same Wilson-interval aggregate math (§5). The prompt-playbook (§2) frames this explicitly: "Answers vary between identical calls... At a true 50% rate, a single ask reads zero half the time," and recommends `replicates: 3+` for low-authority/new clients specifically to make a first mention statistically legible rather than noise.
- **"Model drift" handling:** the term appears in the codebase, but exclusively in the sense of *software/measurement drift* between code paths that must stay identical — e.g. a routed call vs. a direct call silently diverging in what gets measured (`lib/llm/index.ts` comments: "so a routed call and a direct call can't drift apart in the parts that decide what gets measured"), or the README's discussion of a gateway that "permits searching but can't be made to search" causing a routed measurement to "drift against a direct key." **There is no mechanism for detecting or compensating for a provider silently changing its underlying model weights/behavior over time** (the closest related concept is the deliberate choice to use Google's *rolling* aliases like `gemini-flash-latest` rather than pinned dated versions — `lib/models.ts` explicitly documents the resulting trade-off: "if Google moves what it points at, a change in the trend line may be the model rather than the brand," i.e. the product accepts unannounced-model-drift risk in exchange for not 404ing on new signups). Similarly, `runs.route`/`runs.provider`/`runs.model` are recorded per-run precisely so a step-change in a trend line can later be attributed to "the credential/model changed" rather than "visibility changed" — but this is a diagnostic/attribution field, not an automatic drift-detection or correction system.
- **Router/model-swap protection (the nearest thing to "drift" the code actively defends against):** OpenRouter's `extraBody` pins the upstream provider (`provider: { order: [OPENROUTER_UPSTREAM[provider]], allow_fallbacks: false }`) specifically because "OpenRouter price-load-balances a model across upstream hosts that can serve different quantizations, and moves between them silently... a measurement change disguised as a visibility change: the mention rate shifts because routing shifted." This is the one concrete, defended-against "drift" scenario in the whole codebase, and it's about infrastructure routing, not model-weight drift.

---

## Appendix: file index for reuse

| Concern | File(s) |
|---|---|
| Prompt-variation generation + system prompt | `lib/llm/index.ts:1491-1592`, `app/api/topics/[id]/generate/route.ts` |
| Prompt methodology doc | `docs/prompt-playbook.md` |
| Mention detection | `lib/mentions.ts`, `lib/mentions.test.ts` |
| Sentiment/recommendation analysis | `lib/llm/index.ts:1594-1710`, `lib/llm/analysis.test.ts` |
| Metrics/formulas | `lib/metrics.ts`, `lib/metrics.test.ts` |
| Run orchestration | `lib/engine.ts`, `lib/engine.test.ts`, `lib/engine-budget.test.ts` |
| Provider adapters + gateway routing | `lib/llm/index.ts` (whole file), `lib/routers.ts`, `lib/routers.test.ts` |
| Model catalog | `lib/models.ts`, `lib/models.test.ts` |
| DB schema | `supabase/schema.sql` |
| Cron | `app/api/cron/run/route.ts`, `vercel.json` |
| CLI | `cli/lettertrace.mjs`, `cli/README.md`, `cli/{args,config,http,mcp,oauth,output,secret,brand}.mjs` |
| MCP server | `app/api/mcp/[transport]/route.ts`, `app/api/mcp/mcp-route.test.ts` |
| Onboarding | `lib/onboard.ts`, `lib/onboard.test.ts`, `app/api/onboarding/{suggest,complete}/route.ts`, `lib/brand-name.ts`, `lib/competitors.ts` |
