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

`make` helpers:

```bash
make run
make solve P='Return ONLY a unified diff…' F='--file hello.py'
make test
```

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
context_globs = ["docs/**/*.md"]
infer_related_files = true
apply_mode = "ask"
apply_branch = "hybridagent/update"
commit_message = "Apply HybridAgent diff"
clipboard = true
preview_context = 5
cache_responses = true
post_hooks = ["pytest -q"]

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
- `--post-hook "pytest -q"` runs a shell command after a successful apply; repeat the flag for multiple hooks.

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
