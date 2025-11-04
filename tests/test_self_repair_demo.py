from hybrid_agent._sample_bug import greet


def test_greet_says_hello():
    assert greet() == "hello"  # nosec B101
