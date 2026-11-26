from dataclasses import dataclass
from sqlite3 import Connection

from assets.catalog import require_asset
from cues.store import list_active_cues


@dataclass(frozen=True)
class PlaybackIntent:
    cue_id: int
    show: str
    dry_frame: int
    dry_output: str
    echo_delay: int
    echo_output: str
    sample: int


def load_playback_intents(db: Connection, show: str) -> list[PlaybackIntent]:
    intents = []
    samples: dict[int, int] = {}
    for cue in list_active_cues(db, show):
        if cue.asset_version not in samples:
            samples[cue.asset_version] = require_asset(db, cue.asset_version).sample
        intents.append(PlaybackIntent(
            cue.cue_id, cue.show, cue.dry_frame, cue.dry_output,
            cue.echo_delay, cue.echo_output, samples[cue.asset_version],
        ))
    return intents
