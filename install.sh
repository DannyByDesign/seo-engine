#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_DIR="${1:-$SCRIPT_DIR}"
TARGET_REPO="${2:-$ENGINE_DIR}"
AGENT_KIND="${3:-generic}"
case "$AGENT_KIND" in
  generic) SKILL_PARENT="" ;;
  claude) SKILL_PARENT=".claude" ;;
  codex) SKILL_PARENT=".agents" ;;
  *) echo "error: third argument must be generic, claude or codex" >&2; exit 1 ;;
esac

if [ ! -f "$ENGINE_DIR/ARCHITECTURE.md" ]; then
  echo "error: $ENGINE_DIR doesn't look like a seo-engine folder (no ARCHITECTURE.md found)" >&2
  exit 1
fi

if [ ! -d "$TARGET_REPO" ]; then
  echo "error: target repo path does not exist: $TARGET_REPO" >&2
  exit 1
fi
ENGINE_DIR="$(cd "$ENGINE_DIR" && pwd -P)"
TARGET_REPO="$(cd "$TARGET_REPO" && pwd -P)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 not found on PATH — seo-engine's scripts require Python 3.9+" >&2
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "error: python3 is $(python3 -V 2>&1) — seo-engine requires Python 3.9+" >&2
  exit 1
fi
if ! python3 -m pip --version >/dev/null 2>&1; then
  echo "warning: 'python3 -m pip' is unavailable — install pip before installing dependencies" >&2
fi

if [ "$AGENT_KIND" != generic ]; then
  SKILLS_DEST="$TARGET_REPO/$SKILL_PARENT/skills"
  mkdir -p "$SKILLS_DEST"

  echo "Installing seo-engine skills from $ENGINE_DIR into $SKILLS_DEST ..."
  count=0
  for skill_dir in "$ENGINE_DIR"/0[0-6]-*/*/ "$ENGINE_DIR"/shared/seo-references/; do
    [ -f "$skill_dir/SKILL.md" ] || continue
    name="$(basename "$skill_dir")"
    link_path="$SKILLS_DEST/$name"

    # Relink the former onboarding location without replacing unrelated skills.
    if [ "$name" = seo-setup ] && [ -L "$link_path" ] && \
       [ "$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$link_path")" = "$ENGINE_DIR/01-understand/seo-setup" ]; then
      rm "$link_path"
    fi

    if [ -e "$link_path" ] || [ -L "$link_path" ]; then
      if [ -L "$link_path" ] && [ "$(cd "$link_path" 2>/dev/null && pwd -P)" = "$(cd "$skill_dir" && pwd -P)" ]; then
        echo "  = $name (already linked)"
        continue
      fi
      echo "  ! $name already exists at $link_path and is not a link to this skill — skipping (remove it manually to re-link)" >&2
      continue
    fi

    relative_path="$(python3 -c 'import os, sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$skill_dir" "$SKILLS_DEST")"
    ln -s "$relative_path" "$link_path"
    echo "  + $name"
    count=$((count + 1))
  done

  echo ""
  echo "Linked $count skill(s) into $SKILLS_DEST"
else
  echo "Portable setup: ask your agent to read $ENGINE_DIR/00-onboarding/seo-setup/SKILL.md"
fi

if [ ! -f "$TARGET_REPO/.env" ]; then
  : > "$TARGET_REPO/.env"
  chmod 600 "$TARGET_REPO/.env"
  echo "Created $TARGET_REPO/.env (onboarding will configure only the integrations you choose)."
else
  echo "Note: $TARGET_REPO/.env already exists — see $ENGINE_DIR/.env.example for any new keys."
fi

GITIGNORE="$TARGET_REPO/.gitignore"
ensure_ignored() {
  local pattern="$1"
  if [ ! -f "$GITIGNORE" ] || ! grep -qxF "$pattern" "$GITIGNORE"; then
    printf '%s\n' "$pattern" >> "$GITIGNORE"
    echo "  + added '$pattern' to $GITIGNORE"
  fi
}
if git -C "$TARGET_REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Ensuring .gitignore covers seo-engine's secrets and state:"
  ensure_ignored ".env"
  ensure_ignored ".seo-engine/"
  ensure_ignored "credentials/"
  ensure_ignored ".agents/skills/"
  ensure_ignored ".claude/skills/"
else
  echo "warning: $TARGET_REPO is not a git repository — remember to gitignore .env and .seo-engine/ if you init one" >&2
fi

echo ""
echo "Next steps:"
echo "  1. Let your agent create a local Python environment and install requirements.txt."
echo "  2. In an agent session in $TARGET_REPO, say: Help me get started with seo-setup."
echo "     The agent will ask about this website, save its brief, and guide integration setup."
echo "  3. Resume that conversation if interrupted; completed onboarding is remembered."
echo "  4. Invoke 'seo-growth' for Understand → Research → Position → Choose → Execute → Learn"
echo "  5. To run an owned publication, invoke 'pub-site' to scaffold it, then 'pub-strategy',"
echo "     'pub-curate' and 'pub-publish' (model + guardrails: shared/seo-references/publication-playbook.md)"
