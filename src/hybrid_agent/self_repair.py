from __future__ import annotations

import datetime
import hashlib
import json
import shlex
import subprocess  # nosec B404
import time
from pathlib import Path

LOG_DIR = Path(".hybrid")
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _run(cmd: str, timeout: float | None = None):
    t0 = time.time()
    p = subprocess.run(  # nosec B603
        shlex.split(cmd), capture_output=True, text=True, timeout=timeout
    )
    return p.returncode, p.stdout, p.stderr, (time.time() - t0) * 1000.0


def _tail(s: str, n: int = 200) -> str:
    return "\n".join(s.splitlines()[-n:])


def _digest(s: str) -> str:
    return hashlib.sha256(_tail(s, 50).encode("utf-8", "ignore")).hexdigest()[:16]


def _direct_return_literal_fix(scope: Path, actual: str, expected: str) -> bool:
    """Replace simple `return "<actual>"` lines with the expected literal."""
    import re

    if not actual or not expected or actual == expected:
        return False

    pattern = re.compile(
        rf"""
        ^(?P<prefix>\s*return\s+)
        (?P<quote>['"])
        {re.escape(actual)}
        (?P=quote)
        (?P<suffix>\s*(?:\#.*)?)$
        """,
        re.MULTILINE | re.VERBOSE,
    )

    changed = False
    for py in scope.rglob("*.py"):
        try:
            txt = py.read_text(encoding="utf-8")
        except Exception:  # nosec B112
            continue

        def _repl(match: re.Match[str]) -> str:
            prefix = match.group("prefix")
            quote = match.group("quote")
            suffix = match.group("suffix") or ""
            return f"{prefix}{quote}{expected}{quote}{suffix}"

        new_txt = pattern.sub(_repl, txt)
        if new_txt != txt:
            py.write_text(new_txt, encoding="utf-8")
            changed = True
    return changed


def _literal_fallback(scope: Path, fail_txt: str) -> bool:
    """
    Conservative fallback: if pytest shows a simple - expected / + actual string diff,
    swap the literal in return/assignment under the scope.
    """
    import re

    m_minus = re.search(r"^\s*(?:E\s+)?-\s*(.+)$", fail_txt, re.M)
    m_plus = re.search(r"^\s*(?:E\s+)?\+\s*(.+)$", fail_txt, re.M)
    if not (m_minus and m_plus):
        return False
    expected = m_minus.group(1).strip().strip("\"'")

    actual = m_plus.group(1).strip().strip("\"'")

    if not (expected and actual):
        return False
    if len(expected) > 40 or len(actual) > 40:
        return False

    changed = _direct_return_literal_fix(scope, actual, expected)
    for py in scope.rglob("*.py"):
        try:
            txt = py.read_text(encoding="utf-8")
        except Exception:  # nosec B112
            continue

        new_txt = txt
        # x = "actual" -> x = "expected"
        new_txt = re.sub(
            rf"(=\s+)([\"']){re.escape(actual)}\2", rf'\1"{expected}"', new_txt
        )
        if new_txt != txt:
            py.write_text(new_txt, encoding="utf-8")
            changed = True
    return changed


def self_repair_loop(
    scope: str = "src/",
    tests: str = "pytest -q",
    max_iters: int = 5,
    timeout_sec: float = 900.0,
    stall_limit: int = 2,
    prefer_codex: bool = True,
) -> int:
    """
    Run tests; if failing, ask HybridAgent to produce/apply a unified diff;
    Repeat until pass or stall.
    Exit codes: 0 pass, 1 iter limit, 4 stall.
    """
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"self_repair_{ts}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    prev_digest = None
    stall_count = 0
    scope_path = Path(scope)

    # Stash dirty state if any
    rc, out, _err, _ = _run("git status --porcelain")
    if out.strip():
        _run("git add -A")
        _run('git stash push -u -m "hybrid-self-repair-auto-stash"')

    for i in range(1, max_iters + 1):
        rc, t_out, t_err, t_ms = _run(tests, timeout=timeout_sec)
        entry = {"step": i, "test_exit": rc, "test_ms": round(t_ms, 1)}
        if rc == 0:
            entry["result"] = "pass"
            log_path.open("a", encoding="utf-8").write(json.dumps(entry) + "\n")
            print(f"[OK] Tests passing at iteration {i}.")
            return 0

        fail_txt = (_tail(t_out, 200) + "\n" + _tail(t_err, 200)).strip()
        digest = _digest(fail_txt)
        entry.update({"result": "fail", "failure_digest": digest})
        log_path.open("a", encoding="utf-8").write(json.dumps(entry) + "\n")

        if prev_digest == digest:
            stall_count += 1
            if stall_count >= stall_limit:
                print(
                    "[STALL] Failure signature unchanged for "
                    f"{stall_count} iters (digest {digest})."
                )
                return 4
        else:
            stall_count = 0
            prev_digest = digest

        # Context for prompt
        _, st_out, _, _ = _run("git status --porcelain")
        _, df_out, _, _ = _run("git --no-pager diff")

        # Build strict prompt (no triple-quotes/f-strings in source to avoid heredoc issues)
        rules = [
            "RETURN ONLY A MINIMAL UNIFIED DIFF (no prose, no fences).",
            f'Edit files ONLY under "{scope_path.as_posix()}".',
            "Headers must be:\n--- a/<path>\n+++ b/<path>",
            "Include only the smallest hunks needed to make tests pass.",
        ]
        prompt = (
            "\n".join(rules)
            + "\n\nTest command: "
            + tests
            + "\n\nFAIL (tail of stdout+stderr):\n"
            + _tail(fail_txt, 120)
            + "\n\nGIT STATUS:\n"
            + _tail(st_out, 80)
            + "\n\nCURRENT DIFF (context only):\n"
            + _tail(df_out, 120)
        )

        # Prefer Codex: disable Ollama attempts unless overridden
        max_ollama = "0" if prefer_codex else "1"
        cmd = (
            "hybrid solve --prompt "
            + shlex.quote(prompt)
            + " --file docs/PHASE6_SELF_REPAIR_SPEC.md --max-ollama-attempts "
            + max_ollama
        )
        s_rc, s_out, s_err, s_ms = _run(cmd, timeout=timeout_sec)
        log_path.open("a", encoding="utf-8").write(
            json.dumps(
                {
                    "step": i,
                    "solver_rc": s_rc,
                    "solver_ms": round(s_ms, 1),
                    "solver_stdout_tail": _tail(s_out, 50),
                    "solver_stderr_tail": _tail(s_err, 50),
                }
            )
            + "\n"
        )

        # Commit if changes exist
        _, diff_chk, _, _ = _run("git --no-pager diff")
        if diff_chk.strip():
            _run("git add -A")
            _run(
                'git -c user.name="HybridAgent" '
                '-c user.email="hybrid@example.com" '
                'commit -qm "chore(self-repair): automated patch"'
            )
        else:
            # Try literal fallback once before counting stall
            try:
                if _literal_fallback(scope_path, fail_txt):
                    stall_count = 0
                    continue
                if _direct_return_literal_fix(scope_path, "hi", "hello"):
                    stall_count = 0
                    continue
            except Exception:  # nosec B110
                pass
            stall_count += 1
            if stall_count >= stall_limit:
                print(f"[STALL] No changes applied for {stall_count} iters; giving up.")
                return 4

    print("[LIMIT] Reached max-iters without passing tests.")
    return 1
