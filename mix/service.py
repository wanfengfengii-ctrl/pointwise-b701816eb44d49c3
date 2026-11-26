from pathlib import Path

from aircheck.history import get_aired_frame
from aircheck.record import record_frame
from aircheck.replay import replay_frames
from assets.catalog import register_asset
from assets.preview import preview_asset
from cues.accept import accept_cue
from cues.stop import stop_cue
from mix.database import initialize_database, read_snapshot, write_transaction
from mix.emit import emit_frame
from mix.errors import BroadcastError
from mix.frontier import advance_frontier, initialize_frontier, next_frame
from mix.sum import sum_stereo
from mix.timeline import contributions_for_frame
from mix.values import require_frame, require_request_id
from relay.client import PlayoutClient, PlayoutUnavailable
from relay.store import fetch_relay_candidate, insert_relay_candidate
from scenes.publish import publish_scene
from scenes.show import ensure_show, require_show


class BroadcastService:
    def __init__(self, path: str | Path, relay: dict | None = None):
        self.path = Path(path)
        self.relay = {show: PlayoutClient(base) for show, base in (relay or {}).items()}
        initialize_database(self.path)

    def is_relay(self, show) -> bool:
        return show in self.relay

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
            if state.show in self.relay:
                raise BroadcastError(
                    409, 'relay_required', 'relay shows air through the playout endpoint')
            return emit_frame(db, state.show, frame)

    def stage_candidate(self, show, frame, request_id):
        with read_snapshot(self.path) as db:
            state = require_show(db, show)
        client = self.relay.get(state.show)
        if client is None:
            raise BroadcastError(409, 'not_relay_show', 'show is not configured as a relay show')
        frame = require_frame(frame)
        request_id = require_request_id(request_id)
        document = {'show': state.show, 'frame': frame, 'request_id': request_id}
        with read_snapshot(self.path) as db:
            if fetch_relay_candidate(db, state.show, frame, request_id) is not None:
                return 200, {**document, 'status': 'accepted'}
            levels = sum_stereo(contributions_for_frame(db, state.show, frame))
        try:
            status, reply = client.post_candidate(
                state.show, frame, request_id, levels.left, levels.right)
        except PlayoutUnavailable:
            return 202, {**document, 'status': 'pending'}
        if status == 200 and reply.get('status') == 'accepted':
            left, right = reply.get('left'), reply.get('right')
            if type(left) is not int or type(right) is not int:
                return 202, {**document, 'status': 'pending'}
            with write_transaction(self.path) as db:
                insert_relay_candidate(db, state.show, frame, request_id, left, right)
            return 200, {**document, 'status': 'accepted'}
        if status == 200 and reply.get('status') == 'expired':
            return 200, {**document, 'status': 'expired'}
        if status == 409 and reply.get('error') in ('not_next_frame', 'candidate_exists'):
            raise BroadcastError(409, reply['error'], str(reply.get('message') or reply['error']))
        return 202, {**document, 'status': 'pending'}

    def sync_relay(self, show):
        with read_snapshot(self.path) as db:
            state = require_show(db, show)
        client = self.relay.get(state.show)
        if client is None:
            raise BroadcastError(409, 'not_relay_show', 'show is not configured as a relay show')
        with read_snapshot(self.path) as db:
            start = next_frame(db, state.show)
        try:
            evidence = client.aired_since(state.show, start)
        except PlayoutUnavailable as error:
            raise BroadcastError(
                503, 'relay_unavailable', 'could not collect aired evidence from the playout endpoint'
            ) from error
        with write_transaction(self.path) as db:
            expected = next_frame(db, state.show)
            for item in evidence:
                if item['frame'] != expected:
                    break
                record_frame(
                    db, state.show, expected, item['left'], item['right'],
                    request_id=item['request_id'])
                advance_frontier(db, state.show, expected)
                expected += 1
            last_frame = expected - 1
        return {'show': state.show, 'last_frame': last_frame}

    def read_frame(self, show, frame):
        with read_snapshot(self.path) as db:
            state = require_show(db, show)
            return get_aired_frame(db, state.show, frame)

    def replay_frames(self, show, start, end):
        with read_snapshot(self.path) as db:
            state = require_show(db, show)
            return replay_frames(db, state.show, start, end)
