from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from hybrid_agent import cli_app

runner = CliRunner()


def test_mouth_sync_cli_writes_json(tmp_path: Path) -> None:
    out_path = tmp_path / "visemes.json"
    audio_path = tmp_path / "dummy.wav"
    audio_path.write_bytes(b"")  # create placeholder audio file

    result = runner.invoke(
        cli_app.app,
        [
            "exec",
            "mouth-sync",
            "--audio",
            str(audio_path),
            "--fps",
            "30",
            "--out",
            str(out_path),
        ],
    )
    assert result.exit_code == 0, result.output  # nosec B101

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["fps"] == 30  # nosec B101
    frames = payload.get("frames", [])
    assert isinstance(frames, list) and len(frames) == 5  # nosec B101
    assert all(set(frame) == {"t", "viseme"} for frame in frames)  # nosec B101
