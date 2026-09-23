# Onboarding

Start here once per website workspace. Read [seo-setup/SKILL.md](seo-setup/SKILL.md),
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

Per-website progress and knowledge stay in the workspace's ignored `.seo-engine/` directory;
credentials stay in its ignored `.env`. This directory contains reusable onboarding logic,
not any customer's answers. See the root [.env.example](../.env.example) for the variable
reference and [workflow](../workflow/README.md) for what happens after setup.
