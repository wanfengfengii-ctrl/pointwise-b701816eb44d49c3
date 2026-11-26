from sqlite3 import Connection, Row

from mix.values import frame_key


def create_relay_schema(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS relay_candidates (
            show TEXT NOT NULL,
            frame BLOB NOT NULL,
            request_id TEXT NOT NULL,
            left_level INTEGER NOT NULL,
            right_level INTEGER NOT NULL,
            PRIMARY KEY (show, frame, request_id)
        )
    ''')


def fetch_relay_candidate(db: Connection, show: str, frame: int, request_id: str) -> Row | None:
    return db.execute('''
        SELECT show, frame, request_id, left_level, right_level FROM relay_candidates
        WHERE show = ? AND frame = ? AND request_id = ?
    ''', (show, frame_key(frame), request_id)).fetchone()


def insert_relay_candidate(
    db: Connection, show: str, frame: int, request_id: str, left: int, right: int,
) -> None:
    db.execute('''
        INSERT INTO relay_candidates (show, frame, request_id, left_level, right_level)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (show, frame, request_id) DO NOTHING
    ''', (show, frame_key(frame), request_id, left, right))
