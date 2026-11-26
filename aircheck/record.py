from dataclasses import dataclass
from sqlite3 import Connection, Row

from aircheck.store import append_aired_frame
from mix.errors import BroadcastError
from mix.values import frame_from_key


@dataclass(frozen=True)
class AiredFrame:
    show: str
    frame: int
    left: int
    right: int
    request_id: str | None = None

    @classmethod
    def from_row(cls, row: Row):
        return cls(
            row['show'], frame_from_key(row['frame']), row['left_level'], row['right_level'],
            row['request_id'],
        )


def record_frame(
    db: Connection, show: str, frame: int, left: int, right: int, request_id: str | None = None,
) -> AiredFrame:
    for level in (left, right):
        if type(level) is not int or not -10 <= level <= 10:
            raise BroadcastError(503, 'invalid_level', 'formal output must be an integer between -10 and 10')
    append_aired_frame(db, show, frame, left, right, request_id)
    return AiredFrame(show, frame, left, right, request_id)
