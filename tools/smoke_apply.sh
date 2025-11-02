#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT_DIR/.venv/bin/python3"; [ -x "$PY" ] || PY="$(command -v python3 || command -v python)"

WORK="$(mktemp -d /tmp/ha_apply_smoke.XXXXXX)"
rsync -a --delete "$ROOT_DIR"/ "$WORK"/ >/dev/null
cd "$WORK"

git init -q
git config user.name "Smoke Test"
git config user.email "smoke@example.local"
git add -A
git commit -q -m "baseline"

TARGET="src/hybrid_agent/__init__.py"; [ -f "$TARGET" ] || TARGET="src/hybrid_agent/cli.py"
mkdir -p workspace
echo "# smoke-apply-ok" >> "$TARGET"
git diff > workspace/last.diff
git checkout -- "$TARGET"

export PYTHONPATH="$PWD/src"
set +e
OUT="$("$PY" -m hybrid_agent.cli apply 2>&1)"
RC=$?
set -e

echo "$OUT"
echo "[INFO] Tail of $TARGET after apply:"; tail -n 1 "$TARGET"
echo "[INFO] Git status:"; git status --porcelain || true

# Optional quick tests
"$PY" -m pytest -q || true

exit $RC
