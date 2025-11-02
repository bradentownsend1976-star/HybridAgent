from __future__ import annotations

import json
from typing import Tuple
from urllib import error, request


def ollama_generate_diff(
    model: str, prompt: str, timeout_s: int = 25
) -> Tuple[bool, str, str]:
    payload = {"model": model, "prompt": prompt, "stream": False}
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        "http://localhost:11434/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
    )

    try:
        with request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
        message = f"[ERR] Ollama returned HTTP {exc.code}. {detail}".strip()
        return False, "", message
    except error.URLError as exc:
        return False, "", f"[ERR] Unable to reach Ollama: {exc}"
    except Exception as exc:  # pragma: no cover - defensive
        return False, "", f"[ERR] Unexpected error querying Ollama: {exc}"

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return False, "", "[ERR] Ollama returned invalid JSON response."

    response_text = payload.get("response", "")
    if isinstance(response_text, str) and response_text.strip():
        return True, response_text, "[OK]"

    return False, "", "[ERR] Ollama returned an empty response."
