def test_discovery_runs_without_crashing():
    from hybrid_agent.plugins.registry import discover_plugins, get_plugins_by_kind

    plist = discover_plugins()
    assert isinstance(plist, list)
    _ = get_plugins_by_kind("generator")
