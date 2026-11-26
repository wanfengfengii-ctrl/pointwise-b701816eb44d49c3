import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from mix.errors import BroadcastError


@contextmanager
def _transaction(path: str | Path, *, write: bool):
    try:
        with closing(sqlite3.connect(path, timeout=5.0, isolation_level=None)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys = ON')
            if not write:
                db.execute('PRAGMA query_only = ON')
            with db:
                db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                yield db
    except sqlite3.Error as error:
        raise BroadcastError(503, 'storage_failure', 'could not complete the database transaction') from error


def write_transaction(path: str | Path):
    return _transaction(path, write=True)


def read_snapshot(path: str | Path):
    return _transaction(path, write=False)


def initialize_database(path: str | Path) -> None:
    with write_transaction(path) as db:
        db.execute('''
            CREATE TABLE IF NOT EXISTS playout_shows (
                show TEXT PRIMARY KEY NOT NULL
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS playout_clock (
                show TEXT PRIMARY KEY NOT NULL REFERENCES playout_shows (show),
                next_frame BLOB NOT NULL
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS playout_candidates (
                show TEXT NOT NULL REFERENCES playout_shows (show),
                frame BLOB NOT NULL,
                request_id TEXT NOT NULL,
                left_level INTEGER NOT NULL CHECK (left_level BETWEEN -10 AND 10),
                right_level INTEGER NOT NULL CHECK (right_level BETWEEN -10 AND 10),
                PRIMARY KEY (show, frame)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS playout_aired (
                show TEXT NOT NULL REFERENCES playout_shows (show),
                frame BLOB NOT NULL,
                left_level INTEGER NOT NULL CHECK (left_level BETWEEN -10 AND 10),
                right_level INTEGER NOT NULL CHECK (right_level BETWEEN -10 AND 10),
                request_id TEXT,
                PRIMARY KEY (show, frame)
            )
        ''')
