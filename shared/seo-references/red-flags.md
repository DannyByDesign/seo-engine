# Red Flags, Penalty Risks & Gotchas (2026)

> Read by: **every skill in this system, before it makes any change.** This is the veto layer.
> If a proposed action conflicts with anything here, the skill must refuse or downgrade to a
> flagged recommendation for human review — never auto-apply it.
>
> Scope note: manual-action taxonomy and enforcement mechanics are among the fastest-moving parts
> of Google's system. Google's spam-policy enforcement for site reputation abuse and scaled content
> abuse moved from manual-review-only to **algorithmic detection** during the August 2025 spam
> update; a March 2026 core update reportedly left these specific policies untouched. Re-verify
> this section periodically in any long-running deployment — do not treat it as permanently fixed.

## 1. Google's spam policies — the ones that matter for an automation system

These are Google's own defined violation categories.
[Spam policies for Google web search](https://developers.google.com/search/docs/essentials/spam-policies)

### Scaled content abuse
Generating large volumes of content — by any method, including AI generation, human mass-production,
or scraping — whose **primary purpose is manipulating search rankings** rather than helping users,
and which provides **minimal value**. The policy is explicitly method-agnostic: "no matter how it's
created." This is the single highest-risk category for an AI-agent-operated content system.

**Guardrail for this system:** publishing on a cadence is allowed (the `pub-*` skills exist to do
it), but volume is never the goal and never the metric. Every piece a skill queues carries a
one-sentence reason a real reader benefits (the topic-map `brief`), is research-backed with named
sources, and clears the length/structure floor `validate_site.py` checks. The measured ceiling that
works is one to two long reads per publication per day, never batch dumps — see §7.

### Site reputation abuse ("parasite SEO")
Third-party content published on a host site specifically to exploit the host's *own* established
ranking signals (domain authority) — e.g., a payday-loan review section hosted on a otherwise
unrelated, high-authority news site. As of **November 19, 2024**, Google explicitly closed the
"first-party oversight" loophole: white-label partnerships, licensing deals, and arrangements with
partial ownership no longer exempt a site from this policy if the actual content production and
editorial standards diverge from the host's own.
[Site reputation abuse policy update](https://developers.google.com/search/blog/2024/11/site-reputation-abuse)

**Not a violation:** freelance-authored content commissioned and genuinely edited under the host's
own editorial standards, and properly disclosed affiliate content, are explicitly fine on their own.
The line is editorial independence/oversight vs. rented ranking signal.

### Expired domain abuse
Repurposing an expired domain (bought for its existing backlink/authority profile) to host unrelated
content whose primary purpose is manipulating rankings via the old domain's authority. Never
recommend or implement a strategy that involves acquiring expired/aged domains for their existing
authority.

### Cloaking
Showing search engines (or specific crawlers) different content than what a human visitor sees.
**This includes serving different content to AI crawlers than to Googlebot or human visitors** —
the same principle extends to the GEO context. Any A/B test, personalization, or bot-detection
logic in a target repo must be audited to confirm it does not differentiate content by crawler
identity in a way that could be read as cloaking.

### Doorway pages
Large sets of near-duplicate pages, each targeting a slightly different keyword/location variant,
designed to funnel search traffic to a single destination rather than to genuinely distinct content.
Programmatic page-generation (e.g., "city + service" template pages) is not inherently a violation
— but it becomes one the moment the pages are templated boilerplate with no substantive
per-page differentiation. `seo-content-optimize` must flag any templated/programmatic page set for
human review before scaling it.

### Link spam / link schemes
Any link intended primarily to manipulate ranking rather than for genuine editorial or user value —
buying/selling links that pass PageRank, excessive reciprocal linking, automated link-building,
low-quality guest-post/directory link placements done for SEO rather than audience value. This
system does not build, recommend, or automate outbound link acquisition of any kind — `seo-backlinks`
is a **monitoring** skill (tracking your own profile and competitors' for research), never an
acquisition tool.

## 2. Manual actions: what actually happens

- A manual action can remove **some or all** of a site from search results entirely — not merely
  demote it. [Manual actions report](https://support.google.com/webmasters/answer/9044175)
- Recovery requires fixing the violation on **every affected page** — a partial fix does not yield
  a partial recovery. Any remediation workflow this system runs must guarantee complete coverage of
  a detected violation pattern across the whole site, not a sample.
- Reconsideration review can take **days to weeks** after a fix is submitted — do not design
  workflows that assume same-day recovery.
- Do not assume a fixed, enumerable list of manual-action category names as displayed in Search
  Console — the exact taxonomy is less rigid/stable than commonly assumed in SEO folklore; describe
  violations in terms of the underlying policy (§1), not a specific UI label.

## 3. AI-content-specific pitfalls

- **There is no "AI content penalty."** Google does not penalize content for being AI-generated;
  it penalizes scaled, low-value content regardless of production method (§1). The Shredder pass
  in `pub-write` (sentence-level rewriting across several model providers) is a *voice-diversity*
  tool for a multi-author masthead, not a detector-evasion tool — run it for that reason or not at
  all; nothing in Google's or the AI vendors' policies rewards it.
- **Do not freshness-fake.** Updating a timestamp or making a cosmetic edit without substantive
  content improvement is a form of the manipulation Google's helpful-content guidance targets
  directly, and it's brittle — readers notice a stale article with a suspiciously new date.
- **Cadence is a schedule, not a target.** The planner publishes N per week because a real
  publication does, but every slot is filled from a scored topic map with a stated reader benefit;
  an empty slot stays empty. The moment "hit the number" overrides "clear the bar", the system is
  producing scaled content abuse by another name.

## 4. Technical mistakes that silently tank a site

These aren't policy violations — they're self-inflicted technical failures that this system's
audit skills exist specifically to catch:

- **Accidental `noindex`** — left over from staging, a CMS default, or a bad conditional (e.g.,
  `noindex` applied to a whole template because of one flag meant for a subset of pages). Especially
  common after a redesign or CMS migration. Auto-scan for `noindex` on any page that has inbound
  internal links or historical search traffic, and treat mismatches as high-priority alerts, not
  silent auto-fixes (removing a `noindex` could also be wrong if it was intentional — flag, don't guess).
- **Canonical loops and cross-domain canonical hijacking** — see [seo-playbook.md](seo-playbook.md)
  §5. A cross-domain canonical pointing somewhere the site owner didn't set is a security incident,
  not a routine fix — escalate rather than auto-correct.
- **JS-rendering traps** — compare raw HTML with rendered content before diagnosing crawler
  visibility. Google AI search uses Google's rendered index; raw-fetch bots may see only an
  empty shell. See [geo-playbook.md](geo-playbook.md) §11 for the scoped guidance.
- **hreflang errors** — missing reciprocal tags (A points to B but B doesn't point back to A),
  pointing to non-canonical or redirecting URLs, or inconsistent language/region codes. These
  silently cause the wrong locale variant to rank in the wrong country, which looks like "random"
  performance variance if not checked directly.
- **Redirect chains and loops** — each additional hop in a chain dilutes signal and slows crawl
  budget/user experience; a true loop makes the destination unreachable/uncrawlable entirely.
- **IndexNow / URL-submission misconceptions** — submitting a URL via IndexNow does **not**
  guarantee indexing; it only signals a change and may earn a prioritized (not immediate) crawl
  visit. Submitted URLs **count toward the site's crawl quota**, so submitting URLs indiscriminately
  can itself waste crawl budget. **Google does not participate in IndexNow at all** — for Google,
  rely on Search Console (sitemaps + URL Inspection), not IndexNow.

## 5. GEO-specific gotchas

- **Blocking the wrong AI crawler.** Blocking `Google-Extended` does *not* remove a site from AI
  Overviews (those use the standard Search index); blocking `GPTBot` does *not* affect ChatGPT
  search citations (that's `OAI-SearchBot`); blocking Bing's unified crawler removes the site from
  **both** classic Bing results and Copilot at once (no separable training-only bot exists). See
  [geo-playbook.md](geo-playbook.md) §4 for the full per-vendor table — audit against it explicitly,
  never apply a generic "block/allow all AI bots" rule.
- **Treating llms.txt as a citation lever.** It measurably is not (see geo-playbook §1). Don't spend
  engineering effort maintaining one under the belief it drives visibility.
- **Overselling structured data for GEO.** Schema.org markup has no proven causal AI-citation
  benefit (see geo-playbook §3) and showed a statistically significant *negative* effect on Google
  AI Overviews in the one rigorous controlled test available. Implement schema for its real,
  separate traditional-SEO value — don't justify it internally as a GEO win.
- **Cloaking risk extends to AI crawlers.** Serving different content to `OAI-SearchBot` or
  `PerplexityBot` than to human visitors or Googlebot is the same violation as classic cloaking,
  just against a newer set of user agents.

## 6. The meta-rule for every skill in this system

Before any skill applies a change, it should be able to answer: **"If Google (or an AI-search
provider) fully understood exactly why I made this change, would they consider it a legitimate
improvement, or an attempt to game their system?"** If the honest answer is ambiguous, escalate to
human review rather than auto-apply. This system is designed to compound trust over years, not to
extract a short-term ranking bump that a future policy update (or manual review) claws back with
interest.

## 7. Third-party publications (the `pub-*` skills): where the lines are

Publications must disclose ownership and use real contributor or organization attribution. Do not create fictional authors, backdate tenure, conceal commercial relationships, or treat multiple sites as independent endorsements. The publication playbook describes the required review and migration process. Mechanical word/source floors do not prove helpfulness or policy compliance. Never scale publishing faster than evidence and editorial capacity permit.
