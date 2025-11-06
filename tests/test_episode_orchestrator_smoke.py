from hybrid_agent.plugins import discover, get_plugins_by_kind
def test_orchestrator_discovery_and_plan():
    d = discover()
    names = {cls.__name__ for cls in d['executors']}
    assert 'EpisodeOrchestrator' in names  # nosec B101
    m = get_plugins_by_kind('executor')
    eo = m.get('episode-orchestrator')
    assert eo is not None  # nosec B101
    out = eo.run(topic='Frank and Glitch at the park', background='assets/backgrounds/park_day.png', target_secs=90)
    assert out.get('ok') and isinstance(out.get('cmd'), str) and 'build_episode_no_mouth.command' in out['cmd']  # nosec B101
