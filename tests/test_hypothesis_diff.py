import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given  # type: ignore  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

loop = pytest.importorskip("hybrid_agent.loop")


@given(st.text())
def test_strip_code_fences_idempotent(raw_text: str) -> None:
    """Applying strip twice should stabilise."""
    first = loop._strip_code_fences(raw_text)
    second = loop._strip_code_fences(first)
    assert first == second  # nosec B101


@given(st.text())
def test_looks_like_unified_diff_consistent(raw_text: str) -> None:
    """No combination of fence stripping should flip the answer."""
    direct = loop._looks_like_unified_diff(raw_text)
    stripped = loop._looks_like_unified_diff(loop._strip_code_fences(raw_text))
    assert direct == stripped  # nosec B101
