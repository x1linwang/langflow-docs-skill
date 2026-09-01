#!/usr/bin/env bash
# Install the langflow-1-11-docs skill for whichever agent CLIs are present.
#
# Usage:
#   ./install.sh              # install globally for every detected agent
#   ./install.sh --project    # install into ./.claude/skills of the current repo
#   ./install.sh --list       # show what would be installed where, change nothing
#   ./install.sh --uninstall  # remove previously installed copies
#
# Copies rather than symlinks: symlink traversal in skill discovery is not
# guaranteed across these tools, and ~2 MB per target is not worth the risk.
# Re-run to update.

set -euo pipefail

SKILL_NAME="langflow-1-11-docs"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/skills/$SKILL_NAME"

MODE="global"
for arg in "$@"; do
  case "$arg" in
    --project)   MODE="project" ;;
    --list)      MODE="list" ;;
    --uninstall) MODE="uninstall" ;;
    -h|--help)   sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [ ! -f "$SRC/SKILL.md" ]; then
  echo "error: $SRC/SKILL.md not found. Run this from a full checkout." >&2
  exit 1
fi

# ---------------------------------------------------------------- python ----
PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,9) else 1)' 2>/dev/null; then
      PY="$candidate"; break
    fi
  fi
done
if [ -z "$PY" ] && [ "$MODE" != "list" ] && [ "$MODE" != "uninstall" ]; then
  cat >&2 <<'MSG'
error: no python3 >= 3.9 on PATH.

The skill is a Python script with no third-party dependencies, so any recent
python3 works. Install one, then re-run:
  macOS    brew install python3
  Ubuntu   sudo apt install python3
  Windows  install Python from python.org, and run this script in Git Bash or WSL
MSG
  exit 1
fi

# ---------------------------------------------------------------- targets ---
# ~/.claude/skills is read by both Claude Code and opencode, so two global
# copies cover all three supported tools.
TARGETS=()
LABELS=()

add_target() { TARGETS+=("$1"); LABELS+=("$2"); }

if [ "$MODE" = "project" ]; then
  add_target "./.claude/skills/$SKILL_NAME" "this project (Claude Code, opencode)"
  if [ -d "./.codex" ] || command -v codex >/dev/null 2>&1; then
    add_target "./.codex/skills/$SKILL_NAME" "this project (Codex CLI)"
  fi
else
  add_target "$HOME/.claude/skills/$SKILL_NAME" "Claude Code + opencode"
  if command -v codex >/dev/null 2>&1 || [ -d "$HOME/.codex" ]; then
    add_target "$HOME/.codex/skills/$SKILL_NAME" "Codex CLI"
  fi
  if [ -d "$HOME/.config/opencode" ]; then
    add_target "$HOME/.config/opencode/skills/$SKILL_NAME" "opencode (native dir)"
  fi
fi

if [ "$MODE" = "list" ]; then
  echo "source: $SRC"
  echo "python: ${PY:-none found}"
  echo "would install to:"
  for i in "${!TARGETS[@]}"; do
    state="new"; [ -d "${TARGETS[$i]}" ] && state="overwrite"
    printf '  %-58s %-28s [%s]\n' "${TARGETS[$i]}" "${LABELS[$i]}" "$state"
  done
  exit 0
fi

if [ "$MODE" = "uninstall" ]; then
  for target in "${TARGETS[@]}"; do
    if [ -d "$target" ]; then rm -rf "$target"; echo "removed  $target"; fi
  done
  exit 0
fi

# ---------------------------------------------------------------- install ---
SIZE=$(du -sh "$SRC" | cut -f1)
echo "installing $SKILL_NAME ($SIZE) using $PY"
for i in "${!TARGETS[@]}"; do
  target="${TARGETS[$i]}"
  mkdir -p "$(dirname "$target")"
  # Remove first: `cp -R src dest` nests into dest/src when dest exists.
  rm -rf "$target"
  cp -R "$SRC" "$target"
  find "$target" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
  printf '  ok  %-58s %s\n' "$target" "${LABELS[$i]}"
done

# ------------------------------------------------------------------ verify --
FIRST="${TARGETS[0]}"
echo
echo "verifying..."
if OUT=$("$PY" "$FIRST/docsearch.py" search "agent as a tool" -n 1 --no-snippet 2>&1); then
  echo "$OUT" | sed -n '1,4p' | sed 's/^/  /'
else
  echo "$OUT" | sed 's/^/  /' >&2
  echo "error: the skill installed but its first search failed." >&2
  exit 1
fi

# A fresh install must not need to write anything. Compare content, not mtimes:
# cp -R stamps every file with the current time, so an mtime comparison here
# reports a rebuild that never happened.
if command -v md5 >/dev/null 2>&1; then HASH="md5 -q"
elif command -v md5sum >/dev/null 2>&1; then HASH="md5sum"
else HASH=""; fi
if [ -n "$HASH" ]; then
  SRC_SUM=$($HASH "$SRC/index/corpus.idx.json.gz" | awk '{print $1}')
  DST_SUM=$($HASH "$FIRST/index/corpus.idx.json.gz" | awk '{print $1}')
  if [ "$SRC_SUM" != "$DST_SUM" ]; then
    echo "  note: the index was rebuilt on first use rather than used as shipped." >&2
  fi
fi

cat <<MSG

done. Start a new session in your agent and ask a Langflow question -- the
skill triggers on its description, there is nothing to configure.

  Claude Code   skills are picked up from ~/.claude/skills
  Codex CLI     skills are picked up from ~/.codex/skills
  opencode      reads ~/.claude/skills and ~/.config/opencode/skills

Try: "In Langflow 1.11, how do I make a custom component available as an agent tool?"
MSG
