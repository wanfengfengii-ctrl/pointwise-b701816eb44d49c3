from sqlite3 import Connection

from mix.errors import BroadcastError
from scenes.draft import validate_draft
from scenes.show import require_show
from scenes.store import ApprovedScene, append_scene_activation, fetch_current_scene, save_approved_revision


def publish_scene(db: Connection, show, revision, echo_output, echo_delay) -> ApprovedScene:
    state = require_show(db, show)
    draft = validate_draft(revision, echo_output, echo_delay)
    scene = save_approved_revision(db, state.show, draft)
    append_scene_activation(db, scene)
    return scene


def require_current_scene(db: Connection, show) -> ApprovedScene:
    state = require_show(db, show)
    if state.current_revision is None:
        raise BroadcastError(409, 'show_not_open', 'publish a scene before accepting cues')
    scene = fetch_current_scene(db, state.show)
    if scene is None:
        raise BroadcastError(503, 'storage_failure', 'current scene record is missing')
    return scene
