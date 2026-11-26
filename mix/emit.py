from sqlite3 import Connection

from aircheck.record import AiredFrame, record_frame
from mix.errors import BroadcastError
from mix.frontier import advance_frontier, next_frame
from mix.sum import sum_stereo
from mix.timeline import contributions_for_frame
from mix.values import require_frame


def emit_frame(db: Connection, show: str, frame) -> AiredFrame:
    frame = require_frame(frame)
    if frame != next_frame(db, show):
        raise BroadcastError(409, 'not_next_frame', 'only the next frame may be aired')
    levels = sum_stereo(contributions_for_frame(db, show, frame))
    aired = record_frame(db, show, frame, levels.left, levels.right)
    advance_frontier(db, show, frame)
    return aired
