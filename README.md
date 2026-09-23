# SEO Engine

Install SEO skills into your existing website project. Your AI agent researches opportunities,
interviews you for firsthand knowledge, writes useful content, fixes technical issues and
measures results. Each website keeps its own brand brief and research between sessions.

Works with any AI coding agent that can read files and run commands. You stay in your website
repo—no separate SEO project to clone or open.

## Install

**Copy this prompt into your AI agent while it has your website repo open:**

```text
Install SEO Engine into the website Git repository you are currently working in.
Read https://raw.githubusercontent.com/DannyByDesign/seo-engine/main/00-onboarding/install.md
and follow the direct-install instructions. Preserve this repo's existing files,
credentials and agent instructions. Then read the installed skill at
.seo-engine/engine/00-onboarding/seo-setup/SKILL.md and guide me through onboarding,
asking about my goals and configuring only the integrations I need.
```

### Prefer manual installation?

Choose one route, then start onboarding below.

<details>
<summary><strong>Codex plugin</strong></summary>

```bash
codex plugin marketplace add DannyByDesign/seo-engine
codex plugin add seo-engine@seo-engine
```

Open a new agent session in your website repo after installing.

</details>

<details>
<summary><strong>Claude Code plugin</strong></summary>

Run these as separate commands in Claude Code:

```text
/plugin marketplace add DannyByDesign/seo-engine
/plugin install seo-engine@seo-engine
```

Use the plugin from your website project. For team installation, see [project-scoped setup](00-onboarding/install.md).

</details>

<details>
<summary><strong>Direct install for any coding agent</strong></summary>

Run from your existing website repository (macOS, Linux or WSL; Python 3.9+ required):

```bash
curl -fsSL https://raw.githubusercontent.com/DannyByDesign/seo-engine/main/bootstrap.sh | bash
```

This downloads the engine into `.seo-engine/engine/` and adds a short entry point to your
agent instructions, preserving existing content. [Install details and updates](00-onboarding/install.md).

</details>

## Get started

The prompt above starts onboarding for you. If you installed manually, say:

> Use seo-setup to set up SEO Engine for this website.

The agent asks about your goals, sets up its Python environment, saves a brand brief, and
guides only the integrations you need. No manual environment-file editing. Start without
API keys; some optional services cost money.

Then ask naturally:

> Research and draft an article about [topic] for our audience.

> Check this website for technical SEO problems.

> Continue with our next SEO task.

Articles combine external research with your approved experience, study human writing
examples, and receive a full clarity/concision edit. Each topic gets its own interview and
disclosure confirmation.

## Your website owns its knowledge

Engine code can update independently. Your website's `.seo-engine/` holds its onboarding,
brand brief, research and decisions; credentials stay in its `.env`. These files are ignored
by Git, so back them up privately. Different websites never share this state.

Host-agent writing uses your chosen model. Optional scripted publication generation supports
OpenAI, Anthropic and Gemini APIs. Traffic growth has not yet been demonstrated in a live pilot.

[Onboarding](00-onboarding/README.md) · [Workflow](workflow/README.md) ·
[Integrations](.env.example) · [Architecture](ARCHITECTURE.md)

## Development

Clone this repository only to contribute to the engine. With Python 3.9+ in a virtual environment:

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests/ -q
python scripts/dev/check_docs.py
```
