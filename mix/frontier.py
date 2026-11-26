from sqlite3 import Connection

from mix.errors import BroadcastError
from mix.values import frame_from_key, frame_key


def create_frontier_schema(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS frontiers (
            show TEXT PRIMARY KEY NOT NULL REFERENCES shows (show),
            next_frame BLOB NOT NULL
        )
    ''')


def initialize_frontier(db: Connection, show: str) -> None:
    db.execute(
        'INSERT INTO frontiers (show, next_frame) VALUES (?, ?) ON CONFLICT (show) DO NOTHING',
        (show, frame_key(0)),
    )


def next_frame(db: Connection, show: str) -> int:
    row = db.execute('SELECT next_frame FROM frontiers WHERE show = ?', (show,)).fetchone()
    if row is None:
        raise BroadcastError(503, 'storage_failure', 'prepared show has no frame frontier')
    return frame_from_key(row['next_frame'])


def advance_frontier(db: Connection, show: str, frame: int) -> None:
    cursor = db.execute(
        'UPDATE frontiers SET next_frame = ? WHERE show = ? AND next_frame = ?',
        (frame_key(frame + 1), show, frame_key(frame)),
    )
    if cursor.rowcount != 1:
        raise BroadcastError(409, 'not_next_frame', 'only the next frame may be aired')
