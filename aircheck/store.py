from sqlite3 import Connection, Row

from mix.values import frame_key


def create_aircheck_schema(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS aired_frames (
            show TEXT NOT NULL REFERENCES shows (show),
            frame BLOB NOT NULL,
            left_level INTEGER NOT NULL CHECK (left_level BETWEEN -10 AND 10),
            right_level INTEGER NOT NULL CHECK (right_level BETWEEN -10 AND 10),
            PRIMARY KEY (show, frame)
        )
    ''')


def append_aired_frame(db: Connection, show: str, frame: int, left: int, right: int) -> None:
    db.execute(
        'INSERT INTO aired_frames (show, frame, left_level, right_level) VALUES (?, ?, ?, ?)',
        (show, frame_key(frame), left, right),
    )


def fetch_aired_frame(db: Connection, show: str, frame: int) -> Row | None:
    return db.execute('''
        SELECT show, frame, left_level, right_level FROM aired_frames
        WHERE show = ? AND frame = ?
    ''', (show, frame_key(frame))).fetchone()


def fetch_frame_range(db: Connection, show: str, start: int, end: int) -> list[Row]:
    return db.execute('''
        SELECT show, frame, left_level, right_level FROM aired_frames
        WHERE show = ? AND frame BETWEEN ? AND ?
        ORDER BY frame
    ''', (show, frame_key(start), frame_key(end))).fetchall()
