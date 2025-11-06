from __future__ import annotations

from typing import Dict, List, Type

from .registry import get_plugins_by_kind as _get


def discover() -> dict:
    exec_classes: List[Type] = [type(p) for p in _get("executor").values()]
    val_classes: List[Type] = [type(p) for p in _get("validator").values()]
    gen_classes: List[Type] = [type(p) for p in _get("generator").values()]
    return {
        "executors": exec_classes,
        "validators": val_classes,
        "generators": gen_classes,
    }


def get_plugins_by_kind(kind: str) -> Dict[str, object]:
    return _get(kind)
