# Onboarding

Start here once per existing website repository, after installing the plugin or engine. Read [seo-setup/SKILL.md](seo-setup/SKILL.md),
or tell your AI agent: **“Help me get started.”**

```text
00-onboarding/
└── seo-setup/
    ├── SKILL.md                     guided conversation and handoff
    └── scripts/
        ├── onboard.py               save/resume setup, enter credentials, complete
        ├── detect_stack.py          inspect the website's framework and paths
        └── check_integrations.py    report configured services and setup guidance
```

The agent establishes the website, goals and constraints, saves a brand brief, configures
selected integrations, and hands off the first useful task to the ongoing workflow.
It resumes incomplete setup and reuses completed onboarding on later sessions.

For selected free APIs, the agent uses its available browser/computer-use tools to obtain
credentials and configure them, interrupting only when user action is required (such as login).
For paid APIs, it pauses that integration and guides you to obtain the key securely.

Per-website progress and knowledge stay in the workspace's ignored `.seo-engine/` directory;
credentials stay in its ignored `.env`. This directory contains reusable onboarding logic,
not any customer's answers. See the root [.env.example](../.env.example) for the variable
reference and [workflow](../workflow/README.md) for what happens after setup.
