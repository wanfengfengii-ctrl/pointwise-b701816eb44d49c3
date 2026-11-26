from tests.support import StudioCase, frame_result


class LiveTests(StudioCase):
    def _scene_change(self):
        self.api.scene('opening', 'left', 2)
        cue_a = self.api.cue(self.api.asset('A', 8), 0)
        self.assert_air(0, 8, 0)
        self.api.scene('next', 'right', 1)
        self.api.cue(self.api.asset('B', 6), 2)
        self.assert_air(1, 0, 0)
        return cue_a

    def test_unknown_asset(self):
        self.api.scene('opening', 'right', 2)
        path = '/shows/studio/cues'
        for version in (999, 2 ** 70):
            self.assert_error('POST', path, 404, 'unknown_asset', {
                'asset_version': version, 'dry_frame': 0, 'dry_output': 'left',
            })
        for frame in range(3):
            self.assert_air(frame, 0, 0)

    def test_past_dry_frame(self):
        self.api.scene('opening', 'right', 2)
        version = self.api.asset('chime', 5)
        self.assert_air(0, 0, 0)
        path = '/shows/studio/cues'
        self.assert_error('POST', path, 409, 'dry_frame_aired', {
            'asset_version': version, 'dry_frame': 0, 'dry_output': 'left',
        })
        self.assert_error('POST', path, 400, 'invalid_frame', {
            'asset_version': version, 'dry_frame': True, 'dry_output': 'left',
        })
        self.api.cue(version, 1)
        self.assert_air(1, 5, 0)
        self.assert_air(2, 0, 0)
        self.assert_air(3, 0, 5)
        self.assertEqual(self.api.read(0), frame_result(0, 0, 0))

    def test_blend_and_clip(self):
        self.api.scene('opening', 'right', 2)
        for sample in (8, 6, -6):
            self.api.cue(self.api.asset(f'sample-{sample}', sample), 0)
        self.assert_air(0, 8, 0)
        self.assert_air(1, 0, 0)
        self.assert_air(2, 0, 8)

    def test_routed_echo(self):
        self.api.scene('opening', 'right', 2)
        self.api.cue(self.api.asset('short-echo', 3), 0)
        for sample in (8, 6, -6):
            self.api.cue(self.api.asset(f'sample-{sample}', sample), 2)
        self.assert_air(0, 3, 0)
        self.assert_air(1, 0, 0)
        self.assert_air(2, 8, 3)
        self.assert_air(3, 0, 0)
        self.assert_air(4, 0, 8)

    def test_stereo_bounds(self):
        self.api.scene('opening', 'right', 2)
        for sample, output in ((8, 'left'), (6, 'left'), (-8, 'right'), (-6, 'right')):
            self.api.cue(self.api.asset(output, sample), 0, output)
        self.assert_air(0, 10, -10)
        self.assert_air(1, 0, 0)
        self.assert_air(2, 0, 0)

    def test_exact_large_integers(self):
        magnitude = 2 ** 100
        self.api.scene('long decay', 'right', 2 ** 90)
        for sample in (magnitude, 7, -magnitude):
            version = self.api.asset('wide sample', sample)
            self.assertEqual(self.api.preview(version)['sample'], sample)
            self.api.cue(version, 0)
        self.assert_air(0, 7, 0)
        self.assert_air(1, 0, 0)
        self.assert_error('GET', f'/shows/studio/frames/{2 ** 90}', 404, 'frame_not_aired')
        self.api.cue(self.api.asset('future sound', 3), 2 ** 95)
        self.assert_air(2, 0, 0)

    def test_scene_change_with_pending_echo(self):
        self._scene_change()
        self.assert_air(2, 10, 0)
        self.assert_air(3, 0, 6)
        self.assertEqual(self.api.replay(0, 3), [
            frame_result(0, 8, 0), frame_result(1, 0, 0), frame_result(2, 10, 0), frame_result(3, 0, 6),
        ])

    def test_deferred_scene(self):
        version = self.api.asset('same sample', 4)
        self.api.scene('opening', 'left', 2)
        old_cue = self.api.cue(version, 0)
        with self.paused_emission(0) as pending:
            self.api.scene('next', 'right', 1)
            new_cue = self.api.cue(version, 2)
            self.assertNotEqual(old_cue, new_cue)
            self.assert_error('GET', '/shows/studio/frames/0', 404, 'frame_not_aired')
        self.assertEqual(pending.result(), frame_result(0, 4, 0))
        self.assert_air(1, 0, 0)
        self.assert_air(2, 8, 0)
        self.assert_air(3, 0, 4)

    def test_stop_one_overlapping_cue(self):
        cue_a = self._scene_change()
        self.assertEqual(self.api.stop(cue_a), {'cue_id': cue_a, 'stopped': True})
        self.assert_air(2, 6, 0)
        self.assert_air(3, 0, 6)
        self.assertEqual(self.api.read(0), frame_result(0, 8, 0))

    def test_same_asset(self):
        self.api.scene('opening', 'right', 1)
        version = self.api.asset('bell', 4)
        a = self.api.cue(version, 0)
        b = self.api.cue(version, 0)
        self.assertNotEqual(a, b)
        self.assertEqual(self.api.stop(a), {'cue_id': a, 'stopped': True})
        self.assertEqual(self.api.stop(a), {'cue_id': a, 'stopped': True})
        self.assert_air(0, 4, 0)
        self.assert_air(1, 0, 4)

    def test_stop_commits_before_waiting_frame(self):
        cue_a = self._scene_change()
        with self.paused_emission(2) as pending:
            self.assertEqual(self.api.stop(cue_a), {'cue_id': cue_a, 'stopped': True})
            self.assert_error('GET', '/shows/studio/frames/2', 404, 'frame_not_aired')
        self.assertEqual(pending.result(), frame_result(2, 6, 0))
        self.assertEqual(self.api.read(2), frame_result(2, 6, 0))
        self.assert_air(3, 0, 6)
        self.assertEqual(self.api.read(0), frame_result(0, 8, 0))

    def test_frame_commits_before_stop(self):
        cue_a = self._scene_change()
        with self.paused_emission(2) as pending:
            self.assert_error('GET', '/shows/studio/frames/2', 404, 'frame_not_aired')
        self.assertEqual(pending.result(), frame_result(2, 10, 0))
        self.assertEqual(self.api.stop(cue_a), {'cue_id': cue_a, 'stopped': True})
        self.assertEqual(self.api.read(2), frame_result(2, 10, 0))
        self.assert_air(3, 0, 6)

    def test_foreign_stop(self):
        self.service.prepare_show('other')
        self.api.scene('opening', 'right', 1, 'other')
        self.api.scene('opening', 'left', 2)
        cue = self.api.cue(self.api.asset('bell', 5), 0)
        self.assert_error('POST', f'/shows/other/cues/{cue}/stop', 404, 'unknown_cue')
        self.assert_error('POST', '/shows/studio/cues/999/stop', 404, 'unknown_cue')
        self.assert_air(0, 0, 0, 'other')
        self.assert_air(0, 5, 0)
        self.assert_air(1, 0, 0)
        self.assert_air(2, 5, 0)
