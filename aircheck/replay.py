from sqlite3 import Connection

from aircheck.record import AiredFrame
from aircheck.store import fetch_frame_range
from mix.errors import BroadcastError
from mix.values import require_frame


def replay_frames(db: Connection, show: str, start, end) -> list[AiredFrame]:
    start = require_frame(start, 'start')
    end = require_frame(end, 'end')
    if end < start:
        raise BroadcastError(400, 'invalid_range', 'end must be at or after start')
    rows = fetch_frame_range(db, show, start, end)
    if len(rows) != end - start + 1:
        raise BroadcastError(404, 'frame_not_aired', 'the requested range has unaired frames')
    return [AiredFrame.from_row(row) for row in rows]
