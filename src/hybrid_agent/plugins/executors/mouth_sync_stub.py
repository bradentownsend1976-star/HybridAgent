from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List


class MouthSync:
    """Deterministic stub executor used for smoke tests."""

    id = "mouth-sync"
    name = "mouth-sync"
    version = "0.1.0"
    kind = "executor"

    def run(self, **kwargs: Any) -> Dict[str, Any]:
        fps = int(kwargs.get("fps", 30))
        audio = kwargs.get("audio")
        out = pathlib.Path(str(kwargs.get("out", "visemes.json")))

        frames: List[Dict[str, Any]] = [
            {"t": 0.00, "viseme": "rest"},
            {"t": 0.10, "viseme": "A"},
            {"t": 0.20, "viseme": "E"},
            {"t": 0.30, "viseme": "O"},
            {"t": 0.40, "viseme": "rest"},
        ]
        payload: Dict[str, Any] = {
            "fps": fps,
            "frames": frames,
            "source": {"audio": audio, "note": "stub"},
        }

        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload


PLUGIN = MouthSync()
