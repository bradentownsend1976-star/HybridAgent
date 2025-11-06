from __future__ import annotations

from typing import Any, Protocol


class Executor(Protocol):
    id: str
    kind: str  # 'executor'

    def run(self, **kwargs: Any) -> Any: ...


class Validator(Protocol):
    id: str
    kind: str  # 'validator'

    def run(self, **kwargs: Any) -> Any: ...


class Generator(Protocol):
    id: str
    kind: str  # 'generator'

    def run(self, **kwargs: Any) -> Any: ...
