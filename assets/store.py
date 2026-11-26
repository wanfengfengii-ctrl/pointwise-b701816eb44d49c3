from sqlite3 import Connection

from assets.samples import AssetVersion
from mix.values import MAX_ROW_ID


def create_asset_schema(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS asset_versions (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            sample_hex TEXT NOT NULL
        )
    ''')


def insert_asset_version(db: Connection, name: str, sample: int) -> AssetVersion:
    cursor = db.execute(
        'INSERT INTO asset_versions (name, sample_hex) VALUES (?, ?)',
        (name, hex(sample)),
    )
    return AssetVersion(cursor.lastrowid, name, sample)


def fetch_asset_version(db: Connection, version: int) -> AssetVersion | None:
    if version > MAX_ROW_ID:
        return None
    row = db.execute(
        'SELECT version, name, sample_hex FROM asset_versions WHERE version = ?',
        (version,),
    ).fetchone()
    if row is None:
        return None
    return AssetVersion(row['version'], row['name'], int(row['sample_hex'], 16))
