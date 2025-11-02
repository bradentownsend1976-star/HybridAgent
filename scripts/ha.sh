#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [ -f "${REPO_ROOT}/.venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  . "${REPO_ROOT}/.venv/bin/activate" || true
fi

# ensure src/ is importable (src layout)
if [ -n "${PYTHONPATH:-}" ]; then
  export PYTHONPATH="${REPO_ROOT}/src:${PYTHONPATH}"
else
  export PYTHONPATH="${REPO_ROOT}/src"
fi

exec python3 -m hybrid_agent.cli "$@"
