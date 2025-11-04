# Phase 5 CLI Polish — `hybrid`

## Goals
- Ship a friendly CLI: `hybrid doctor`, `hybrid solve`, `hybrid plan`.
- Keep current behavior under the hood; expose a clean Typer interface.
- Colorized output, clear errors, and `--help` everywhere.

## Requirements
- Implement Typer app at `src/hybrid_agent/cli_app.py`:
  - `hybrid doctor` → run doctor routine, print pass/fail summary.
  - `hybrid solve --prompt "..." --file PATH [--context-plan] [--max-ollama-attempts N]`
  - `hybrid plan  --prompt "..." --file PATH` (plan-only; no apply)
- Reuse `loop.solve_request(...)` and existing helpers; respect env (`OLLAMA_HOST`, Codex fallback).
- Exit codes: 0=ok; 2=non-diff; 3=validator reject; 10=model down.
- Nice progress + final summary (source, message).

## Packaging
- Console entry:
  - setuptools: `entry_points={'console_scripts': ['hybrid=hybrid_agent.cli_app:app']}`

## Acceptance
- `python -m pip install typer rich` (if not already)
- `python -m hybrid_agent.cli_app --help` works
- `hybrid doctor` works
- `hybrid solve --prompt "Refactor app.py" --file app.py --context-plan` prints plan
- `hybrid solve --prompt "Refactor app.py" --file app.py` applies a unified diff and reports source + validator result
