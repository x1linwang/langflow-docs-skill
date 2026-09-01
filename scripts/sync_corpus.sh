#!/usr/bin/env bash
# Re-vendor the Langflow docs corpus from upstream and rebuild the index.
#
# Usage:  ./scripts/sync_corpus.sh [version]
#         ./scripts/sync_corpus.sh 1.12.0
#
# Defaults to the version currently vendored. Use this when Langflow publishes
# a new doc version, then review the diff before committing -- the point of a
# pinned snapshot is that it changes only when you decide it does.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL="$ROOT/skills/langflow-1-11-docs"
CORPUS="$SKILL/corpus"

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
  VERSION=$(python3 -c "import json;print(json.load(open('$CORPUS/MANIFEST.json'))['langflow_docs_version'])")
fi
echo "syncing Langflow docs version $VERSION"

command -v git >/dev/null || { echo "error: git required" >&2; exit 1; }
command -v jq  >/dev/null || { echo "error: jq required" >&2; exit 1; }

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "sparse-cloning upstream..."
git clone --filter=blob:none --no-checkout --depth 1 \
  https://github.com/langflow-ai/langflow.git "$TMP/langflow" >/dev/null 2>&1
(
  cd "$TMP/langflow"
  git sparse-checkout init --cone >/dev/null
  git sparse-checkout set docs/versioned_docs docs/versioned_sidebars >/dev/null
  git checkout >/dev/null 2>&1
)

SRC="$TMP/langflow/docs/versioned_docs/version-$VERSION"
if [ ! -d "$SRC" ]; then
  echo "error: upstream has no version-$VERSION. Available:" >&2
  ls "$TMP/langflow/docs/versioned_docs" >&2
  exit 1
fi

SHA=$(cd "$TMP/langflow" && git rev-parse HEAD)
SHA_DATE=$(cd "$TMP/langflow" && git log -1 --format=%cI)

echo "replacing corpus..."
rm -rf "$CORPUS"
mkdir -p "$CORPUS"
rsync -a --exclude='.DS_Store' --exclude='*.zip' --exclude='*.png' \
         --exclude='.gitignore' "$SRC/" "$CORPUS/"

SIDEBAR="$TMP/langflow/docs/versioned_sidebars/version-$VERSION-sidebars.json"
[ -f "$SIDEBAR" ] && cp "$SIDEBAR" "$CORPUS/_sidebar.json"

PAGES=$(find "$CORPUS" -name '*.md*' | wc -l | tr -d ' ')
SNIPPETS=$(find "$CORPUS" \( -name '*.sh' -o -name '*.py' -o -name '*.js' \) | wc -l | tr -d ' ')

cat > "$CORPUS/MANIFEST.json" <<JSON
{
  "langflow_docs_version": "$VERSION",
  "covers": "the entire Langflow ${VERSION%.*}.x line (Langflow cuts doc versions per minor, not per patch)",
  "upstream_repo": "https://github.com/langflow-ai/langflow",
  "upstream_path": "docs/versioned_docs/version-$VERSION",
  "upstream_commit": "$SHA",
  "upstream_commit_date": "$SHA_DATE",
  "vendored_on": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "pages": $PAGES,
  "code_snippets": $SNIPPETS,
  "license": "MIT",
  "excluded_from_upstream": ["*.png", "*.zip", ".DS_Store", ".gitignore"],
  "added_by_us": ["_sidebar.json (copied from docs/versioned_sidebars/version-$VERSION-sidebars.json)"]
}
JSON

# NOTICE names the version in prose; keep it in step.
if [ -f "$CORPUS/../corpus.NOTICE.template" ]; then
  sed "s/__VERSION__/$VERSION/g" "$CORPUS/../corpus.NOTICE.template" > "$CORPUS/NOTICE"
fi

echo "rebuilding index..."
python3 "$SKILL/docsearch.py" build

echo
echo "pages=$PAGES snippets=$SNIPPETS upstream=$SHA"
echo
echo "Next steps:"
echo "  1. python3 scripts/regression.py    -- retrieval must not regress"
echo "  2. review 'git diff --stat'"
echo "  3. update SKILL.md if its prose version or routing table changed"
echo "  4. BUMP \"version\" in .claude-plugin/plugin.json"
echo
echo "     Step 4 is not optional. version is pinned in plugin.json, so"
echo "     pushing a new corpus without bumping it leaves every plugin user"
echo "     on their cached copy -- they never see this update."
