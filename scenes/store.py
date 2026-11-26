from dataclasses import dataclass
from sqlite3 import Connection

from mix.errors import BroadcastError
from scenes.draft import SceneDraft


@dataclass(frozen=True)
class ShowState:
    show: str
    current_revision: str | None


@dataclass(frozen=True)
class ApprovedScene:
    show: str
    revision: str
    echo_output: str
    echo_delay: int


def create_scene_schema(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS shows (
            show TEXT PRIMARY KEY NOT NULL,
            current_revision TEXT,
            FOREIGN KEY (show, current_revision) REFERENCES approved_scenes (show, revision)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS approved_scenes (
            show TEXT NOT NULL REFERENCES shows (show),
            revision TEXT NOT NULL,
            echo_output TEXT NOT NULL CHECK (echo_output IN ('left', 'right')),
            echo_delay_hex TEXT NOT NULL,
            PRIMARY KEY (show, revision)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS scene_activations (
            activation_id INTEGER PRIMARY KEY,
            show TEXT NOT NULL,
            revision TEXT NOT NULL,
            UNIQUE (show, revision),
            FOREIGN KEY (show, revision) REFERENCES approved_scenes (show, revision)
        )
    ''')


def insert_show_if_missing(db: Connection, show: str) -> None:
    db.execute('INSERT INTO shows (show) VALUES (?) ON CONFLICT (show) DO NOTHING', (show,))


def fetch_show(db: Connection, show: str) -> ShowState | None:
    row = db.execute('SELECT current_revision FROM shows WHERE show = ?', (show,)).fetchone()
    if row is None:
        return None
    return ShowState(show, row['current_revision'])


def save_approved_revision(db: Connection, show: str, draft: SceneDraft) -> ApprovedScene:
    cursor = db.execute('''
        INSERT INTO approved_scenes (show, revision, echo_output, echo_delay_hex)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (show, revision) DO NOTHING
    ''', (show, draft.revision, draft.echo_output, hex(draft.echo_delay)))
    if cursor.rowcount == 0:
        raise BroadcastError(409, 'revision_exists', 'this scene revision is already approved')
    return ApprovedScene(show, draft.revision, draft.echo_output, draft.echo_delay)


def append_scene_activation(db: Connection, scene: ApprovedScene) -> None:
    db.execute(
        'INSERT INTO scene_activations (show, revision) VALUES (?, ?)',
        (scene.show, scene.revision),
    )
    db.execute('UPDATE shows SET current_revision = ? WHERE show = ?', (scene.revision, scene.show))


def fetch_current_scene(db: Connection, show: str) -> ApprovedScene | None:
    row = db.execute('''
        SELECT scene.revision, scene.echo_output, scene.echo_delay_hex
        FROM shows
        JOIN approved_scenes AS scene
          ON scene.show = shows.show AND scene.revision = shows.current_revision
        WHERE shows.show = ?
    ''', (show,)).fetchone()
    if row is None:
        return None
    return ApprovedScene(show, row['revision'], row['echo_output'], int(row['echo_delay_hex'], 16))
