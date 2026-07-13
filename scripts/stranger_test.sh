#!/bin/sh
# stranger_test.sh — the fresh-account test as a script.
#
# Builds a throwaway HOME with synthetic rules + a synthetic transcript laid out
# as a real ~/.claude, runs the from-source quickstart exactly as the README
# tells a stranger to, and asserts the report renders. Deterministic path only:
# it passes --no-judge so it never needs the `claude` CLI, and it never touches
# the real ~/.claude.
#
# Exit 0 = PASS, nonzero = FAIL.

set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
FAKE_HOME="$TMP/home"
CLAUDE_DIR="$FAKE_HOME/.claude"
PROJECT_DIR="$CLAUDE_DIR/projects/-tmp-demo"

cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

start=$(date +%s)

# Lay out a synthetic ~/.claude from the bundled demo fixtures (100% synthetic).
mkdir -p "$CLAUDE_DIR/rules" "$PROJECT_DIR"
cp "$REPO/housebroken/demo_fixtures/rules.md" "$CLAUDE_DIR/CLAUDE.md"
cp "$REPO/housebroken/demo_fixtures/session.jsonl" "$PROJECT_DIR/session.jsonl"

# Run the exact from-source quickstart command, but against the fake HOME and
# with judging off (no CLI dependency). --days 3650 so mtime never excludes it.
out="$TMP/report.txt"
if HOME="$FAKE_HOME" python3 -m housebroken --claude-dir "$CLAUDE_DIR" \
        --no-judge --days 3650 --no-color >"$out" 2>"$TMP/err.txt"; then
    :
else
    echo "FAIL: housebroken exited nonzero"
    cat "$TMP/err.txt" >&2
    exit 1
fi

elapsed=$(( $(date +%s) - start ))

# Assert the report rendered with at least one real grade line.
if grep -qE "HOUSEBROKEN REPORT" "$out" && grep -qE "VIOLATED|PASSED|ASLEEP" "$out"; then
    echo "PASS: report rendered in ${elapsed}s"
    exit 0
fi

echo "FAIL: report did not render a recognizable grade line"
echo "--- captured output ---"
cat "$out"
exit 1
