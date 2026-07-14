#!/usr/bin/env bash
# Installs seo-engine's skills into a target website repo's Claude Code
# skill directory (.claude/skills/) via symlinks, so the shared scripts/lib/
# stays co-located in one seo-engine/ folder while each skill (including the
# seo-references knowledge skill) is independently discoverable.
#
# Usage (run from anywhere, pass the seo-engine folder + target repo):
#   ./install.sh /path/to/seo-engine /path/to/target-repo
#
# Or, if you've already copied seo-engine/ into the target repo as a
# subdirectory, run it from there with just the target repo path (defaults
# to the parent of this script's location):
#   cd my-website/seo-engine && ./install.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_DIR="${1:-$SCRIPT_DIR}"
TARGET_REPO="${2:-$(cd "$ENGINE_DIR/.." && pwd)}"

if [ ! -f "$ENGINE_DIR/ARCHITECTURE.md" ]; then
  echo "error: $ENGINE_DIR doesn't look like a seo-engine folder (no ARCHITECTURE.md found)" >&2
  exit 1
fi

if [ ! -d "$TARGET_REPO" ]; then
  echo "error: target repo path does not exist: $TARGET_REPO" >&2
  exit 1
fi

# --- Python floor check (scripts require >= 3.9) --------------------------
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

# --- Symlink each skill into .claude/skills/ -------------------------------
SKILLS_DEST="$TARGET_REPO/.claude/skills"
mkdir -p "$SKILLS_DEST"

echo "Installing seo-engine skills from $ENGINE_DIR into $SKILLS_DEST ..."
count=0
for skill_dir in "$ENGINE_DIR"/skills/*/; do
  name="$(basename "$skill_dir")"
  link_path="$SKILLS_DEST/$name"

  if [ -e "$link_path" ] || [ -L "$link_path" ]; then
    if [ -L "$link_path" ] && [ "$(readlink "$link_path")" = "$skill_dir" ]; then
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

# --- .env: create an inert stub, never copy example values ----------------
if [ ! -f "$TARGET_REPO/.env" ]; then
  cat > "$TARGET_REPO/.env" <<EOF
# seo-engine configuration — every key is OPTIONAL.
# See $ENGINE_DIR/.env.example for the full documented list of supported
# keys and how to obtain each one. Add only the keys you actually have;
# skills report exactly which env var would unlock each missing capability.
EOF
  echo "Created $TARGET_REPO/.env (empty stub — add whichever API keys you have; all optional)."
else
  echo "Note: $TARGET_REPO/.env already exists — see $ENGINE_DIR/.env.example for any new keys."
fi

# --- .gitignore: make sure secrets and state never get committed -----------
GITIGNORE="$TARGET_REPO/.gitignore"
ensure_ignored() {
  local pattern="$1"
  if [ ! -f "$GITIGNORE" ] || ! grep -qxF "$pattern" "$GITIGNORE"; then
    printf '%s\n' "$pattern" >> "$GITIGNORE"
    echo "  + added '$pattern' to $GITIGNORE"
  fi
}
if [ -d "$TARGET_REPO/.git" ]; then
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
echo "  4. Invoke 'seo-maintain' any time you want a prioritized SEO+GEO checkup"
