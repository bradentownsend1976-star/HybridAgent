#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
# Prefer project venv if present
if [ -f "$HERE/.venv/bin/activate" ]; then
  . "$HERE/.venv/bin/activate"
fi

echo "[INFO] Running CodexCLI post-apply suite: nox -s lint typecheck tests"
# nox might not be globally installed; ensure it's available
python -m pip -q install nox >/dev/null || true
nox -s lint typecheck tests
