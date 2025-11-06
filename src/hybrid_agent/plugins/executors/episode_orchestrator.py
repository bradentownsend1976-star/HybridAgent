from __future__ import annotations
import re
from typing import Any, Dict

class EpisodeOrchestrator:
    id = 'episode-orchestrator'
    kind = 'executor'

    @staticmethod
    def _slug(s: str) -> str:
        s = s.strip().lower()
        s = re.sub(r'[^a-z0-9]+', '-', s)
        return re.sub(r'-+', '-', s).strip('-') or 'episode'

    def run(self, **kwargs: Any) -> Dict[str, Any]:
        topic: str = str(kwargs.get('topic', 'untitled'))
        background: str = str(kwargs.get('background', 'assets/backgrounds/living_room.png'))
        target_secs: int = int(kwargs.get('target_secs', 90))
        ep_id = self._slug(topic)[:48]
        cmd = (
            'cd /mnt/c/Users/Braden/Desktop/FrankvsAI && '
            'set -euo pipefail && '
            'export IMAGEIO_FFMPEG_EXE="$(which ffmpeg)" && '
            f'EP="{ep_id}" && EPDIR="frankvsai-episodes/$EP" && '
            f'BG="{background}" && '
            'bash tools/build_episode_no_mouth.command '
            '--ep "$EP" --script "$EPDIR/$EP.txt" --bg "$BG" --gap 0.10'
        )
        return {'ok': True, 'plan': {'topic': topic, 'episode_id': ep_id, 'background': background, 'target_secs': target_secs}, 'cmd': cmd}

PLUGIN = EpisodeOrchestrator()
