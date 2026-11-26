from sqlite3 import Connection

from cues.store import fetch_cue, mark_cue_stopped
from mix.errors import BroadcastError
from mix.values import require_id


def stop_cue(db: Connection, show: str, cue_id) -> int:
    cue_id = require_id(cue_id, 'cue_id')
    cue = fetch_cue(db, show, cue_id)
    if cue is None:
        raise BroadcastError(404, 'unknown_cue', 'cue does not belong to this show')
    if not cue.stopped:
        mark_cue_stopped(db, show, cue.cue_id)
    return cue.cue_id
