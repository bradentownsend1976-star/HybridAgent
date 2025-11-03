"""
Coverage-guided fuzz harness for diff utilities.

Run locally with:
    python -m pip install atheris
    PYTHONPATH=src python tests/fuzz_diff_apply.py
"""

from __future__ import annotations

import sys

try:
    import atheris
except ModuleNotFoundError:  # pragma: no cover
    if __name__ == "__main__":
        print("Atheris not installed; skipping fuzz harness.")
    sys.exit(0)

from hybrid_agent import loop


def TestOneInput(data: bytes) -> None:  # noqa: N802 (atheris naming)
    payload = data.decode("utf-8", errors="ignore")
    loop._strip_code_fences(payload)
    loop._looks_like_unified_diff(payload)


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
