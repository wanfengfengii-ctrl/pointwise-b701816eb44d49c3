from sqlite3 import Connection

from assets.catalog import require_asset
from cues.store import AcceptedCue, insert_cue
from mix.errors import BroadcastError
from mix.values import require_frame
from scenes.draft import validate_output
from scenes.publish import require_current_scene


def accept_cue(
    db: Connection, show: str, asset_version, dry_frame, dry_output, *, next_unplayed: int,
) -> AcceptedCue:
    dry_frame = require_frame(dry_frame, 'dry_frame')
    dry_output = validate_output(dry_output, 'dry_output')
    if dry_frame < next_unplayed:
        raise BroadcastError(409, 'dry_frame_aired', 'the requested dry frame has already aired')
    scene = require_current_scene(db, show)
    asset = require_asset(db, asset_version)
    return insert_cue(
        db, show=scene.show, asset_version=asset.version, dry_frame=dry_frame, dry_output=dry_output,
        scene_revision=scene.revision, echo_output=scene.echo_output, echo_delay=scene.echo_delay,
    )
