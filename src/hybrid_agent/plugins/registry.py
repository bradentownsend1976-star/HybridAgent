from __future__ import annotations
from typing import Dict, List, Type
from .executors import mouth_sync_stub
_EXEC = {mouth_sync_stub.PLUGIN.id: mouth_sync_stub.PLUGIN}
_VAL: Dict[str, object] = {}
_GEN: Dict[str, object] = {}
def get_plugins_by_kind(kind: str) -> Dict[str, object]:
    return {'executor': dict(_EXEC), 'validator': dict(_VAL), 'generator': dict(_GEN)}.get(kind, {})
def discover_plugins() -> List[object]:
    return list(_EXEC.values()) + list(_VAL.values()) + list(_GEN.values())
