from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shlex
import shutil
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

try:  # Python 3.11+
    import tomllib  # type: ignore[import]
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    try:
        import tomli as tomllib  # type: ignore[import,no-redef]
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]

from hybrid_agent import __version__
from hybrid_agent.loop import solve_request

DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_OLLAMA_MODEL = "phi3:mini"
DEFAULT_CODEX_MODELS = "api:ollama:phi3:mini,api:ollama:codellama:7b-instruct"

SESSION_FILE = Path("workspace") / "session.json"
CACHE_DIR_NAME = Path("workspace") / "cache"


def _ensure_workspace(root: Path) -> Path:
    ws = root / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def _resolve_path(root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve()


def _load_toml(path: Path) -> dict:
    if tomllib is None:
        return {}
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as exc:  # type: ignore[attr-defined]
        print(f"[WARN] Failed to parse config {path}: {exc}", file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


def _load_config(root: Path, args: argparse.Namespace) -> dict:
    candidates: list[Path] = []
    if getattr(args, "config", None):
        resolved = _resolve_path(root, args.config)
        if resolved:
            candidates.append(resolved)
    elif os.environ.get("HYBRID_AGENT_CONFIG"):
        resolved = _resolve_path(root, os.environ["HYBRID_AGENT_CONFIG"])
        if resolved:
            candidates.append(resolved)
    else:
        candidates.append(root / "config" / "hybrid_agent.toml")

    for path in candidates:
        if path.exists():
            cfg = _load_toml(path)
            cfg["_path"] = str(path)
            return cfg
    return {}


def _session_path(root: Path) -> Path:
    return root / SESSION_FILE


def _load_session(root: Path) -> dict:
    path = _session_path(root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_session(root: Path, payload: dict) -> None:
    path = _session_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    sanitized = {k: v for k, v in payload.items() if v is not None}
    path.write_text(
        json.dumps(sanitized, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _load_preamble(
    root: Path, args: argparse.Namespace, config: dict, session: dict
) -> str | None:
    pieces: list[str] = []

    env_text = os.environ.get("HYBRID_AGENT_PREAMBLE", "")
    if env_text.strip():
        pieces.append(env_text.strip())

    cfg_text = config.get("prompt_preamble")
    if isinstance(cfg_text, str) and cfg_text.strip():
        pieces.append(cfg_text.strip())

    session_path = session.get("preamble_file")
    candidate_path = _resolve_path(root, getattr(args, "preamble_file", None))
    if candidate_path is None and session_path:
        candidate_path = _resolve_path(root, session_path)
    if candidate_path is None and isinstance(config.get("preamble_file"), str):
        candidate_path = _resolve_path(root, config["preamble_file"])
    if candidate_path is None:
        default = root / "config" / "preamble.txt"
        candidate_path = default if default.exists() else None

    if candidate_path and candidate_path.exists():
        try:
            file_text = candidate_path.read_text(encoding="utf-8")
            if file_text.strip():
                pieces.append(file_text.strip())
        except OSError as exc:
            print(
                f"[WARN] Unable to read preamble file {candidate_path}: {exc}",
                file=sys.stderr,
            )

    if pieces:
        return "\n\n".join(pieces)
    return None


def _expand_weighted_models(spec) -> str:
    if not spec:
        return ""
    entries: list[str] = []
    if isinstance(spec, str):
        tokens = [token.strip() for token in spec.split(",") if token.strip()]
    elif isinstance(spec, list):
        tokens = [str(token).strip() for token in spec if str(token).strip()]
    else:
        return str(spec)

    for token in tokens:
        if "|" in token:
            model, weight = token.rsplit("|", 1)
        else:
            model, weight = token, "1"
        model = model.strip()
        try:
            count = max(1, int(weight))
        except ValueError:
            count = 1
        entries.extend([model] * count)
    return ",".join(entries) if entries else ""


def _expand_context_globs(root: Path, patterns: list[str]) -> list[str]:
    results: list[str] = []
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file():
                try:
                    rel = path.relative_to(root)
                except ValueError:
                    rel = path
                results.append(str(rel))
    return results


def _infer_related_files(files: list[str], root: Path) -> list[str]:
    related: set[str] = set()
    for entry in files:
        path = Path(entry)
        if not path.is_absolute():
            path = (root / path).resolve()
        if not path.exists():
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue

        if rel.suffix == ".py":
            dir_path = rel.parent
            stem = rel.stem
            candidates = [
                dir_path / f"test_{stem}.py",
                dir_path / f"{stem}_test.py",
            ]
            tests_dir = Path("tests")
            if stem.startswith("test_"):
                base = stem[5:]
                candidates.append(tests_dir / f"{stem}.py")
                candidates.append(tests_dir / f"{base}_test.py")
            else:
                candidates.append(tests_dir / dir_path / f"test_{stem}.py")
                candidates.append(tests_dir / f"test_{stem}.py")
                candidates.append(tests_dir / f"{stem}_test.py")

            for candidate in candidates:
                candidate_path = root / candidate
                if candidate_path.exists() and candidate_path.is_file():
                    related.add(str(candidate))
    return sorted(related)


def _apply_routing(effective: dict, files: list[str], config: dict) -> None:
    rules = config.get("routing_rules") or []
    if not isinstance(rules, list):
        return

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        pattern = rule.get("pattern")
        if not pattern:
            continue
        matches = any(
            fnmatch.fnmatch(file, pattern) or fnmatch.fnmatch(Path(file).name, pattern)
            for file in files
        )
        if not matches:
            continue
        if "ollama_model" in rule:
            effective["ollama_model"] = rule["ollama_model"]
        if "codex_models" in rule:
            effective["codex_models"] = rule["codex_models"]
        if "max_ollama_attempts" in rule:
            try:
                effective["max_ollama_attempts"] = int(rule["max_ollama_attempts"])
            except (TypeError, ValueError):
                pass


def _diff_summary(diff_text: str) -> dict:
    files: list[str] = []
    additions = 0
    deletions = 0
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            files.append(line[6:].strip())
        elif line.startswith("+++ /dev/null"):
            continue
        elif line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return {
        "files": sorted(set(files)),
        "additions": additions,
        "deletions": deletions,
    }


def _files_from_diff(diff_text: str) -> list[str]:
    files: set[str] = set()
    for line in diff_text.splitlines():
        if line.startswith("--- a/"):
            old_path = line[6:].strip()
            if old_path != "/dev/null":
                files.add(old_path)
        elif line.startswith("+++ b/"):
            new_path = line[6:].strip()
            if new_path != "/dev/null":
                files.add(new_path)
    return sorted(files)


def _copy_to_clipboard(text: str) -> bool:
    try:
        if sys.platform == "darwin":
            proc = subprocess.run(["pbcopy"], input=text, text=True)  # nosec B603 B607
            return proc.returncode == 0
        if sys.platform.startswith("win"):
            proc = subprocess.run(["clip"], input=text, text=True)  # nosec B603 B607
            return proc.returncode == 0
        if sys.platform.startswith("linux"):
            for tool in ("xclip", "xsel"):
                if shutil.which(tool):
                    if tool == "xclip":
                        proc = subprocess.run(
                            ["xclip", "-selection", "clipboard"],
                            input=text,  # nosec B603 B607
                            text=True,
                        )
                    else:
                        proc = subprocess.run(
                            ["xsel", "--clipboard", "--input"],
                            input=text,  # nosec B603 B607
                            text=True,
                        )
                    return proc.returncode == 0
    except Exception:  # nosec B110
        pass  # nosec B110
    return False


def _print_diff_preview(diff_text: str, context_lines: int) -> None:
    if context_lines <= 0:
        return
    lines = diff_text.splitlines()
    if not lines:
        print("[PREVIEW] Diff is empty.")
        return
    head = lines[:context_lines]
    tail = lines[-context_lines:] if len(lines) > context_lines else []
    print(f"[PREVIEW] Showing first/last {context_lines} line(s):")
    for line in head:
        print(line)
    if tail and len(lines) > context_lines * 2:
        print("...")
    for line in tail:
        print(line)


def _ensure_git_branch(repo_root: Path, branch: str) -> tuple[bool, str]:
    if not branch:
        return True, ""
    try:
        current = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],  # nosec B603 B607
            cwd=str(repo_root),
            text=True,
            capture_output=True,
        )
    except FileNotFoundError:
        message = "[WARN] git not available; skipping branch management."
        print(message, file=sys.stderr)
        return False, message

    if current.returncode != 0:
        message = current.stderr.strip() or "[ERR] Unable to determine current branch."
        print(message, file=sys.stderr)
        return False, message

    current_branch = current.stdout.strip()
    if current_branch == branch:
        return True, f"[OK] Already on branch {branch}"

    exists = subprocess.run(
        ["git", "show-ref", "--verify", f"refs/heads/{branch}"],  # nosec B603 B607
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if exists.returncode == 0:
        checkout = subprocess.run(
            ["git", "checkout", branch],  # nosec B603 B607
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
    else:
        checkout = subprocess.run(
            ["git", "checkout", "-b", branch],  # nosec B603 B607
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )

    if checkout.returncode != 0:
        message = checkout.stderr.strip() or "[ERR] Unable to checkout branch."
        print(message, file=sys.stderr)
        return False, message
    return True, checkout.stdout.strip() or f"[OK] Switched to branch {branch}"


def _git_commit(repo_root: Path, message: str, files: list[str]) -> tuple[bool, str]:
    if not message:
        return True, ""
    try:
        add = subprocess.run(
            ["git", "add"] + (files if files else ["-A"]),  # nosec B603 B607,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        msg = "[WARN] git not available; skipping commit."
        print(msg, file=sys.stderr)
        return False, msg

    if add.returncode != 0:
        message_out = add.stderr.strip() or "[ERR] git add failed."
        print(message_out, file=sys.stderr)
        return False, message_out

    commit = subprocess.run(
        ["git", "commit", "-m", message],  # nosec B603 B607
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if commit.returncode != 0:
        message_out = commit.stderr.strip() or "[ERR] git commit failed."
        print(message_out, file=sys.stderr)
        return False, message_out
    output = commit.stdout.strip() or "[OK] Commit created."
    print(output)
    return True, output


def _git_status(repo_root: Path) -> str:
    try:
        status = subprocess.run(
            ["git", "status", "--short"],  # nosec B603 B607
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return "[WARN] git not available."
    if status.returncode != 0:
        return status.stderr.strip() or "[ERR] git status failed."
    output = status.stdout.strip()
    return output or "[OK] Working tree clean."


def _git_stash_push(repo_root: Path) -> tuple[bool, str, bool]:
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],  # nosec B603 B607
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False, "[WARN] git not available; cannot stash.", False

    if status.returncode != 0:
        message = status.stderr.strip() or "[ERR] git status failed; cannot stash."
        return False, message, False

    if not status.stdout.strip():
        return True, "[OK] Working tree clean; no stash needed.", False

    stash = subprocess.run(
        [
            "git",
            "stash",
            "push",
            "-u",
            "-m",
            "HybridAgent temporary stash",
        ],  # nosec B603 B607
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if stash.returncode != 0:
        message = stash.stderr.strip() or "[ERR] git stash failed."
        return False, message, False
    message = stash.stdout.strip() or "[OK] Stashed working tree."
    return True, message, True


def _git_stash_pop(repo_root: Path) -> tuple[bool, str]:
    try:
        pop = subprocess.run(
            ["git", "stash", "pop"],  # nosec B603 B607
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False, "[WARN] git not available; cannot restore stash."

    if pop.returncode != 0:
        message = pop.stderr.strip() or "[ERR] git stash pop failed."
        return False, message
    return True, pop.stdout.strip() or "[OK] Restored previous working tree."


def _run_post_hooks(repo_root: Path, hooks: list[str]) -> list[str]:
    messages: list[str] = []
    for hook in hooks:
        hook = hook.strip()
        if not hook:
            continue
        args = hook if isinstance(hook, (list, tuple)) else shlex.split(str(hook))
        proc = subprocess.run(
            args,  # nosec B603  # nosec B603
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            stdout = proc.stdout.strip()
            detail = stderr or stdout or "no output"
            messages.append(f"[ERR] Post-hook failed ({hook}): {detail}")
        else:
            stdout = proc.stdout.strip()
            detail = stdout or "completed."
            messages.append(f"[OK] Post-hook ({hook}) {detail}")
    return messages


def _apply_diff_text(
    diff_text: str, repo_root: Path, preview: bool = False
) -> tuple[int, str]:
    """Apply a unified diff to repo_root, optionally previewing with git apply --check."""
    normalized = diff_text.replace("\r\n", "\n")
    patch_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            suffix=".patch",
        ) as tmp:
            tmp.write(normalized)
            patch_path = Path(tmp.name)

        check = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "apply",
                "--check",
                str(patch_path),
            ],  # nosec B603 B607
            capture_output=True,
            text=True,
        )
        if check.returncode != 0:
            detail = (
                check.stderr.strip()
                or check.stdout.strip()
                or "git apply --check failed."
            )
            return 1, f"[ERR] git apply --check failed: {detail}"

        if preview:
            return 0, "[OK] Diff validated (preview only)."

        apply_proc = subprocess.run(
            ["git", "-C", str(repo_root), "apply", str(patch_path)],  # nosec B603 B607
            capture_output=True,
            text=True,
        )
        if apply_proc.returncode != 0:
            detail = (
                apply_proc.stderr.strip()
                or apply_proc.stdout.strip()
                or "git apply failed."
            )
            return 1, f"[ERR] git apply failed: {detail}"
        return 0, "[OK] Diff applied."
    finally:
        if patch_path is not None:
            try:
                patch_path.unlink(missing_ok=True)
            except Exception:  # nosec B110
                pass


# nosec B110
def _compute_cache_key(
    prompt: str,
    preamble: str | None,
    files: list[str],
    stdin_text: str | None,
    effective: dict,
) -> str:
    hasher = hashlib.sha256()
    hasher.update(prompt.encode("utf-8"))
    if preamble:
        hasher.update(preamble.encode("utf-8"))
    hasher.update("\n".join(files).encode("utf-8"))
    if stdin_text:
        hasher.update(stdin_text.encode("utf-8"))
    hasher.update(str(effective["stdin_label"]).encode("utf-8"))
    hasher.update(str(effective["ollama_model"]).encode("utf-8"))
    hasher.update(str(effective["codex_models"]).encode("utf-8"))
    hasher.update(str(effective["max_ollama_attempts"]).encode("utf-8"))
    return hasher.hexdigest()


def _build_effective_args(
    root: Path,
    args: argparse.Namespace,
    config: dict,
    session: dict,
) -> dict:
    effective: dict[str, Any] = {}

    def pick(option, session_key, cfg_key, default):
        if option is not None:
            return option
        if session_key in session:
            return session[session_key]
        return config.get(cfg_key, default)

    def pick_float(option, session_key, cfg_key, default):
        value = pick(option, session_key, cfg_key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def pick_int(option, session_key, cfg_key, default):
        value = pick(option, session_key, cfg_key, default)
        if value in (None, ""):
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    effective["max_ollama_attempts"] = int(
        pick(
            args.max_ollama_attempts,
            "max_ollama_attempts",
            "max_ollama_attempts",
            DEFAULT_MAX_ATTEMPTS,
        )
    )
    effective["ollama_model"] = pick(
        args.ollama_model,
        "ollama_model",
        "ollama_model",
        DEFAULT_OLLAMA_MODEL,
    )
    effective["codex_models"] = pick(
        args.codex_models,
        "codex_models",
        "codex_models",
        DEFAULT_CODEX_MODELS,
    )
    effective["ollama_backoff_initial"] = max(
        0.0,
        pick_float(
            args.ollama_backoff_initial,
            "ollama_backoff_initial",
            "ollama_backoff_initial",
            0.25,
        ),
    )
    effective["ollama_backoff_multiplier"] = max(
        1.0,
        pick_float(
            args.ollama_backoff_multiplier,
            "ollama_backoff_multiplier",
            "ollama_backoff_multiplier",
            2.0,
        ),
    )
    effective["ollama_backoff_max"] = max(
        0.0,
        pick_float(
            args.ollama_backoff_max,
            "ollama_backoff_max",
            "ollama_backoff_max",
            5.0,
        ),
    )
    effective["codex_backoff_initial"] = max(
        0.0,
        pick_float(
            args.codex_backoff_initial,
            "codex_backoff_initial",
            "codex_backoff_initial",
            0.5,
        ),
    )
    effective["codex_backoff_multiplier"] = max(
        1.0,
        pick_float(
            args.codex_backoff_multiplier,
            "codex_backoff_multiplier",
            "codex_backoff_multiplier",
            2.0,
        ),
    )
    effective["codex_backoff_max"] = max(
        0.0,
        pick_float(
            args.codex_backoff_max,
            "codex_backoff_max",
            "codex_backoff_max",
            5.0,
        ),
    )
    effective["stdin_label"] = pick(
        args.stdin_label, "stdin_label", "stdin_label", "stdin.txt"
    )

    cfg_globs = config.get("context_globs")
    session_globs = session.get("context_globs")
    context_globs: list[str] = []
    if isinstance(cfg_globs, list):
        context_globs.extend(str(pattern) for pattern in cfg_globs)
    if isinstance(session_globs, list) and not getattr(args, "context_glob", None):
        context_globs.extend(str(pattern) for pattern in session_globs)
    if getattr(args, "context_glob", None):
        context_globs.extend(args.context_glob)
    effective["context_globs"] = context_globs

    infer_val = args.infer_related
    if infer_val is None:
        infer_val = session.get("infer_related")
    if infer_val is None:
        infer_val = config.get("infer_related_files", True)
    effective["infer_related"] = bool(infer_val)

    preview_context = pick(
        args.preview_context, "preview_context", "preview_context", 0
    )
    try:
        effective["preview_context"] = max(0, int(preview_context))
    except (TypeError, ValueError):
        effective["preview_context"] = 0

    clipboard_setting = args.clipboard
    if clipboard_setting is None:
        clipboard_setting = session.get("clipboard")
    if clipboard_setting is None:
        clipboard_setting = config.get("clipboard", False)
    effective["clipboard"] = bool(clipboard_setting)

    apply_mode = args.apply_mode
    if apply_mode is None:
        apply_mode = session.get("apply_mode")
    if apply_mode is None:
        apply_mode = config.get("apply_mode")
    if apply_mode is None and (args.apply or config.get("apply_by_default")):
        apply_mode = "always"
    if apply_mode not in {"never", "ask", "always"}:
        apply_mode = "never"
    effective["apply_mode"] = apply_mode
    effective["apply_preview"] = bool(
        pick(args.apply_preview, "apply_preview", "apply_preview", False)
    )

    log_file = args.log_file or session.get("log_file") or config.get("log_file")
    effective["log_file"] = _resolve_path(root, log_file) if log_file else None

    effective["apply_branch"] = pick(
        args.apply_branch, "apply_branch", "apply_branch", ""
    )
    effective["commit_message"] = pick(
        args.commit, "commit_message", "commit_message", ""
    )

    cache_flag = args.cache_responses
    if cache_flag is None:
        cache_flag = session.get("cache_responses")
    if cache_flag is None:
        cache_flag = config.get("cache_responses", True)
    effective["cache_responses"] = bool(cache_flag)

    cache_dir = args.cache_dir or session.get("cache_dir") or config.get("cache_dir")
    cache_path = _resolve_path(root, cache_dir) if cache_dir else root / CACHE_DIR_NAME
    effective["cache_dir"] = cache_path
    archive_limit = pick_int(
        args.archive_max_entries,
        "archive_max_entries",
        "archive_max_entries",
        None,
    )
    if isinstance(archive_limit, int) and archive_limit <= 0:
        archive_limit = None
    effective["archive_max_entries"] = archive_limit
    cache_limit = pick_int(
        args.cache_max_entries,
        "cache_max_entries",
        "cache_max_entries",
        None,
    )
    if isinstance(cache_limit, int) and cache_limit <= 0:
        cache_limit = None
    effective["cache_max_entries"] = cache_limit

    prompt_template = (
        args.prompt_template
        or session.get("prompt_template")
        or config.get("prompt_template")
    )
    effective["prompt_template"] = (
        _resolve_path(root, prompt_template) if prompt_template else None
    )

    cfg_hooks = config.get("post_hooks")
    session_hooks = session.get("post_hooks", [])
    hooks: list[str] = []
    if isinstance(cfg_hooks, str):
        hooks.append(cfg_hooks)
    elif isinstance(cfg_hooks, list):
        hooks.extend(str(h) for h in cfg_hooks)
    if isinstance(session_hooks, list) and not getattr(args, "post_hook", None):
        hooks.extend(str(h) for h in session_hooks)
    if getattr(args, "post_hook", None):
        hooks.extend(args.post_hook)
    effective["post_hooks"] = [hook for hook in hooks if hook]

    git_status_flag = args.git_status
    if git_status_flag is None:
        git_status_flag = session.get("git_status")
    if git_status_flag is None:
        git_status_flag = config.get("git_status", False)
    effective["git_status"] = bool(git_status_flag)

    stash_flag = args.stash_unstaged
    if stash_flag is None:
        stash_flag = session.get("stash_unstaged")
    if stash_flag is None:
        stash_flag = config.get("stash_unstaged", False)
    effective["stash_unstaged"] = bool(stash_flag)

    effective["json"] = bool(args.json or config.get("json_output"))

    return effective


def _render_prompt_template(template_path: Path, context: Dict[str, Any]) -> str:
    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(
            f"[WARN] Unable to read prompt template {template_path}: {exc}",
            file=sys.stderr,
        )
        return context["prompt"]

    class SafeDict(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    return template.format_map(SafeDict(context))


def cmd_solve(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parents[2]
    _ensure_workspace(root)

    session = _load_session(root) if getattr(args, "repeat", False) else {}
    config = _load_config(root, args)
    effective = _build_effective_args(root, args, config, session)

    raw_prompt = args.prompt if args.prompt is not None else session.get("prompt")
    if not raw_prompt:
        print(
            "[ERR] Prompt is required (provide --prompt or use --repeat with a saved session).",
            file=sys.stderr,
        )
        return 2

    base_files: list[str] = []
    if args.repeat:
        base_files = session.get("files", []) or []
    initial_files = args.file or base_files
    context_files = list(dict.fromkeys(initial_files))
    if effective["context_globs"]:
        context_files.extend(_expand_context_globs(root, effective["context_globs"]))
    context_files = list(dict.fromkeys(context_files))

    if effective["infer_related"]:
        related = _infer_related_files(context_files, root)
        context_files.extend([f for f in related if f not in context_files])
    context_files = list(dict.fromkeys(context_files))

    _apply_routing(effective, context_files, config)

    stdin_text: str | None = None
    if getattr(args, "stdin", False):
        stdin_text = sys.stdin.read()
        if not stdin_text:
            print(
                "[WARN] --stdin was provided but no data was read from STDIN.",
                file=sys.stderr,
            )

    preamble = _load_preamble(root, args, config, session)

    template_path: Path | None = effective["prompt_template"]
    if template_path:
        template_context = {
            "prompt": raw_prompt,
            "files": "\n".join(context_files),
            "file_list": context_files,
            "stdin_label": effective["stdin_label"],
            "config_path": config.get("_path", ""),
        }
        final_prompt = _render_prompt_template(template_path, template_context)
    else:
        final_prompt = raw_prompt

    cache_enabled = effective["cache_responses"]
    cache_dir: Path = effective["cache_dir"]
    cache_key = None
    if cache_enabled:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = _compute_cache_key(
            final_prompt,
            preamble,
            context_files,
            stdin_text,
            effective,
        )

    cache_metadata = {
        "prompt": raw_prompt,
        "context_files": context_files,
        "stdin_label": effective["stdin_label"],
        "ollama_model": effective["ollama_model"],
        "codex_models": effective["codex_models"],
        "max_ollama_attempts": effective["max_ollama_attempts"],
        "prompt_template": str(template_path) if template_path else "",
    }

    if getattr(args, "context_plan", False):
        result = solve_request(
            prompt=final_prompt,
            files=context_files,
            max_ollama_attempts=effective["max_ollama_attempts"],
            ollama_model=effective["ollama_model"],
            codex_models=effective["codex_models"],
            workspace_dir=str(root / "workspace"),
            root_dir=str(root),
            ollama_backoff_initial=effective["ollama_backoff_initial"],
            ollama_backoff_multiplier=effective["ollama_backoff_multiplier"],
            ollama_backoff_max=effective["ollama_backoff_max"],
            codex_backoff_initial=effective["codex_backoff_initial"],
            codex_backoff_multiplier=effective["codex_backoff_multiplier"],
            codex_backoff_max=effective["codex_backoff_max"],
            archive_max_entries=effective["archive_max_entries"],
            cache_max_entries=effective["cache_max_entries"],
            stdin_text=stdin_text,
            stdin_label=effective["stdin_label"],
            preamble=preamble,
            log_file=None,
            plan_only=True,
        )
        payload = {
            "returncode": result.returncode,
            "message": result.message,
            "source": result.source,
            "prompt": result.diff_text,
            "files": context_files,
            "stdin_label": effective["stdin_label"] if stdin_text else None,
        }
        if effective["json"]:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(result.message)
            print("\n----- Prompt -----")
            print(result.diff_text)
        return result.returncode

    result = solve_request(
        prompt=final_prompt,
        files=context_files,
        max_ollama_attempts=effective["max_ollama_attempts"],
        ollama_model=effective["ollama_model"],
        codex_models=effective["codex_models"],
        workspace_dir=str(root / "workspace"),
        root_dir=str(root),
        ollama_backoff_initial=effective["ollama_backoff_initial"],
        ollama_backoff_multiplier=effective["ollama_backoff_multiplier"],
        ollama_backoff_max=effective["ollama_backoff_max"],
        codex_backoff_initial=effective["codex_backoff_initial"],
        codex_backoff_multiplier=effective["codex_backoff_multiplier"],
        codex_backoff_max=effective["codex_backoff_max"],
        stdin_text=stdin_text,
        stdin_label=effective["stdin_label"],
        preamble=preamble,
        log_file=str(effective["log_file"]) if effective["log_file"] else None,
        cache_dir=str(cache_dir) if cache_enabled else None,
        cache_key=cache_key,
        cache_metadata=cache_metadata,
        archive_max_entries=effective["archive_max_entries"],
        cache_max_entries=effective["cache_max_entries"],
    )

    session_payload = {
        "prompt": raw_prompt,
        "files": context_files,
        "stdin_label": effective["stdin_label"],
        "ollama_model": effective["ollama_model"],
        "codex_models": effective["codex_models"],
        "max_ollama_attempts": effective["max_ollama_attempts"],
        "ollama_backoff_initial": effective["ollama_backoff_initial"],
        "ollama_backoff_multiplier": effective["ollama_backoff_multiplier"],
        "ollama_backoff_max": effective["ollama_backoff_max"],
        "codex_backoff_initial": effective["codex_backoff_initial"],
        "codex_backoff_multiplier": effective["codex_backoff_multiplier"],
        "codex_backoff_max": effective["codex_backoff_max"],
        "apply_mode": effective["apply_mode"],
        "apply_preview": effective["apply_preview"],
        "context_globs": effective["context_globs"],
        "infer_related": effective["infer_related"],
        "prompt_template": (
            str(template_path.relative_to(root))
            if template_path and template_path.is_relative_to(root)
            else (str(template_path) if template_path else None)
        ),
        "cache_responses": cache_enabled,
        "cache_dir": (
            str(cache_dir.relative_to(root))
            if cache_dir.is_relative_to(root)
            else str(cache_dir)
        ),
        "cache_max_entries": effective["cache_max_entries"],
        "archive_max_entries": effective["archive_max_entries"],
        "preview_context": effective["preview_context"],
        "clipboard": effective["clipboard"],
        "post_hooks": effective["post_hooks"],
        "git_status": effective["git_status"],
        "stash_unstaged": effective["stash_unstaged"],
        "apply_branch": effective["apply_branch"],
        "commit_message": effective["commit_message"],
        "preamble_file": (
            getattr(args, "preamble_file", None) or session.get("preamble_file")
        ),
    }
    _save_session(root, session_payload)

    payload = {
        "returncode": result.returncode,
        "message": result.message,
        "source": result.source,
        "diff_text": result.diff_text,
        "applied": False,
        "files": context_files,
    }

    if result.returncode != 0:
        if effective["json"]:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(result.message, file=sys.stderr)
        return result.returncode

    diff_text = result.diff_text
    summary = _diff_summary(diff_text)
    payload["summary"] = summary
    touched_files = _files_from_diff(diff_text)
    payload["touched_files"] = touched_files

    if effective["diff_preview"] and not effective["json"]:
        _print_diff_preview(diff_text, effective["preview_context"])

    if effective["clipboard"] and not effective["json"]:
        if _copy_to_clipboard(diff_text):
            print("[OK] Diff copied to clipboard.")
        else:
            print("[WARN] Unable to copy diff to clipboard.", file=sys.stderr)

    if effective["json"]:
        payload["diff_text"] = diff_text
    else:
        print(diff_text, end="" if diff_text.endswith("\n") else "\n")
        if result.message:
            print(result.message, file=sys.stderr)

    if effective["git_status"] and not effective["json"]:
        status = _git_status(root)
        print("[GIT STATUS]")
        print(status)

    apply_rc = 0
    apply_messages: list[str] = []
    apply_mode = effective["apply_mode"]
    confirmed = apply_mode == "always"
    stash_applied = False

    if apply_mode == "ask" and not effective["json"]:
        response = input("Apply diff? [y/N]: ").strip().lower()
        confirmed = response in {"y", "yes"}
        if not confirmed:
            apply_messages.append("[INFO] Diff not applied.")

    if apply_mode != "never" and confirmed:
        if effective["stash_unstaged"]:
            stash_ok, stash_msg, stash_applied = _git_stash_push(root)
            apply_messages.append(stash_msg)
            if not stash_ok:
                apply_rc = 1

        branch_msg = ""
        if apply_rc == 0 and effective["apply_branch"]:
            branch_ok, branch_msg = _ensure_git_branch(root, effective["apply_branch"])
            if branch_msg:
                apply_messages.append(branch_msg)
            if not branch_ok:
                apply_rc = 1

        try:
            if apply_rc == 0:
                apply_rc, apply_msg = _apply_diff_text(
                    diff_text,
                    root,
                    preview=effective["apply_preview"],
                )
                apply_messages.append(apply_msg)
                if apply_rc == 0 and effective["commit_message"]:
                    commit_ok, commit_msg = _git_commit(
                        root,
                        effective["commit_message"],
                        touched_files,
                    )
                    apply_messages.append(commit_msg)
                    if not commit_ok:
                        apply_rc = 1

            if apply_rc == 0 and effective["post_hooks"]:
                post_hook_msgs = _run_post_hooks(root, effective["post_hooks"])
                apply_messages.extend(post_hook_msgs)
        finally:
            if stash_applied:
                pop_ok, pop_msg = _git_stash_pop(root)
                apply_messages.append(pop_msg)
                if not pop_ok and apply_rc == 0:
                    apply_rc = 1

        payload["applied"] = apply_rc == 0
        payload["apply_message"] = "; ".join(msg for msg in apply_messages if msg)
        if not effective["json"]:
            for msg in apply_messages:
                is_warning = msg.startswith("[ERR]") or msg.startswith("[WARN]")
                stream = sys.stderr if is_warning else sys.stdout
                print(msg, file=stream)
    elif apply_mode != "never":
        payload["apply_message"] = "; ".join(apply_messages)
    else:
        payload["apply_message"] = "[INFO] apply_mode=never; diff not applied."

    if effective["json"]:
        print(json.dumps(payload, ensure_ascii=False))

    return apply_rc if apply_rc != 0 else 0


def cmd_apply(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parents[2]
    ws = _ensure_workspace(repo_root)
    diff_path = ws / "last.diff"
    if not diff_path.exists():
        message = "[ERR] workspace/last.diff not found"
        print(message, file=sys.stderr)
        return 2

    raw = diff_path.read_bytes().replace(b"\r\n", b"\n")
    diff_text = raw.decode("utf-8", errors="replace")
    rc, msg = _apply_diff_text(diff_text, repo_root, preview=args.preview)
    stream = sys.stderr if rc != 0 else sys.stdout
    print(msg, file=stream)
    return rc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ha", description="HybridAgent CLI")
    parser.add_argument(
        "--version", action="version", version=f"HybridAgent {__version__}"
    )
    parser.add_argument("--config", help="Path to hybrid_agent.toml for defaults.")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    solve = subparsers.add_parser(
        "solve",
        help="Try Ollama for a unified diff, then escalate to Codex if needed.",
    )
    solve.add_argument(
        "--prompt",
        help="Instruction that asks for ONLY a unified diff.",
    )
    solve.add_argument(
        "--file",
        action="append",
        default=[],
        help="Optional file(s) to include in context.",
    )
    solve.add_argument(
        "--context-glob",
        action="append",
        help="Include context files matching a glob pattern.",
    )
    solve.add_argument(
        "--context-plan",
        action="store_true",
        help="Show the prompt/context without contacting models.",
    )
    solve.add_argument(
        "--stdin",
        action="store_true",
        help="Read additional context from STDIN.",
    )
    solve.add_argument(
        "--stdin-label",
        default=None,
        help="Virtual filename used for STDIN content.",
    )
    solve.add_argument(
        "--max-ollama-attempts",
        type=int,
        default=None,
        help="Ollama attempts (default 5 or config).",
    )
    solve.add_argument("--ollama-model", default=None, help="Ollama model to query.")
    solve.add_argument(
        "--codex-models",
        default=None,
        help="Comma-separated CodexCLI models.",
    )
    solve.add_argument(
        "--ollama-backoff-initial",
        type=float,
        default=None,
        help="Initial seconds before retrying Ollama (default 0.25).",
    )
    solve.add_argument(
        "--ollama-backoff-multiplier",
        type=float,
        default=None,
        help="Multiplier for Ollama retry backoff (default 2.0).",
    )
    solve.add_argument(
        "--ollama-backoff-max",
        type=float,
        default=None,
        help="Maximum seconds between Ollama retries (default 5.0).",
    )
    solve.add_argument(
        "--codex-backoff-initial",
        type=float,
        default=None,
        help="Initial seconds before escalating to CodexCLI (default 0.5).",
    )
    solve.add_argument(
        "--codex-backoff-multiplier",
        type=float,
        default=None,
        help="Multiplier for Codex fallback delay (default 2.0).",
    )
    solve.add_argument(
        "--codex-backoff-max",
        type=float,
        default=None,
        help="Maximum seconds before Codex fallback (default 5.0).",
    )
    infer_group = solve.add_mutually_exclusive_group()
    infer_group.add_argument(
        "--infer-related",
        action="store_true",
        dest="infer_related",
        help="Enable auto-related-file discovery.",
    )
    infer_group.add_argument(
        "--no-infer-related",
        action="store_false",
        dest="infer_related",
        help="Disable auto-related-file discovery.",
    )
    solve.set_defaults(infer_related=None)
    solve.add_argument(
        "--preview-context",
        type=int,
        default=None,
        help="Show N context lines from the diff.",
    )
    solve.add_argument(
        "--diff-preview",
        action="store_true",
        help="Print a summary and context preview",
    )
    solve.add_argument(
        "--clipboard",
        dest="clipboard",
        action="store_true",
        help="Copy the resulting diff to the clipboard.",
    )
    solve.add_argument(
        "--no-clipboard",
        dest="clipboard",
        action="store_false",
        help="Do not copy the diff to the clipboard.",
    )
    solve.set_defaults(clipboard=None)
    solve.add_argument(
        "--apply",
        action="store_true",
        help="Apply the resulting diff with patch -p1.",
    )
    solve.add_argument(
        "--apply-mode",
        choices=["never", "ask", "always"],
        help="Control whether to apply the diff: never, ask, or always.",
    )
    solve.add_argument(
        "--apply-preview",
        action="store_true",
        help="Show git apply --stat before applying.",
    )
    solve.add_argument(
        "--apply-branch",
        help="Checkout/create the given branch before applying the diff.",
    )
    solve.add_argument(
        "--commit", help="Commit message to use after applying the diff."
    )
    solve.add_argument(
        "--prompt-template",
        help="Template file used to render the final prompt.",
    )
    solve.add_argument(
        "--post-hook",
        action="append",
        help="Shell command to run after a successful apply (repeatable).",
    )
    solve.add_argument(
        "--cache-responses",
        dest="cache_responses",
        action="store_true",
        help="Enable caching of model responses.",
    )
    solve.add_argument(
        "--no-cache-responses",
        dest="cache_responses",
        action="store_false",
        help="Disable caching of model responses.",
    )
    solve.set_defaults(cache_responses=None)
    solve.add_argument(
        "--cache-dir",
        help="Directory to store cached responses (default workspace/cache).",
    )
    solve.add_argument(
        "--cache-max-entries",
        type=int,
        default=None,
        help="Maximum cached diff entries to keep (default unlimited).",
    )
    solve.add_argument(
        "--archive-max-entries",
        type=int,
        default=None,
        help="Maximum archived diffs to retain (default unlimited).",
    )
    solve.add_argument(
        "--git-status",
        dest="git_status",
        action="store_true",
        help="Show git status before attempting to apply.",
    )
    solve.add_argument(
        "--no-git-status",
        dest="git_status",
        action="store_false",
        help="Do not show git status before applying.",
    )
    solve.set_defaults(git_status=None)
    solve.add_argument(
        "--stash-unstaged",
        dest="stash_unstaged",
        action="store_true",
        help="Stash unstaged changes before applying and restore afterwards.",
    )
    solve.add_argument(
        "--no-stash-unstaged",
        dest="stash_unstaged",
        action="store_false",
        help="Skip automatic stashing.",
    )
    solve.set_defaults(stash_unstaged=None)
    solve.add_argument("--log-file", help="Custom run log path.")
    solve.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON output instead of plain text.",
    )
    solve.add_argument(
        "--repeat",
        action="store_true",
        help="Reuse the previous session's configuration.",
    )

    apply_parser = subparsers.add_parser(
        "apply",
        help="Apply workspace/last.diff with patch -p1.",
    )
    apply_parser.add_argument(
        "--preview",
        action="store_true",
        help="Run git apply --stat before patching.",
    )
    apply_parser.set_defaults(func=cmd_apply)

    solve.set_defaults(post_hook=None)
    solve.set_defaults(func=cmd_solve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
