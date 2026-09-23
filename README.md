# SEO Engine

Give your AI coding agent a repeatable workflow for researching, writing and improving a
website’s SEO. Each copy learns one brand’s goals and keeps its research and decisions
between sessions.

Use it to:

- Find useful topics through search results, competitor research and available analytics.
- Write articles grounded in your experience: the agent interviews you and confirms what
  it may share, studies human writing examples, then edits for clarity and concision.
- Diagnose technical SEO problems, improve an existing site and measure the results.

Works with any AI coding agent that can read files and run commands. No specific model
vendor is required.

## Get started

Make a separate copy for each website:

```bash
git clone https://github.com/DannyByDesign/seo-engine.git my-website-seo
```

Open that folder in your AI coding agent and say:

> Read `00-onboarding/seo-setup/SKILL.md` and help me get started.

The agent asks about your website and goals, sets up the environment, saves a brand brief,
and guides integration setup. No need to browse skills or edit environment variables yourself.

Start without API keys; add optional services as needed. Some cost money. Host-agent writing
needs no extra model API. Optional scripted publication generation supports OpenAI, Anthropic
and Gemini.

For source-code changes, put your copy inside the website repository and tell the agent to
use the website root. A standalone copy supports research, public-site audits and drafts.

## Keep working

Ask naturally:

> Continue with our next SEO task.

> Research and draft an article about [topic] for our audience.

> Check this website for technical SEO problems.

The agent reuses saved context. Each new article gets its own interview and disclosure
confirmation.

Your brand brief, research and credentials stay in ignored `.seo-engine/` and `.env` files.
They persist locally but aren’t included in Git pushes; back them up privately. Start a fresh
copy for another brand.

## Go deeper

- [Onboarding](00-onboarding/README.md)
- [Understand → Research → Position → Choose → Execute → Learn](workflow/README.md)
- [Environment variables and integrations](.env.example)
- [Research tools](02-research/research-apis.md)
- [Human writing references](05-execute/seo-copywriting/SKILL.md)
- [Architecture and repository layout](ARCHITECTURE.md)

Traffic growth has not yet been demonstrated in a live pilot; results are not guaranteed.

## Development

With Python 3.9+ in a virtual environment:

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests/ -q
python scripts/dev/check_docs.py
```

CI runs the offline tests and documentation checks. Live API checks are opt-in and may
consume paid quota.
