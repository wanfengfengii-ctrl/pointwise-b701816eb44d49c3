from sqlite3 import Connection

from aircheck.record import AiredFrame
from aircheck.store import fetch_aired_frame
from mix.errors import BroadcastError
from mix.values import require_frame


def get_aired_frame(db: Connection, show: str, frame) -> AiredFrame:
    row = fetch_aired_frame(db, show, require_frame(frame))
    if row is None:
        raise BroadcastError(404, 'frame_not_aired', 'the requested frame has not aired')
    return AiredFrame.from_row(row)
