#!/usr/bin/env bash
# Install cds-skill into a harness skill root.
#
#   ./install.sh dsh-project            # <cwd>/.dsh/skills/cds-skill
#   ./install.sh dsh-user               # $DSH_HOME|~/.dsh/skills/cds-skill
#   ./install.sh claude-user            # ~/.claude/skills/cds-skill
#   ./install.sh agents-user            # $DSH_AGENTS_HOME|~/.agents/skills/cds-skill
#
#   PROJECT_ROOT=/path/to/project ./install.sh dsh-project
#   FORCE=1 ./install.sh dsh-user
#
# A harness discovers a skill as <root>/<name>/SKILL.md, and the directory name
# must equal the skill name, so this copies the whole bundle to a directory
# literally called cds-skill. The engine resolves config/ and schemas/ relative to
# its own scripts/ directory, so the bundle has to stay intact.

set -euo pipefail

SKILL_NAME="cds-skill"
SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-}"

case "$TARGET" in
    dsh-project)  DESTINATION="${PROJECT_ROOT:-$PWD}/.dsh/skills/$SKILL_NAME" ;;
    dsh-user)     DESTINATION="${DSH_HOME:-$HOME/.dsh}/skills/$SKILL_NAME" ;;
    claude-user)  DESTINATION="$HOME/.claude/skills/$SKILL_NAME" ;;
    agents-user)  DESTINATION="${DSH_AGENTS_HOME:-$HOME/.agents}/skills/$SKILL_NAME" ;;
    *)
        echo "usage: $0 {dsh-project|dsh-user|claude-user|agents-user}" >&2
        exit 2
        ;;
esac

if [ ! -f "$SOURCE/SKILL.md" ]; then
    echo "SKILL.md not found beside this script; run the installer from the repository root." >&2
    exit 1
fi

if [ -e "$DESTINATION" ]; then
    if [ "${FORCE:-0}" != "1" ]; then
        echo "$DESTINATION already exists. Re-run with FORCE=1 to replace it." >&2
        exit 1
    fi
    rm -rf "$DESTINATION"
fi

mkdir -p "$DESTINATION"

# Everything the bundle needs at runtime, and nothing it does not.
for item in SKILL.md VERSION README.md LICENSE config schemas scripts references examples docs; do
    if [ -e "$SOURCE/$item" ]; then
        cp -R "$SOURCE/$item" "$DESTINATION/"
    fi
done

find "$DESTINATION" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true

echo "installed  $SKILL_NAME -> $DESTINATION"
echo
echo "Verify with:"
echo "  python \"$DESTINATION/scripts/cds.py\" selftest"
echo "  python \"$DESTINATION/scripts/cds.py\" run --signals \"$DESTINATION/examples/packet_evidence_vs_stance.json\""
