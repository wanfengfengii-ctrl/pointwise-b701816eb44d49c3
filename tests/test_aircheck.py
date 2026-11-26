import sqlite3
from contextlib import closing

from tests.support import StudioCase, frame_result


class AircheckTests(StudioCase):
    def test_gap_rejected(self):
        self.api.scene('opening', 'right', 1)
        self.assert_error('POST', '/shows/studio/frames', 409, 'not_next_frame', {'frame': 1})
        self.assert_error('GET', '/shows/studio/frames/1', 404, 'frame_not_aired')
        self.api.cue(self.api.asset('bell', 5), 0)
        self.assert_air(0, 5, 0)
        self.assert_error('POST', '/shows/studio/frames', 409, 'not_next_frame', {'frame': 0})
        self.assert_air(1, 0, 5)
        self.assertEqual(self.api.replay(0, 1), [frame_result(0, 5, 0), frame_result(1, 0, 5)])

    def test_empty_frame(self):
        self.api.scene('opening', 'left', 2)
        self.assert_air(0, 0, 0)
        self.assert_air(1, 0, 0)
        self.assertEqual(self.api.replay(0, 1), [frame_result(0, 0, 0), frame_result(1, 0, 0)])

    def test_commit_rollback(self):
        self.api.scene('opening', 'right', 1)
        self.api.cue(self.api.asset('door', 7), 1)
        self.assert_air(0, 0, 0)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE test_commit_parent (id INTEGER PRIMARY KEY)')
            db.execute('''
                CREATE TABLE test_commit_child (
                    parent_id INTEGER NOT NULL REFERENCES test_commit_parent (id) DEFERRABLE INITIALLY DEFERRED
                )
            ''')
            db.execute('''
                CREATE TRIGGER test_reject_commit AFTER INSERT ON aired_frames
                BEGIN
                    INSERT INTO test_commit_child (parent_id) VALUES (1);
                END
            ''')
        self.assert_error('POST', '/shows/studio/frames', 503, 'storage_failure', {'frame': 1})
        self.assert_error('GET', '/shows/studio/frames/1', 404, 'frame_not_aired')
        self.assertEqual(self.api.read(0), frame_result(0, 0, 0))
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM test_commit_child').fetchone()[0], 0)
            db.execute('DROP TRIGGER test_reject_commit')
        self.assert_air(1, 7, 0)
        self.assert_error('POST', '/shows/studio/frames', 409, 'not_next_frame', {'frame': 1})
        self.assert_air(2, 0, 7)
        self.assertEqual(self.api.replay(0, 2), [frame_result(0, 0, 0), frame_result(1, 7, 0), frame_result(2, 0, 7)])

    def test_restart(self):
        a = self.api.asset('bell', 8)
        b = self.api.asset('other', 6)
        newer_a = self.api.asset('bell', -3)
        self.api.scene('opening', 'left', 2)
        cue_a = self.api.cue(a, 0)
        self.assert_air(0, 8, 0)
        self.api.scene('next', 'right', 1)
        self.api.cue(b, 2)
        self.api.stop(cue_a)
        self.service.prepare_show('studio')
        self.start()
        self.assertEqual(self.api.preview(a)['sample'], 8)
        self.assertEqual(self.api.preview(newer_a)['sample'], -3)
        self.assertEqual(self.api.read(0), frame_result(0, 8, 0))
        self.assert_error('POST', '/shows/studio/frames', 409, 'not_next_frame', {'frame': 0})
        self.api.cue(newer_a, 1, 'right')
        self.assert_air(1, 0, -3)
        self.assert_air(2, 6, -3)
        self.assert_air(3, 0, 6)
        self.assertEqual(self.api.stop(cue_a), {'cue_id': cue_a, 'stopped': True})

    def test_only_aired_frames(self):
        self.api.scene('opening', 'right', 2)
        cue = self.api.cue(self.api.asset('door', 8), 0)
        self.assert_error('GET', '/shows/studio/frames/0', 404, 'frame_not_aired')
        self.assert_air(0, 8, 0)
        self.api.stop(cue)
        self.assertEqual(self.api.read(0), frame_result(0, 8, 0))
        self.assert_air(1, 0, 0)
        self.assert_air(2, 0, 0)

    def test_stop_after_air(self):
        self.api.scene('opening', 'left', 2)
        a = self.api.cue(self.api.asset('A', 8), 0)
        self.assert_air(0, 8, 0)
        self.api.scene('next', 'right', 1)
        self.api.cue(self.api.asset('B', 6), 2)
        self.assert_air(1, 0, 0)
        self.assert_air(2, 10, 0)
        self.api.stop(a)
        self.assertEqual(self.api.read(0), frame_result(0, 8, 0))
        self.assertEqual(self.api.read(2), frame_result(2, 10, 0))
        self.assert_air(3, 0, 6)

    def test_replay_order(self):
        self.api.scene('opening', 'right', 2)
        self.api.cue(self.api.asset('step', 7), 8)
        self.api.cue(self.api.asset('tap', -2), 11)
        for frame in range(12):
            self.api.emit(frame)
        self.assertEqual(self.api.replay(8, 11), [
            frame_result(8, 7, 0), frame_result(9, 0, 0), frame_result(10, 0, 7), frame_result(11, -2, 0),
        ])

    def test_range_unpublished(self):
        self.api.scene('opening', 'right', 1)
        self.api.cue(self.api.asset('door', 8), 0)
        self.assert_air(0, 8, 0)
        self.assert_error('GET', '/shows/studio/replay?start=0&end=1', 404, 'frame_not_aired')
        self.assert_error('GET', '/shows/studio/replay?start=1&end=0', 400, 'invalid_range')
        self.assert_error('GET', '/shows/studio/replay?start=0&start=1', 400, 'invalid_request')
        self.assert_air(1, 0, 8)
        self.assertEqual(self.api.replay(0, 1), [frame_result(0, 8, 0), frame_result(1, 0, 8)])
