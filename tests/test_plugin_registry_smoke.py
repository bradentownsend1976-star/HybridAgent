from hybrid_agent.plugins.registry import discover_plugins, get_plugins_by_kind


def test_discovery_runs_without_crashing():
    plist = discover_plugins()
    assert isinstance(plist, list)  # nosec B101
    assert isinstance(get_plugins_by_kind("generator"), dict)  # nosec B101
