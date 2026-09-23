#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_DIR="${1:-$SCRIPT_DIR}"
TARGET_REPO="${2:-$(cd "$ENGINE_DIR/.." && pwd)}"
AGENT_KIND="${3:-claude}"
case "$AGENT_KIND" in
  claude) SKILL_PARENT=".claude" ;;
  codex) SKILL_PARENT=".agents" ;;
  *) echo "error: third argument must be claude or codex" >&2; exit 1 ;;
esac

if [ ! -f "$ENGINE_DIR/ARCHITECTURE.md" ]; then
  echo "error: $ENGINE_DIR doesn't look like a seo-engine folder (no ARCHITECTURE.md found)" >&2
  exit 1
fi

if [ ! -d "$TARGET_REPO" ]; then
  echo "error: target repo path does not exist: $TARGET_REPO" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 not found on PATH — seo-engine's scripts require Python 3.9+" >&2
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "error: python3 is $(python3 -V 2>&1) — seo-engine requires Python 3.9+" >&2
  exit 1
fi
PIP_HINT="python3 -m pip install -r \"$ENGINE_DIR/requirements.txt\""
if ! python3 -m pip --version >/dev/null 2>&1; then
  echo "warning: 'python3 -m pip' is unavailable — install pip before installing dependencies" >&2
fi

SKILLS_DEST="$TARGET_REPO/$SKILL_PARENT/skills"
mkdir -p "$SKILLS_DEST"

echo "Installing seo-engine skills from $ENGINE_DIR into $SKILLS_DEST ..."
count=0
for skill_dir in "$ENGINE_DIR"/0[1-6]-*/*/ "$ENGINE_DIR"/shared/seo-references/; do
  [ -f "$skill_dir/SKILL.md" ] || continue
  name="$(basename "$skill_dir")"
  link_path="$SKILLS_DEST/$name"

  if [ -e "$link_path" ] || [ -L "$link_path" ]; then
    if [ -L "$link_path" ] && [ "$(cd "$link_path" 2>/dev/null && pwd -P)" = "$(cd "$skill_dir" && pwd -P)" ]; then
      echo "  = $name (already linked)"
      continue
    fi
    echo "  ! $name already exists at $link_path and is not a link to this skill — skipping (remove it manually to re-link)" >&2
    continue
  fi

  ln -s "$skill_dir" "$link_path"
  echo "  + $name"
  count=$((count + 1))
done

echo ""
echo "Linked $count skill(s) into $SKILLS_DEST"

if [ ! -f "$TARGET_REPO/.env" ]; then
  : > "$TARGET_REPO/.env"
  echo "Created $TARGET_REPO/.env (empty stub — add whichever API keys you have; all optional)."
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
else
  echo "warning: $TARGET_REPO is not a git repository — remember to gitignore .env and .seo-engine/ if you init one" >&2
fi

echo ""
echo "Next steps:"
echo "  1. $PIP_HINT"
echo "  2. Add whichever API keys you have to $TARGET_REPO/.env (all optional — see .env.example)"
echo "  3. In an agent session in $TARGET_REPO, invoke the 'seo-setup' skill to detect your"
echo "     stack and write .seo-engine/config.yml"
echo "  4. Invoke 'seo-growth' for Understand → Research → Position → Choose → Execute → Learn"
echo "  5. To run an owned publication, invoke 'pub-site' to scaffold it, then 'pub-strategy',"
echo "     'pub-curate' and 'pub-publish' (model + guardrails: shared/seo-references/publication-playbook.md)"
