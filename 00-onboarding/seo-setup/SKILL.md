---
name: seo-setup
description: Guide first-time or resumed onboarding for one website's SEO Engine workspace. Discover the site, interview the operator about goals, save brand knowledge, configure only relevant integrations, and hand off a concrete first action. Use for get started, onboard me, install, or change setup requests; completed workspaces continue with seo-growth.
---

# seo-setup

## When to use this skill

A newly installed plugin or engine in a website repo, an interrupted setup, or an explicit change
to goals/integrations. This is the single onboarding entry point for every host AI. A completed
workspace skips the initial interview unless the owner changes direction. Missing credentials
later call for a targeted setup step, not another full onboarding.

## What it checks / does

### 1. Establish the workspace and resume

Read root instructions and run `onboard.py --action status` from the intended workspace.
Read existing config, onboarding and knowledge before asking anything. For existing setups
without an onboarding record, reuse their site identity and settings and ask only missing
business questions. Do not infer the customer's business from this template or its corpus.

The **existing website repository is the workspace**. Keep its name, Git history and remotes.
No separate SEO project, clone or repo renaming is needed. The public upstream distributes
reusable code. Plugin managers may cache that code globally; the website's brand brief,
credentials, interviews and research always stay in its own workspace.

For a plugin install, use the resolved skill directory supplied by the host; do not copy the
plugin or link skills out of a versioned cache. For the direct installer, engine code lives
in `.seo-engine/engine/`. Both routes run commands from the website root, not from the
engine/cache directory. Different websites share tools, never a state directory.

If an older standalone SEO workspace already exists for this same site, identify its saved
context before starting again. Move the complete private context into the website repo only
within user scope, preserving existing target settings; stop on conflicts instead of
silently duplicating or overwriting memory. Source/CMS access remains necessary for implementation.
A deliberate remote-only workspace is still supported, but isn't the default onboarding path.

Bootstrap Python 3.9+ and a virtual environment at `.seo-engine/venv/` if needed; install
`requirements.txt` from the resolved engine and use that environment's interpreter for every
subsequent command. Never install dependencies globally or inside a shared plugin cache.
Native plugin discovery needs no additional `install.sh` run. For a manually supplied engine,
`install.sh ENGINE_ROOT WEBSITE_ROOT generic` adds the entry point; `codex`/`claude` also
link skills for that host. Other agents can read this file directly. If the host cannot read,
edit or execute files, explain that capability requirement rather than requiring a model vendor.
Load only the next applicable skill, not the entire catalog.

### 2. Have a short, adaptive conversation

