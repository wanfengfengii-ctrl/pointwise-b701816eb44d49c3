from sqlite3 import Connection, Row

from mix.values import frame_key


def create_aircheck_schema(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS aired_frames (
            show TEXT NOT NULL REFERENCES shows (show),
            frame BLOB NOT NULL,
            left_level INTEGER NOT NULL CHECK (left_level BETWEEN -10 AND 10),
            right_level INTEGER NOT NULL CHECK (right_level BETWEEN -10 AND 10),
            request_id TEXT,
            PRIMARY KEY (show, frame)
        )
    ''')


def ensure_request_id_column(db: Connection) -> None:
    # Databases prepared before relay support lack the candidate request column.
    columns = {row['name'] for row in db.execute('PRAGMA table_info (aired_frames)')}
    if 'request_id' not in columns:
        db.execute('ALTER TABLE aired_frames ADD COLUMN request_id TEXT')


def append_aired_frame(
    db: Connection, show: str, frame: int, left: int, right: int, request_id: str | None = None,
) -> None:
    db.execute(
        'INSERT INTO aired_frames (show, frame, left_level, right_level, request_id) VALUES (?, ?, ?, ?, ?)',
        (show, frame_key(frame), left, right, request_id),
    )


def fetch_aired_frame(db: Connection, show: str, frame: int) -> Row | None:
    return db.execute('''
        SELECT show, frame, left_level, right_level, request_id FROM aired_frames
        WHERE show = ? AND frame = ?
    ''', (show, frame_key(frame))).fetchone()


def fetch_frame_range(db: Connection, show: str, start: int, end: int) -> list[Row]:
    return db.execute('''
        SELECT show, frame, left_level, right_level, request_id FROM aired_frames
        WHERE show = ? AND frame BETWEEN ? AND ?
        ORDER BY frame
    ''', (show, frame_key(start), frame_key(end))).fetchall()
