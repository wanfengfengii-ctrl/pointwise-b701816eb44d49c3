import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from aircheck.store import create_aircheck_schema, ensure_request_id_column
from assets.store import create_asset_schema
from cues.store import create_cue_schema
from mix.errors import BroadcastError
from mix.frontier import create_frontier_schema
from relay.store import create_relay_schema
from scenes.store import create_scene_schema


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
        create_asset_schema(db)
        create_scene_schema(db)
        create_cue_schema(db)
        create_frontier_schema(db)
        create_aircheck_schema(db)
        ensure_request_id_column(db)
        create_relay_schema(db)
