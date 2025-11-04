# HybridAgent

Local-first CLI that asks Ollama to draft git-style unified diffs before falling back to CodexCLI. The tool keeps everything offline-friendly and logs each run for later inspection.

## No-Install Development

Run straight from the repo (no editable install required):

```bash
PYTHONPATH=src python3 -m hybrid_agent.cli --version
bash scripts/ha.sh --version
bash scripts/ha.sh solve --prompt "Return ONLY a git-style unified diff that changes hello.py to print('hello')." --file hello.py
```

You can pipe extra context from STDIN and auto-apply results:

```bash
cat hello.py | bash scripts/ha.sh solve --stdin --stdin-label hello.py \
  --prompt "Return ONLY a unified diff that uppercases the greeting." --apply
```

Add `--apply-preview` to show `git apply --stat` before applying a diff.
Use `--apply-mode ask` to review the diff interactively, or `--apply-mode never` to keep things read-only.

## CLI Quickstart (`hybrid`)

The Typer-based CLI wraps the legacy `ha` command with colorized output and friendlier help:

```bash
hybrid --help
hybrid doctor
hybrid plan --prompt "Return ONLY a diff that replaces the greeting." --file hello.py
hybrid solve --prompt "Ship the diff." --file hello.py --apply
```

`hybrid plan` always includes `--context-plan`, so it produces the full system prompt and context without reaching out to Ollama or codex-local.

`make` helpers:

```bash
make run
make solve P='Return ONLY a unified diff…' F='--file hello.py'
make test
make lint
make typecheck
make security
make audit
make hooks    # calls tools/post_hooks.sh run
make ci       # runs lint + typecheck + security + audit + test
```

`nox` mirrors the same workflow in isolated virtualenvs:

```bash
nox -s lint typecheck tests
nox -s security audit
```

Install the curated git hooks:

```bash
pip install pre-commit
pre-commit install --install-hooks
```

## Environment Check & Dry Runs

Make sure the local prerequisites are in place before you attempt a real solve:

```bash
hybrid doctor
```

The doctor command checks for `git`, `patch`, `ollama`, the `codex-local` CLI, and whether Ollama is listening on `http://127.0.0.1:11434/`. If anything is missing you will get a concise hint (with color) on how to fix it.

You can compose the full system prompt and context without talking to any models by adding `--context-plan`:

```bash
hybrid plan --prompt "Return ONLY a diff that replaces the greeting." \
  --file hello.py \
  --max-ollama-attempts 0
```

Copy the `[PLAN]` output into the model of your choice if you want to drive the loop manually, or keep the flag off once Ollama/Codex are available.

## One-Line Install (pipx)

