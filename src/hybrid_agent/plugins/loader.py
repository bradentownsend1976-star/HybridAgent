from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Dict, List, Type

from .protocols import Executor, Generator, Validator


def _issubclass_safe(obj, proto) -> bool:
    try:
        return inspect.isclass(obj) and issubclass(obj, proto)  # type: ignore[arg-type]
    except Exception:
        return False


def _implements_protocol(obj, attrs: Dict[str, str]) -> bool:
    """Light structural check: required attributes/methods exist."""
    for name, kind in attrs.items():
        if kind == "attr":
            if not hasattr(obj, name):
                return False
        elif kind == "method":
            if not callable(getattr(obj, name, None)):
                return False
    return True


def discover() -> Dict[str, list]:
    """Discover classes implementing Generator/Validator/Executor in hybrid_agent.plugins.*"""
    gens: List[Type] = []
    vals: List[Type] = []
    execs: List[Type] = []
    _errors: List[tuple] = []

    pkg = importlib.import_module("hybrid_agent.plugins")
    base_path = getattr(pkg, "__path__", None)
    if base_path is None:
        return {
            "generators": gens,
            "validators": vals,
            "executors": execs,
            "errors": _errors,
        }

    for m in pkgutil.walk_packages(base_path, prefix=pkg.__name__ + "."):
        try:
            mod = importlib.import_module(m.name)
        except Exception as exc:  # nosec B110 (record and continue via else-branch)
            _errors.append((m.name, repr(exc)))
        else:
            for _, obj in inspect.getmembers(mod):
                if _issubclass_safe(obj, Generator) or _implements_protocol(
                    obj, {"name": "attr", "version": "attr", "generate": "method"}
                ):
                    gens.append(obj)
                elif _issubclass_safe(obj, Validator) or _implements_protocol(
                    obj, {"name": "attr", "version": "attr", "validate": "method"}
                ):
                    vals.append(obj)
                elif _issubclass_safe(obj, Executor) or _implements_protocol(
                    obj, {"name": "attr", "version": "attr", "run": "method"}
                ):
                    execs.append(obj)

    return {
        "generators": gens,
        "validators": vals,
        "executors": execs,
        "errors": _errors,
    }
