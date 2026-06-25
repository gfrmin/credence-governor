#!/usr/bin/env bash
# check.sh — local CI for credence-governor (sole-developer: run before pushing).
#
# There is no GitHub Actions CI by preference. This is the gate: lint + tests for
# the Python core, the Python Claude Code adapter, and the TS OpenClaw adapter.
# Run from anywhere; it cd's to the repo root.
#
#   scripts/check.sh            # everything
#   scripts/check.sh py         # Python only (skip the TS adapter / npm)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ONLY="${1:-all}"
PY="${PYTHON:-python3}"

echo "== ruff: governor-core + claude-code adapter =="
"$PY" -m ruff check \
  packages/governor_core/credence_governor_core \
  adapters/claude-code/credence_governor_claude_code \
  adapters/claude-code/plugin_hook.py

echo "== pytest: governor-core (parity; no engine needed) =="
PYTHONPATH="packages/governor_core" "$PY" -m pytest packages/governor_core/tests -q

echo "== pytest: claude-code adapter =="
"$PY" -m pytest adapters/claude-code/tests -q

if [ "$ONLY" = "py" ]; then
  echo "OK (Python only)"
  exit 0
fi

echo "== openclaw adapter (TS): typecheck + build + test =="
if command -v npm >/dev/null 2>&1; then
  ( cd adapters/openclaw && (npm ci || npm install) >/dev/null 2>&1 && npm run typecheck && npm run build && npm test )
else
  echo "  npm not found — skipping the TS adapter (run with a Node toolchain to include it)"
fi

echo "OK — all checks passed"
