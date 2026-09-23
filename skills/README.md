# Plugin discovery adapters

Each real `SKILL.md` here points to the canonical skill in onboarding, a workflow phase, or
shared references. Plugin caches can discard symlinks, so discovery must use real files.
The instructions and corpus are maintained only in their canonical directories.

After editing a canonical skill, run `python3 scripts/dev/sync_plugin_skills.py` from the
engine root. CI checks these generated entry files for drift. Other symlinks here preserve
legacy local CLI paths; installed plugins don't depend on them.
