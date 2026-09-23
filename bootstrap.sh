#!/usr/bin/env bash
# Install from GitHub into an existing website repository; no separate clone.
set -euo pipefail

agent=generic
ref=main
update=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    --agent) agent="${2:?--agent needs generic, codex or claude}"; shift 2 ;;
    --ref) ref="${2:?--ref needs a Git ref}"; shift 2 ;;
    --update) update=true; shift ;;
    --help)
      echo "Run from your website repo: bash bootstrap.sh [--agent generic|codex|claude] [--ref REF] [--update]"
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done
case "$agent" in generic|codex|claude) ;; *) echo "Unknown agent: $agent" >&2; exit 1 ;; esac
for command in git curl tar python3; do
  command -v "$command" >/dev/null || { echo "Install $command first." >&2; exit 1; }
done
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || { echo "Python 3.9+ is required." >&2; exit 1; }
repo="$(git rev-parse --show-toplevel)" || { echo "Run this inside your existing website repository." >&2; exit 1; }
state="$repo/.seo-engine"
engine="$state/engine"
if [ -L "$state" ] || [ -L "$engine" ]; then
  echo "Refusing a shared/symlinked installation; .seo-engine must belong to this website." >&2
  exit 1
fi
mkdir -p "$state"
if [ -e "$engine" ] && [ ! -f "$engine/.installed-by-bootstrap" ]; then
  echo "Existing engine is not managed by this installer; leaving it untouched." >&2
  exit 1
fi
if [ -d "$engine" ] && [ "$update" = false ]; then
  echo "Engine already installed. Use --update to replace its code; site knowledge is preserved."
  bash "$engine/install.sh" "$engine" "$repo" "$agent"
  exit 0
fi

stage="$(mktemp -d "$state/.install-XXXXXX")"
trap 'rm -rf "$stage"' EXIT
# Resolve a moving branch/tag once; download that immutable revision.
encoded_ref="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$ref")"
revision="$(curl --fail --silent --show-error --location --connect-timeout 15 --max-time 90 \
  "https://api.github.com/repos/DannyByDesign/seo-engine/commits/$encoded_ref" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"])')"
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || { echo "GitHub did not return a commit revision." >&2; exit 1; }
curl --fail --silent --show-error --location --connect-timeout 15 --max-time 180 \
  "https://codeload.github.com/DannyByDesign/seo-engine/tar.gz/$revision" -o "$stage/engine.tar.gz"
mkdir "$stage/new"
tar -xzf "$stage/engine.tar.gz" --strip-components=1 -C "$stage/new"
[ -f "$stage/new/install.sh" ] && [ -f "$stage/new/00-onboarding/seo-setup/SKILL.md" ] \
  && [ -f "$stage/new/scripts/lib/config.py" ] || { echo "Incomplete engine archive." >&2; exit 1; }
printf '%s\n' "$revision" > "$stage/new/.installed-by-bootstrap"
# Replace only managed engine code. Knowledge, state, credentials and the venv are siblings.
if [ -d "$engine" ]; then mv "$engine" "$stage/previous"; fi
mv "$stage/new" "$engine"
if ! bash "$engine/install.sh" "$engine" "$repo" "$agent"; then
  rm -rf "$engine"
  if [ -d "$stage/previous" ]; then mv "$stage/previous" "$engine"; fi
  echo "Installation failed; restored the previous engine when available." >&2
  exit 1
fi
printf '\nInstalled revision %s\n' "$revision"
echo 'Stay in your website repo and ask your agent: Set up SEO Engine for this website.'
