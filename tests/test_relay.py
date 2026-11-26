import http.client
import socket
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread

from mix.http import BroadcastHTTPServer
from mix.service import BroadcastService
from playout.http import PlayoutHTTPServer, PlayoutRequestHandler
from playout.service import PlayoutService
from relay_fixture import forwarding
from tests.support import QuietHandler, StudioClient, show_path


class QuietPlayoutHandler(PlayoutRequestHandler):
    def log_message(self, format, *args):
        pass


def _free_port():
    with closing(socket.socket()) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def aired(show, frame, left, right, request_id):
    return {'show': show, 'frame': frame, 'left': left, 'right': right, 'request_id': request_id}


class RelayCase(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory(prefix='live-mix-relay-'))
        self.studio_path = Path(directory) / 'studio.sqlite'
        self.playout_path = Path(directory) / 'playout.sqlite'
        self.playout_port = _free_port()
        self.playout_server = None
        self.studio_server = None
        self.start_playout()
        self.proxy = self.enterContext(forwarding(self.playout_port))
        self.operator = StudioClient(self.proxy.server_port)
        self.start_studio()
        self.addCleanup(self.stop_studio)
        self.addCleanup(self.stop_playout)

    def start_playout(self):
        service = PlayoutService(self.playout_path)
        for show in ('early', 'late'):
            service.prepare_show(show)
        self.playout_server = PlayoutHTTPServer(self.playout_port, service, QuietPlayoutHandler)
        self.playout_thread = Thread(
            target=self.playout_server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        self.playout_thread.start()

    def stop_playout(self):
        if self.playout_server is None:
            return
        self.playout_server.shutdown()
        self.playout_thread.join(timeout=5)
        self.playout_server.server_close()
        self.playout_server = None

    def start_studio(self):
        relay = {show: self.proxy.address for show in ('early', 'late')}
        self.studio_service = BroadcastService(self.studio_path, relay=relay)
        self.studio_service.prepare_show('studio')
        for show in ('early', 'late'):
            self.studio_service.prepare_show(show)
        self.studio_server = BroadcastHTTPServer(0, self.studio_service, QuietHandler)
        self.studio_thread = Thread(
            target=self.studio_server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        self.studio_thread.start()
        self.studio = StudioClient(self.studio_server.server_port)

    def stop_studio(self):
        if self.studio_server is None:
            return
        self.studio_server.shutdown()
        self.studio_thread.join(timeout=5)
        self.studio_server.server_close()
        self.studio_server = None

    def assert_error(self, client, method, path, status, code, data=None):
        result = client.expect(method, path, status, data)
        self.assertEqual(result['error'], code)
        self.assertTrue(result['message'])

    def open_relay_show(self, show):
        version = self.studio.asset('A', 8)
        self.studio.scene('opening', 'right', 2, show)
        return version, self.studio.cue(version, 0, show=show)


class RelayOrderTests(RelayCase):
    def test_candidate_before_tick_airs_program(self):
        self.open_relay_show('early')
        staged = self.studio.stage(0, 'opening-0', 'early')
        self.assertEqual(staged, {
            'show': 'early', 'frame': 0, 'request_id': 'opening-0', 'status': 'accepted',
        })
        self.assertEqual(self.operator.tick(0, 'early'), aired('early', 0, 8, 0, 'opening-0'))
        self.assertEqual(self.operator.tick(0, 'early'), aired('early', 0, 8, 0, 'opening-0'))
        self.assert_error(self.studio, 'GET', '/shows/early/frames/0', 404, 'frame_not_aired')
        self.assertEqual(self.studio.sync('early'), {'show': 'early', 'last_frame': 0})
        self.assertEqual(self.studio.read(0, 'early'), aired('early', 0, 8, 0, 'opening-0'))

    def test_tick_before_candidate_airs_silence(self):
        self.open_relay_show('late')
        self.assertEqual(self.operator.tick(0, 'late'), aired('late', 0, 0, 0, None))
        staged = self.studio.stage(0, 'opening-0', 'late')
        self.assertEqual(staged, {
            'show': 'late', 'frame': 0, 'request_id': 'opening-0', 'status': 'expired',
        })
        self.assertEqual(self.studio.sync('late'), {'show': 'late', 'last_frame': 0})
        self.assertEqual(self.studio.read(0, 'late'), aired('late', 0, 0, 0, None))

    def test_both_orders_and_silent_frame_one(self):
        self.open_relay_show('early')
        self.open_relay_show('late')
        self.studio.stage(0, 'opening-0', 'early')
        self.assertEqual(self.operator.tick(0, 'early'), aired('early', 0, 8, 0, 'opening-0'))
        self.assertEqual(self.operator.tick(0, 'late'), aired('late', 0, 0, 0, None))
        self.assertEqual(self.studio.stage(0, 'opening-0', 'late')['status'], 'expired')
        # Frame 1 stays silent on both shows even after the late piece for frame 0.
        self.assertEqual(self.operator.tick(1, 'early'), aired('early', 1, 0, 0, None))
        self.assertEqual(self.operator.tick(1, 'late'), aired('late', 1, 0, 0, None))
        for show in ('early', 'late'):
            self.assert_error(self.studio, 'GET', f'/shows/{show}/frames/0', 404, 'frame_not_aired')
        self.assertEqual(self.studio.sync('early'), {'show': 'early', 'last_frame': 1})
        self.assertEqual(self.studio.sync('late'), {'show': 'late', 'last_frame': 1})
        self.assertEqual(self.studio.replay(0, 1, 'early'), [
            aired('early', 0, 8, 0, 'opening-0'), aired('early', 1, 0, 0, None),
        ])
        self.assertEqual(self.studio.replay(0, 1, 'late'), [
            aired('late', 0, 0, 0, None), aired('late', 1, 0, 0, None),
        ])
        # Repeated syncs do not add frames.
        self.assertEqual(self.studio.sync('early'), {'show': 'early', 'last_frame': 1})
        self.assertEqual(self.studio.sync('late'), {'show': 'late', 'last_frame': 1})


class RelayCandidateTests(RelayCase):
    def test_conflicts_futures_and_reclaim(self):
        self.open_relay_show('early')
        self.assertEqual(self.studio.stage(0, 'first', 'early')['status'], 'accepted')
        self.assert_error(self.studio, 'POST', '/shows/early/stage', 409, 'not_next_frame',
                          {'frame': 1, 'request_id': 'future'})
        self.assert_error(self.studio, 'POST', '/shows/early/stage', 409, 'candidate_exists',
                          {'frame': 0, 'request_id': 'second'})
        self.assert_error(self.operator, 'POST', '/shows/early/tick', 409, 'not_next_frame',
                          {'frame': 5})
        self.operator.tick(0, 'early')
        # The original request reclaims its acceptance even after the frame aired.
        self.assertEqual(self.studio.stage(0, 'first', 'early'), {
            'show': 'early', 'frame': 0, 'request_id': 'first', 'status': 'accepted',
        })
        self.assertEqual(self.studio.stage(0, 'second', 'early')['status'], 'expired')
        self.assertEqual(self.operator.tick(0, 'early'), aired('early', 0, 8, 0, 'first'))

    def test_silent_candidate_keeps_request_id(self):
        self.studio.scene('opening', 'right', 2, 'early')
        self.assertEqual(self.studio.stage(0, 'quiet-0', 'early')['status'], 'accepted')
        self.assertEqual(self.operator.tick(0, 'early'), aired('early', 0, 0, 0, 'quiet-0'))
        self.assertEqual(self.studio.sync('early'), {'show': 'early', 'last_frame': 0})
        self.assertEqual(self.studio.read(0, 'early'), aired('early', 0, 0, 0, 'quiet-0'))

    def test_candidate_values_frozen_at_stage_time(self):
        _, cue = self.open_relay_show('early')
        self.assertEqual(self.studio.stage(0, 'opening-0', 'early')['status'], 'accepted')
        self.assertEqual(self.studio.stop(cue, 'early'), {'cue_id': cue, 'stopped': True})
        self.assertEqual(self.operator.tick(0, 'early'), aired('early', 0, 8, 0, 'opening-0'))

    def test_invalid_requests(self):
        self.studio.scene('opening', 'right', 2, 'early')
        self.assert_error(self.studio, 'POST', '/shows/early/stage', 400, 'invalid_request',
                          {'frame': 0, 'request_id': '  '})
        self.assert_error(self.studio, 'POST', '/shows/early/stage', 400, 'invalid_frame',
                          {'frame': -1, 'request_id': 'x'})
        self.assert_error(self.studio, 'POST', '/shows/early/stage', 400, 'invalid_request',
                          {'frame': 0})
        self.assert_error(self.operator, 'POST', '/shows/early/tick', 400, 'invalid_frame',
                          {'frame': -1})
        self.assert_error(self.operator, 'POST', '/shows/early/candidates', 400, 'invalid_request',
                          {'frame': 0, 'request_id': 'x', 'left': 11, 'right': 0})


class RelayGuardTests(RelayCase):
    def test_relay_guards(self):
        self.studio.scene('opening', 'left', 2, 'studio')
        # Ordinary shows keep the original entrances and reject relay ones.
        self.assert_error(self.studio, 'POST', '/shows/studio/stage', 409, 'not_relay_show',
                          {'frame': 0, 'request_id': 'x'})
        self.assert_error(self.studio, 'POST', '/shows/studio/sync', 409, 'not_relay_show')
        self.assertEqual(self.studio.emit(0, 'studio'),
                         {'show': 'studio', 'frame': 0, 'left': 0, 'right': 0})
        # Relay shows reject the old direct emit entrance.
        self.assert_error(self.studio, 'POST', '/shows/early/frames', 409, 'relay_required',
                          {'frame': 0})
        # Unknown shows keep the original 404 convention on both endpoints.
        self.assert_error(self.studio, 'POST', '/shows/ghost/stage', 404, 'unknown_show',
                          {'frame': 0, 'request_id': 'x'})
        self.assert_error(self.studio, 'POST', '/shows/ghost/sync', 404, 'unknown_show')
        self.assert_error(self.operator, 'POST', '/shows/ghost/tick', 404, 'unknown_show',
                          {'frame': 0})
        # A fresh relay show has synced nothing.
        self.assertEqual(self.studio.sync('early'), {'show': 'early', 'last_frame': -1})

    def test_cue_acceptance_uses_synced_frontier(self):
        version, _ = self.open_relay_show('early')
        self.studio.stage(0, 'opening-0', 'early')
        self.operator.tick(0, 'early')
        # The playout clock moved on, but the studio frontier waits for sync.
        self.studio.cue(version, 0, show='early')
        self.assertEqual(self.studio.sync('early'), {'show': 'early', 'last_frame': 0})
        self.assert_error(self.studio, 'POST', '/shows/early/cues', 409, 'dry_frame_aired',
                          {'asset_version': version, 'dry_frame': 0, 'dry_output': 'left'})

    def test_stage_pending_and_sync_unavailable_when_playout_down(self):
        self.open_relay_show('early')
        self.stop_playout()
        status, document = self.studio.request(
            'POST', '/shows/early/stage', {'frame': 0, 'request_id': 'opening-0'})
        self.assertEqual(status, 202)
        self.assertEqual(document, {
            'show': 'early', 'frame': 0, 'request_id': 'opening-0', 'status': 'pending',
        })
        self.assert_error(self.studio, 'POST', '/shows/early/sync', 503, 'relay_unavailable')


class RelayRecoveryTests(RelayCase):
    def test_disconnect_then_relisten(self):
        _, cue = self.open_relay_show('early')
        # The candidate acceptance reply is lost after the playout accepted it.
        gate = self.proxy.intercept_once('POST', '/shows/early/candidates', drop=True)
        status, document = self.studio.request(
            'POST', '/shows/early/stage', {'frame': 0, 'request_id': 'opening-0'})
        self.assertEqual(status, 202)
        self.assertEqual(document['status'], 'pending')
        self.assertTrue(gate.finished.is_set())
        self.assertEqual(gate.upstream_status, 200)
        # The aired reply for frame 0 is lost as well.
        gate = self.proxy.intercept_once('POST', '/shows/early/tick', drop=True)
        with self.assertRaises(http.client.RemoteDisconnected):
            self.operator.request('POST', '/shows/early/tick', {'frame': 0})
        self.assertTrue(gate.finished.is_set())
        self.assertEqual(gate.upstream_status, 200)
        # The studio goes offline; the playout frame clock keeps running.
        self.stop_studio()
        self.assertEqual(self.operator.tick(1, 'early'), aired('early', 1, 0, 0, None))
        # Both ends reopen on their original databases.
        self.stop_playout()
        self.start_playout()
        self.start_studio()
        self.assertEqual(self.studio.stop(cue, 'early'), {'cue_id': cue, 'stopped': True})
        # The original request and the original tick reclaim their first results.
        self.assertEqual(self.studio.stage(0, 'opening-0', 'early'), {
            'show': 'early', 'frame': 0, 'request_id': 'opening-0', 'status': 'accepted',
        })
        self.assertEqual(self.operator.tick(0, 'early'), aired('early', 0, 8, 0, 'opening-0'))
        self.assert_error(self.studio, 'GET', '/shows/early/frames/0', 404, 'frame_not_aired')
        # Sync records the contiguous aired prefix; a repeat adds nothing.
        self.assertEqual(self.studio.sync('early'), {'show': 'early', 'last_frame': 1})
        self.assertEqual(self.studio.sync('early'), {'show': 'early', 'last_frame': 1})
        self.assertEqual(self.studio.replay(0, 1, 'early'), [
            aired('early', 0, 8, 0, 'opening-0'), aired('early', 1, 0, 0, None),
        ])

    def test_sync_commit_failure_preserves_archive_and_frontier(self):
        self.open_relay_show('early')
        self.studio.stage(0, 'opening-0', 'early')
        self.operator.tick(0, 'early')
        self.operator.tick(1, 'early')
        with closing(sqlite3.connect(self.studio_path)) as db, db:
            db.execute('CREATE TABLE test_sync_parent (id INTEGER PRIMARY KEY)')
            db.execute('''
                CREATE TABLE test_sync_child (
                    parent_id INTEGER NOT NULL REFERENCES test_sync_parent (id)
                    DEFERRABLE INITIALLY DEFERRED
                )
            ''')
            db.execute('''
                CREATE TRIGGER test_reject_sync AFTER INSERT ON aired_frames
                BEGIN
                    INSERT INTO test_sync_child (parent_id) VALUES (1);
                END
            ''')
        self.assert_error(self.studio, 'POST', '/shows/early/sync', 503, 'storage_failure')
        # Archive and frontier are preserved together; the frame stays unaired locally.
        self.assert_error(self.studio, 'GET', '/shows/early/frames/0', 404, 'frame_not_aired')
        with closing(sqlite3.connect(self.studio_path)) as db:
            self.assertEqual(
                db.execute('SELECT COUNT(*) FROM aired_frames').fetchone()[0], 0)
            self.assertEqual(
                db.execute('SELECT COUNT(*) FROM test_sync_child').fetchone()[0], 0)
        # The playout's aired frames can still be fetched again.
        self.assertEqual(self.operator.tick(0, 'early'), aired('early', 0, 8, 0, 'opening-0'))
        self.assertEqual(self.operator.tick(1, 'early'), aired('early', 1, 0, 0, None))
        # Clearing the failure lets sync record the same values.
        with closing(sqlite3.connect(self.studio_path)) as db, db:
            db.execute('DROP TRIGGER test_reject_sync')
        self.assertEqual(self.studio.sync('early'), {'show': 'early', 'last_frame': 1})
        self.assertEqual(self.studio.read(0, 'early'), aired('early', 0, 8, 0, 'opening-0'))
        self.assertEqual(self.studio.read(1, 'early'), aired('early', 1, 0, 0, None))
        self.assertEqual(self.studio.sync('early'), {'show': 'early', 'last_frame': 1})

    def test_restart_reclaims_acceptance(self):
        self.open_relay_show('early')
        self.assertEqual(self.studio.stage(0, 'opening-0', 'early')['status'], 'accepted')
        self.operator.tick(0, 'early')
        self.stop_playout()
        self.start_playout()
        self.stop_studio()
        self.start_studio()
        # The studio answers from its own record without the playout.
        self.assertEqual(self.studio.stage(0, 'opening-0', 'early'), {
            'show': 'early', 'frame': 0, 'request_id': 'opening-0', 'status': 'accepted',
        })
        self.assertEqual(self.operator.tick(0, 'early'), aired('early', 0, 8, 0, 'opening-0'))
        self.assertEqual(self.studio.sync('early'), {'show': 'early', 'last_frame': 0})
        self.assertEqual(self.studio.read(0, 'early'), aired('early', 0, 8, 0, 'opening-0'))
