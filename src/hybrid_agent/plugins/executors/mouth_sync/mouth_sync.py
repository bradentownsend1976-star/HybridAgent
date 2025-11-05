from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class MouthSync:  # Executor protocol: name, version, run()
    name: str = "mouth-sync"
    version: str = "0.0.1"

    def run(
        self, *, audio: str, fps: int = 30, out: str | None = None, **_: Any
    ) -> Dict[str, Any]:
        """
        Stub executor: returns a tiny, deterministic viseme timeline for smoke tests.
        Format:
        {
          "fps": <int>,
          "frames": [
              {"t": 0,    "viseme": "rest"},
              {"t": 0.10, "viseme": "A"},
              {"t": 0.20, "viseme": "E"},
              {"t": 0.30, "viseme": "O"},
              {"t": 0.40, "viseme": "rest"}
          ],
          "source": {"audio": "<path>", "note": "stub"}
        }
        """
        # Minimal timeline; real implementation will read `audio` + extract phonemes.
        frames: List[Dict[str, Any]] = [
            {"t": 0.00, "viseme": "rest"},
            {"t": 0.10, "viseme": "A"},
            {"t": 0.20, "viseme": "E"},
            {"t": 0.30, "viseme": "O"},
            {"t": 0.40, "viseme": "rest"},
        ]
        result: Dict[str, Any] = {
            "fps": int(fps),
            "frames": frames,
            "source": {"audio": audio, "note": "stub"},
        }

        if out:
            import json
            import pathlib

            pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
            pathlib.Path(out).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
