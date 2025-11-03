from __future__ import annotations

import json
from typing import List, Tuple
from urllib import request as _req
from urllib.parse import urlsplit


def _safe_urlopen(req, timeout_s):
    # Only allow http/https (avoid file:// etc.)
    url = getattr(req, "full_url", None) or str(req)
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"Disallowed URL scheme: {parts.scheme}")
    return _req.urlopen(req, timeout=timeout_s)  # nosec B310


# nosec B310
def _pick_ollama_model(models: str) -> str:
    first = (models or "").split(",")[0].strip()
    if not first:
        return "qwen2.5-coder:7b-instruct"
    if "api:ollama:" in first:
        return first.split("api:ollama:", 1)[1]
    return first


def ollama_generate_diff(
    models: str,
    prompt: str,
    files: List[str],
    timeout_s: int = 180,
) -> Tuple[bool, str, str]:
    """Call local Ollama /api/generate and return only the model text.
    Returns (ok, text, message).
    """
    model = _pick_ollama_model(models)
    body = {
        "model": model,
        "prompt": prompt,
        "options": {"temperature": 0},
        "stream": False,
    }
    try:
        data = json.dumps(body).encode("utf-8")
        req = _req.Request(
            "http://127.0.0.1:11434/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _safe_urlopen(req, timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        try:
            j = json.loads(raw)
        except Exception:
            lines = raw.strip().splitlines()
            j = json.loads(lines[-1]) if lines else {}
        text = (j.get("response") or "").strip()
        if not text:
            return (False, "", "[ERR] Empty response from Ollama")
        return (True, text, "[OK]")
    except Exception as e:
        return (False, "", f"[ERR] Ollama error: {e}")


# Legacy-compatible wrapper for older call sites:
# generate_diff(prompt, model='qwen2.5-coder:7b-instruct', files=[...], timeout_s=180)
def generate_diff(
    prompt: str,
    model: str | None = None,
    files: list[str] | None = None,
    timeout_s: int = 180,
) -> tuple[bool, str, str]:
    return ollama_generate_diff(
        models=(model or ""),
        prompt=prompt,
        files=(files or []),
        timeout_s=timeout_s,
    )
