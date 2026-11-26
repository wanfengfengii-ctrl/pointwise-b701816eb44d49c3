from pathlib import Path

from aircheck.history import get_aired_frame
from aircheck.replay import replay_frames
from assets.catalog import register_asset
from assets.preview import preview_asset
from cues.accept import accept_cue
from cues.stop import stop_cue
from mix.database import initialize_database, read_snapshot, write_transaction
from mix.emit import emit_frame
from mix.frontier import initialize_frontier, next_frame
from scenes.publish import publish_scene
from scenes.show import ensure_show, require_show


class BroadcastService:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        initialize_database(self.path)

    def prepare_show(self, show):
        with write_transaction(self.path) as db:
            state = ensure_show(db, show)
            initialize_frontier(db, state.show)
        return state

    def register_asset(self, name, sample):
        with write_transaction(self.path) as db:
            return register_asset(db, name, sample)

    def preview_asset(self, version):
        with read_snapshot(self.path) as db:
            return preview_asset(db, version)

    def publish_scene(self, show, revision, echo_output, echo_delay):
        with write_transaction(self.path) as db:
            return publish_scene(db, show, revision, echo_output, echo_delay)

    def accept_cue(self, show, asset_version, dry_frame, dry_output):
        with write_transaction(self.path) as db:
            state = require_show(db, show)
            return accept_cue(
                db, state.show, asset_version, dry_frame, dry_output,
                next_unplayed=next_frame(db, state.show),
            ).cue_id

    def stop_cue(self, show, cue_id):
        with write_transaction(self.path) as db:
            state = require_show(db, show)
            return stop_cue(db, state.show, cue_id)

    def emit_frame(self, show, frame):
        with write_transaction(self.path) as db:
            state = require_show(db, show)
            return emit_frame(db, state.show, frame)

    def read_frame(self, show, frame):
        with read_snapshot(self.path) as db:
            state = require_show(db, show)
            return get_aired_frame(db, state.show, frame)

    def replay_frames(self, show, start, end):
        with read_snapshot(self.path) as db:
            state = require_show(db, show)
            return replay_frames(db, state.show, start, end)