Follow the [native question-tool rule](../../shared/seo-references/content-interview.md#question-interface),
including its availability check and explicit fallback reason. Ask two or three questions at a time, skip
known answers, and follow up on what matters. Start with:

- Which website/brand is this workspace for, and who should it help?
- What outcome matters first: improve the existing site, research/write content, or launch an
  owned publication? What would count as progress (for example qualified inquiries)?
- What constraints should guide the work: geography/language, positioning exclusions, review
  expectations, and budget for optional services? Which services do they already have?

Inspect the website and available product/source material yourself. Propose a first useful
action; do not ask the owner for competitors, keywords, a content calendar, or structured JSON.
Clarify missing source/CMS access only when the chosen action needs it. Record unknowns as
unknown; a new site with no analytics can still start with research and drafts.

Save progress with `onboard.py --action save --file PATH` after useful answers; partial input
is accepted. Write only fields actually established. Do not mark complete before the later
steps. Keep the machine-readable input file in ignored `.seo-engine/`.

### 3. Save the site brief and technical setup

Maintain `.seo-engine/knowledge.md` as a concise current brief: offering, audience, goals,
approved positioning, constraints, useful source references, open questions, operating
permissions and the agreed next action. Distinguish observed facts, operator statements and
hypotheses. Update it as work teaches us something useful; don't append conversation transcripts.
Raw secrets/private interview details do not belong here. Onboarding establishes working
context, not permission to quote the operator or publish particular claims.

Establish the [website visual brief](../../shared/seo-references/images.md#1-establish-the-websites-visual-brief)
in `.seo-engine/visuals.md`: inspect existing assets and components, save brand references,
sourcing permissions and image conventions, and use the native question tool only for gaps.
Resume this brief on later sessions; don't impose the publication's default illustration style.

Run `detect_stack.py` for a code repo (`--dir` can inspect a subdirectory). Merge evidenced
settings into `.seo-engine/config.yml`, preserving unrelated settings, topics and locales.
Resolve the production URL from user scope/config/live canonical evidence, preserving path
prefixes. Ask only if identity remains ambiguous. `onboard.py` saves the established site URL;
the agent merges framework, observed sitemap and source/build paths. For a remote-only site,
leave unknown filesystem settings unset. Missing sitemap is later diagnostic work.
`static_source_dir` ships files; `build_output_dir` is regenerated. When inspecting a nested
site, prefix detected paths relative to the workspace; never mistake engine files for the site.

### 4. Connect only what the chosen goal needs

Read the annotated [.env.example](../../.env.example) and run `check_integrations.py`.
Use its per-provider instructions plus [API setup](../../shared/seo-references/api-reference.md)
only for selected services. Show a small recommendation with what each unlocks and whether
it costs money. Do not present every missing key as a task or require a paid service to start.

| Goal | Start with | Add only when needed |
|---|---|---|
| Improve an existing site | Source access, live crawl; GSC if already available | PSI/CrUX, GA4 or PostHog for outcomes, IndexNow for submission |
| Research and write | Host browsing + human corpus + topic interview | DataForSEO for Google SERPs/volume, Ahrefs or Semrush for additional demand/backlinks; Brave/Firecrawl for discovery/rendering; LanguageTool for proofreading |
| Measure growth | Existing GSC plus GA4/PostHog or attributable exports | OpenRouter model probes for visibility questions |
| Run scripted publication generation | One OpenRouter key and chosen model slugs | Image model on the same account; social/editorial sources only if useful |

For PostHog, follow [API setup](../../shared/seo-references/api-reference.md#posthog).
Use host-assisted queries or attributable exports; the automated traffic collector does not
support PostHog yet. Reuse existing instrumentation and establish the conversion events with
the operator; credentials alone do not authorize adding tracking or changing event capture.

Host-agent writing uses the current agent and needs no extra model account. All scripted
text, optional sentence rewriting, generated covers and model probes use **OpenRouter**.
Do not ask users to sign up with individual model vendors. Configure `LLM_MODEL`,
`LLM_CHEAP_MODEL`, `LLM_REWRITE_MODELS`, `IMAGE_MODEL` and `AI_VISIBILITY_MODELS` only for
selected workflows; inspect current model capabilities/pricing and keep probe lists small.
Use the paid setup flow for `OPENROUTER_API_KEY`; a chat subscription does not cover API usage.
Existing direct-vendor settings need migration; see [API setup](../../shared/seo-references/api-reference.md#openrouter--scripted-ai).

Choose the setup path from the selected service's current account terms, not a permanent
free/paid vendor label. Reuse suitable credentials already configured for this website.

- **Paid APIs:** pause that integration and give the user the provider's setup link, the key
  type/scopes needed and a secure way to supply it. The user obtains the key and handles billing;
  resume when it is available, or record a deferral. Do not subscribe, buy credits or start a
  paid trial. Continue independent free setup while waiting.
- **Free APIs:** perform setup yourself using the host agent's available native browser or
  computer-use tools and its authenticated session. Follow current provider instructions to
  create/retrieve the needed key or download credentials, apply the minimum permissions for
  this website, and configure them locally. Don't hand routine dashboard work to the user or
  ask for confirmation at every step. Generate local credentials such as IndexNow keys locally.
- **Interrupt only for a real blocker:** login, MFA/CAPTCHA, missing account/admin access,
  required human consent, unavailable browser/secure credential transfer, or a billing step.
  State the exact action needed, let the user complete it, then resume from that point. Never
  ask for passwords or MFA codes in chat. If a free tier needs a payment method, permits billed
  overages or has unclear charges, use the paid setup path instead.

These instructions apply to any host, including Codex and Claude Code; discover the tools
actually available rather than assuming a particular browser API exists. Account access and
host-tool permissions still apply. Keep successful free setup quiet until the onboarding recap.

Use `onboard.py --action credential --key KEY` in a terminal the user can interact with, or
`--from-file PATH` for a credential file supplied by the user or obtained during authorized
free setup. Use a host-supported secure transfer or private download without echoing secrets
into chat, logs or command arguments; if unavailable, use hidden user-controlled entry.
The helper writes only that key, preserves unrelated `.env` lines and sets restrictive permissions.
For Google, prefer an absolute `GOOGLE_APPLICATION_CREDENTIALS` path to the downloaded
service-account file kept in ignored `credentials/` with restrictive permissions, or import JSON
with `GSC_SERVICE_ACCOUNT_JSON`. Never print the file. Do not source `.env` as shell code.
Non-secret settings (property ID, provider/model choices) can be edited directly.
If the host has no secure entry surface, accept a local credential file path or defer; don't
pretend credentials were connected. A ChatGPT/Claude subscription isn't an API credential.

Check only selected integrations, with existing spending authorization. Presence checks do
not validate tokens, property permissions, billing or model availability. Use the relevant
read-only skill/API call, record its actual result, and resolve access failures where possible.
Do not run the all-provider smoke harness on first use. Keep each chosen integration as
`configured` (not tested), `verified` (successful relevant call), `deferred`, or `blocked`, with
a short note. Deferred services do not block work with an explicit fallback. Credentials never
confer publication, purchasing, messaging or scheduling authority.

### 5. Finish once and hand off

Show a short recap: website, first outcome, saved context, ready/deferred capabilities, remaining
user action and the next concrete task. Correct misunderstandings using the conversation;
do not add an approval ceremony for reversible local setup. Run `onboard.py --action complete`
once the agreed brief and decisions are saved. This is completion of onboarding, not a claim
that all optional APIs work. Interrupted runs resume; completed runs go directly to the saved
next action. Continue authorized work through `seo-growth`; load `pub-site` only for a chosen
publication. Topic-specific interviews/disclosure confirmation still happen for each article.

## Running it

Set `SKILL_DIR` to the absolute directory containing this `SKILL.md` (resolve symlinks), and
use the configured Python environment. Run from the one website workspace root; in automation,
set `SEO_REPO_ROOT` explicitly. These conventions work with any host agent.

```bash
python3 "$SKILL_DIR/scripts/onboard.py" --action status
python3 "$SKILL_DIR/scripts/detect_stack.py" --dir /absolute/workspace
python3 "$SKILL_DIR/scripts/check_integrations.py" --format table
python3 "$SKILL_DIR/scripts/onboard.py" --action save --file .seo-engine/onboarding-input.json
python3 "$SKILL_DIR/scripts/onboard.py" --action credential --key GOOGLE_APPLICATION_CREDENTIALS
python3 "$SKILL_DIR/scripts/onboard.py" --action complete
```

`--from-file` reads a supplied or securely downloaded credential file instead of hidden terminal entry. `--file`
is only for non-secret onboarding JSON. Example shape (agent authors actual values):

```json
{
  "workspace_name": "acme-seo",
  "brand_name": "Acme",
  "site_url": "https://acme.test",
  "workflow": "research-content",
  "audience": "Operations leads at small businesses",
  "goals": ["Help qualified buyers evaluate the product"],
  "success_measure": "Qualified inquiries from useful articles",
  "constraints": {"paid_tools": "defer", "publication": "drafts for review"},
  "integrations": {},
  "next_action": "Research one recurring buyer question, then interview the operator"
}
```

`integrations` maps provider keys from `check_integrations.py` to `{ "status": "deferred",
"note": "Use host browsing for now; keyword volumes remain unknown" }`, or another truthful
status. Empty means the owner chose to start without APIs. Save merges top-level fields;
when editing integrations include previous decisions too.

## Expected output

`onboard.py` reports workspace, status (`not_started`, `in_progress`, `complete`), saved paths,
site identity, selected integration readiness and next action. `detect_stack.py` reports stack
and sitemap evidence; `check_integrations.py` reports credential presence and setup guidance.
Those two discovery scripts remain read-only. Onboarding writes local state only and makes
no network calls. Credential output contains the variable name, never its value.

## State files

- `.seo-engine/config.yml`: site identity and technical settings; shared by the skills.
- `.seo-engine/onboarding.json`: progress, goals, integration decisions, completion and next action.
- `.seo-engine/knowledge.md`: current brand brief, read by the host before strategy/content work.
- `.seo-engine/visuals.md`: website-specific visual references, assets, sourcing and image conventions.
- `.env`: workspace-local credentials; no fallback to another engine's keys.

All are private/ignored by default. They persist across sessions on this machine, but a Git
push does **not** back them up. Explain this at handoff: use private backup for continuity.
Only deliberately reviewed, shareable material belongs in version control; do not force-add
all of `.seo-engine/`. A private remote alone doesn't change ignore rules.

## How to interpret results

A completed record avoids repeating onboarding. A later missing token or failed API needs a
focused repair. The helper refuses silently changing an existing site's URL; an actual domain
migration needs deliberate reconciliation of identity/state, while another brand uses its own
website repository. A pending record may be incomplete and is never treated as readiness.

## Safe to auto-apply vs. human review

Inspect local/public facts, install local dependencies, link skills, merge configuration and
save the agreed brief within setup scope. Preserve existing files and user choices. Ask for
unrecoverable account access or business decisions; reuse established authority. Don't create
remotes, rename the active directory, publish, purchase, schedule or send messages implicitly.

## Guardrails

Never load another workspace's brand knowledge or credentials. Process environment overrides
local `.env`, so inspect configured variable **names**, never values, when accounts look wrong.
Do not modify the public template's README/name/corpus to personalize a customer's workspace;
identity lives in local context and the existing website repository. Never fabricate successful checks.

## References

- [Common setup](../../shared/seo-references/common-setup.md): paths and state contract.
- [Environment variables](../../.env.example): purposes, requirements and setup locations.
- [Topic interviews](../../shared/seo-references/content-interview.md): permission per article.
- [Growth workflow](../../workflow/README.md): execution after onboarding.

## Graceful degradation

No keys is a valid start for host-assisted research, drafting and local diagnosis. Explain
unavailable metrics/capabilities and keep useful work moving. Missing website source blocks
source edits/deployment, not understanding the business or preparing an evidence-based draft.
