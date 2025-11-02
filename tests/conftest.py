import textwrap
from pathlib import Path
from typing import Callable

import pytest


@pytest.fixture
def hybridagent_validator(tmp_path: Path) -> Callable[[str], Path]:
    """
    Fixture to help tests generate a temporary validator script.

    Usage:
        def test_guardrail(hybridagent_validator):
            validator_path = hybridagent_validator("import sys\nsys.exit(0)")
    """

    def writer(source: str, filename: str = "config/validate_diff.py") -> Path:
        target = tmp_path / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        if not source.endswith("\n"):
            source = source + "\n"
        target.write_text(textwrap.dedent(source), encoding="utf-8")
        return target

    return writer
