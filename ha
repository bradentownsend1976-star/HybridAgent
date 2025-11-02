#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -x "$ROOT_DIR/.venv/bin/ha" ]; then
  exec "$ROOT_DIR/.venv/bin/ha" "$@"
else
  PY="$(command -v python3 || command -v python)"
  export PYTHONPATH="$ROOT_DIR/src"
  exec "$PY" -m hybrid_agent.cli "$@"
fi
