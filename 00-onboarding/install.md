# Installation inside a website repository

Use either a native plugin or the direct installer. Both run from your existing website repo
and keep that website's `.seo-engine/` state there. Installing code doesn't complete onboarding:
ask the agent to use `seo-setup` once for that website, then reuse the saved setup.

## Native plugins

Codex:

```bash
codex plugin marketplace add DannyByDesign/seo-engine
codex plugin add seo-engine@seo-engine
```

Claude Code, from the website project:

```bash
claude plugin marketplace add DannyByDesign/seo-engine
claude plugin install seo-engine@seo-engine --scope project
```

The project-scoped Claude installation records the selection in the website's settings for
teammates. Plugin code lives in the host's cache. Code can be shared across projects; company
knowledge, API credentials and Python environments cannot. Use a new agent session after
installation if skills aren't visible. This is a GitHub-hosted marketplace, not a claim of
listing in a vendor's official plugin directory.

The package includes the complete engine: skills, cross-phase scripts, shared libraries and
human writing corpus. Copying a single `SKILL.md` with a generic skill downloader is insufficient.
Don't add links from your site to a versioned plugin cache; the host manages discovery.

Provider documentation: [Codex packaging](https://developers.openai.com/plugins/build/plugins)
and [Claude marketplaces](https://code.claude.com/docs/en/plugin-marketplaces).

## Direct install

From any directory inside your website's Git repository:

```bash
curl -fsSL https://raw.githubusercontent.com/DannyByDesign/seo-engine/main/bootstrap.sh | bash
```

Requires Bash, Git, curl, tar and Python 3.9+. It resolves the repository root, downloads an
immutable revision of the engine, and installs it under `.seo-engine/engine/`. It preserves
existing `.env`, Git remotes/history and agent instructions. A scoped block in `AGENTS.md`
and `CLAUDE.md` tells the agent where onboarding lives. If your agent doesn't read those files,
ask it to read `.seo-engine/engine/00-onboarding/seo-setup/SKILL.md` directly.

For optional local skill discovery links, add `--agent codex` or `--agent claude`:

```bash
curl -fsSL https://raw.githubusercontent.com/DannyByDesign/seo-engine/main/bootstrap.sh | bash -s -- --agent codex
```

The installer doesn't run onboarding, make API calls to SEO vendors, change the website's
package dependencies or publish content. Onboarding creates `.seo-engine/venv/`, installs the
engine's Python requirements there, and guides credentials. Existing `.env` values are preserved.
The installed commit is recorded in `.seo-engine/engine/.installed-by-bootstrap`.

## Updates and removal

Use your host's plugin manager for native plugin updates/removal. For direct installs,
re-running the command keeps the existing version; request an update explicitly:

```bash
curl -fsSL https://raw.githubusercontent.com/DannyByDesign/seo-engine/main/bootstrap.sh | bash -s -- --update
```

Pass `--ref COMMIT_OR_TAG` to select an engine revision. To pin the bootstrap code too, replace
`main` in its download URL with the same revision. A failed download leaves the installed engine
untouched. Updates replace engine code only; the website's brand brief, state, reports, `.env`
and Python environment remain. Ask the agent to refresh Python requirements after an update.
Don't edit installed engine code; contribute changes upstream or keep a separate development clone.

To remove a direct installation, ask your agent to remove `.seo-engine/engine/`, only the skill
links pointing to it, and its marked blocks in `AGENTS.md`/`CLAUDE.md`. Keep `.seo-engine/knowledge.md`
and other site state unless you explicitly want them deleted. Keep credentials used by the website.

## Existing standalone SEO workspaces

Stop running tasks in the old workspace. Ask the agent to move its private SEO context into
the existing website repo, inspect conflicting files before merging, and run setup there.
Do not overwrite an already configured website or mix state from different brands. Keep a
private backup until the agent verifies the site identity and resumes the saved next action.
