from hybrid_agent.plugins import discover


def test_discovery_finds_mouthsync():
    items = discover()
    execs = items.get("executors", [])
    names = {cls.__name__ for cls in execs}
    assert "MouthSync" in names  # nosec B101
