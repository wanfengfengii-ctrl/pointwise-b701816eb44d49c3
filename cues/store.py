from dataclasses import dataclass
from sqlite3 import Connection, Row

from mix.values import MAX_ROW_ID, frame_from_key, frame_key


@dataclass(frozen=True)
class AcceptedCue:
    cue_id: int
    show: str
    asset_version: int
    dry_frame: int
    dry_output: str
    scene_revision: str
    echo_output: str
    echo_delay: int
    stopped: bool


def create_cue_schema(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS cues (
            cue_id INTEGER PRIMARY KEY,
            show TEXT NOT NULL REFERENCES shows (show),
            asset_version INTEGER NOT NULL REFERENCES asset_versions (version),
            dry_frame BLOB NOT NULL,
            dry_output TEXT NOT NULL CHECK (dry_output IN ('left', 'right')),
            scene_revision TEXT NOT NULL,
            echo_output TEXT NOT NULL CHECK (echo_output IN ('left', 'right')),
            echo_delay_hex TEXT NOT NULL,
            stopped INTEGER NOT NULL DEFAULT 0 CHECK (stopped IN (0, 1)),
            FOREIGN KEY (show, scene_revision) REFERENCES approved_scenes (show, revision)
        )
    ''')
    db.execute('CREATE INDEX IF NOT EXISTS active_cues_by_show ON cues (show, cue_id) WHERE stopped = 0')


def insert_cue(
    db: Connection, *, show: str, asset_version: int, dry_frame: int, dry_output: str,
    scene_revision: str, echo_output: str, echo_delay: int,
) -> AcceptedCue:
    cursor = db.execute('''
        INSERT INTO cues (show, asset_version, dry_frame, dry_output, scene_revision, echo_output, echo_delay_hex)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (show, asset_version, frame_key(dry_frame), dry_output, scene_revision, echo_output, hex(echo_delay)))
    return AcceptedCue(cursor.lastrowid, show, asset_version, dry_frame, dry_output,
                       scene_revision, echo_output, echo_delay, False)


def _accepted_cue(row: Row) -> AcceptedCue:
    return AcceptedCue(
        row['cue_id'], row['show'], row['asset_version'], frame_from_key(row['dry_frame']),
        row['dry_output'], row['scene_revision'], row['echo_output'],
        int(row['echo_delay_hex'], 16), bool(row['stopped']),
    )


def fetch_cue(db: Connection, show: str, cue_id: int) -> AcceptedCue | None:
    if cue_id > MAX_ROW_ID:
        return None
    row = db.execute('SELECT * FROM cues WHERE cue_id = ? AND show = ?', (cue_id, show)).fetchone()
    if row is None:
        return None
    return _accepted_cue(row)


def mark_cue_stopped(db: Connection, show: str, cue_id: int) -> None:
    db.execute('UPDATE cues SET stopped = 1 WHERE cue_id = ? AND show = ? AND stopped = 0', (cue_id, show))


def list_active_cues(db: Connection, show: str) -> list[AcceptedCue]:
    rows = db.execute('SELECT * FROM cues WHERE show = ? AND stopped = 0 ORDER BY cue_id', (show,))
    return [_accepted_cue(row) for row in rows]
