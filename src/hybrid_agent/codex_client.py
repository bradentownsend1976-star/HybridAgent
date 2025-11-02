import subprocess
from typing import List, Tuple


def codex_generate_diff(
    models: str,
    prompt: str,
    files: List[str],
    timeout_s: int = 180,
) -> Tuple[bool, str, str]:
    """
    Invoke `codex-local` with a Codex-style interface. Expects ONLY a unified diff on stdout.
    Returns (ok, text, message).
    """
    cmd = ["codex-local", "--models", models, "--prompt", prompt]  # no --unified (not supported)
    for f in files:
        cmd.extend(["--file", f])
    try:
        out = subprocess.check_output(cmd, timeout=timeout_s, text=True, stderr=subprocess.STDOUT)
        text = out.strip()
        if not text:
            return (False, "", "[ERR] Empty response from CodexCLI")
        return (True, text, "[OK]")
    except subprocess.CalledProcessError as e:
        return (False, "", f"[ERR] CodexCLI failed (exit {e.returncode}): {e.output.strip()}")
    except FileNotFoundError:
        return (False, "", "[ERR] codex-local not found on PATH")
    except Exception as e:  # defensive
        return (False, "", f"[ERR] Unexpected CodexCLI error: {e}")