If you have [pipx](https://github.com/pypa/pipx) available, you can install the CLI from this repository with a single command:

```bash
pipx install --suffix hybridagent "$(pwd)"
```

Run the command from the repository root to publish `hybrid` and `ha` onto your PATH without touching the system Python. Replace `$(pwd)` with a Git URL if you have a remote.

## Prompt Guardrails

HybridAgent always enforces a strict diff-only system prompt. You can append additional guidance by either:

- creating `config/preamble.txt` in the repo root, or
- setting the `HYBRID_AGENT_PREAMBLE` environment variable, or
- passing `--preamble-file path/to/custom.txt`.

## Session & Repeat

Every successful run stores its inputs in `workspace/session.json`. Re-run the same configuration with:

```bash
bash scripts/ha.sh solve --repeat --prompt "Tweak the last change slightly."
```

CLI flags still override the saved session, so you can mix `--repeat` with new options.

## Prompt Templates

Use `--prompt-template templates/guardrails.txt` (or `prompt_template = "templates/guardrails.txt"` in TOML) to wrap the raw prompt. Templates can reference:

- `{prompt}` – original prompt text  
- `{files}` – newline-separated context files  
- `{file_list}` – Python list of context files  
- `{stdin_label}` – name assigned to STDIN content  
- `{config_path}` – path to the active config file

Missing placeholders are left intact, making templates easy to iterate on.

## Config Defaults

Optional defaults live in `config/hybrid_agent.toml` (override via `--config` or `HYBRID_AGENT_CONFIG`). Example:

```toml
max_ollama_attempts = 3
ollama_model = "phi3:mini"
codex_models = "api:ollama:phi3:mini,api:ollama:codellama:7b-instruct"
prompt_preamble = "Never edit README.md."
log_file = "workspace/run_log.jsonl"
apply_by_default = false
apply_preview = true
json_output = false
infer_related_files = true
apply_mode = "ask"
apply_branch = "hybridagent/update"
commit_message = "Apply HybridAgent diff"
clipboard = true
preview_context = 5
cache_responses = true
post_hooks = ["bash tools/post_hooks.sh run"]

[context]
context_globs = ["src/**/*.py", "tests/**/*.py"]
context_plan = true

[tooling]
require_ripgrep = true
require_ctags = true

[[routing_rules]]
pattern = "*.ts"
ollama_model = "typescript-specialist"
codex_models = "api:ollama:codellama:7b-instruct"
```

Environment variables still win (`HYBRID_AGENT_PREAMBLE`, `HYBRID_AGENT_CONFIG`).

Weighted Codex models are supported via `codex_weighted_models = ["modelA|3", "modelB|1"]` (or the `--codex-models "modelA|3,modelB|1"` CLI flag).

## Response Caching

HybridAgent caches successful diffs under `workspace/cache/` keyed by prompt, context, and model options. Disable with `--no-cache-responses` (or `cache_responses = false`), or supply a custom directory via `--cache-dir`. Cached diffs still flow through validators and archival so the workflow stays consistent.

## Structured Output & Automation

Pass `--json` to receive machine-readable output:

```bash
bash scripts/ha.sh solve --prompt "..." --json | jq .
```

The payload includes `returncode`, `message`, `source`, `diff_text`, and `applied`.

## Diff History, Logging & Validation

Every successful run writes the diff to both `workspace/last.diff` and a timestamped archive under `workspace/diffs/`. Runs append JSON lines to `workspace/run_log.jsonl` (or a custom path via `--log-file`) capturing backend attempts, models, return codes, and whether a diff was coerced.

Place an optional validator at `config/validate_diff.py` to veto or rewrite diffs. It receives the proposed diff on STDIN; exit code `0` approves (stdout can emit a replacement diff), while a non-zero exit rejects the change and surfaces stderr/stdout as the failure message.

## Diff Previews, Clipboard & Hooks

- `--diff-preview --preview-context 5` prints a small snippet prior to the full diff.  
- `--clipboard` copies the diff to your system clipboard (macOS, Windows, Linux with `xclip`/`xsel`).  
- Post-apply automation defaults to `bash tools/post_hooks.sh run`, which fans out to lint, type, test, security, and audit stages (skipping any tools you have not installed yet). Override with `--post-hook` or `post_hooks = [...]` in the TOML.

## Quality Gates & Safety Nets

- `make lint`, `make typecheck`, and `make hooks` are the fastest way to smoke-test a generated diff before committing.  
- The Hypothesis property tests (`tests/test_hypothesis_diff.py`) and optional Atheris fuzz harness (`tests/fuzz_diff_apply.py`) keep diff parsing hardened; they run automatically in CI.  
- Pre-commit hooks (`pre-commit install --install-hooks`) run Ruff, Black, Isort, and Bandit locally; invoke manual stages (`pre-commit run --hook-stage manual pytest`) for slower checks.  
- CI now enforces formatting, static analysis, security scans, and dependency audits via `.github/workflows/ci.yml`.  
- Prefer `nox -s lint typecheck tests security audit` for a hermetic, reproducible toolchain when you want to avoid polluting your main environment.

## Security & Supply-Chain Scanning

- `make security` runs Bandit and Semgrep (with a fallback to the community `auto` ruleset).  
- `make audit` runs both `pip-audit` and `safety` so you catch Python advisories early.  
- In CI the same scanners fail the build if an issue is found; locally you can allow them to warn by tweaking `tools/post_hooks.sh`.

## Retrieval & Context Helpers

- Set `context.context_plan = true` (default) so HybridAgent previews which files it will feed into the prompt.  
- Install `ripgrep` (`rg`) and `universal-ctags` to unlock fast symbol search; toggle the `tooling.require_ripgrep` / `require_ctags` flags in `hybrid_agent.toml` to make them mandatory.  
- Populate `context_globs` in `hybrid_agent.toml` to bias context collection toward high-signal directories (already seeded with `src`, `tests`, and `tools`).  
- Pair this repo with local coder models such as `qwen2.5-coder`, `deepseek-coder`, or `starcoder2` in Ollama for a stronger ensemble before falling back to CodexCLI.

## Editor Helpers

- VS Code: import `scripts/vscode-tasks.json` into `.vscode/tasks.json` to run HybridAgent via `Ctrl+Shift+B`.
- Vim: source `scripts/vim-hybridagent-command.vim` to register `:HybridAgentSolve` (uses the shell wrapper).
- Both helpers respect the new `--context-plan` switch so you can preview prompts without model calls.

## Development (optional, local)

Editable installs remain useful for IDEs and packaging workflows:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
ha --version
```

## Pytest Fixture

For contract tests around guardrails, import the `hybridagent_validator` fixture (see `tests/conftest.py`). It materialises a temporary `config/validate_diff.py` so you can assert that diffs are accepted or rejected during CI.

## Git Workflows

- `--git-status` shows `git status --short` before attempting an apply.  
- `--stash-unstaged` temporarily stashes dirty worktrees and restores them afterwards.  
- `--apply-branch feature/refine` checks out (or creates) a branch prior to patching.  
- `--commit "Summarise the change"` stages touched files and commits once the diff lands.
