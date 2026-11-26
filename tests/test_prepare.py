from tests.support import StudioCase


class PrepareTests(StudioCase):
    def test_asset_preview(self):
        version = self.api.asset('door', 8)
        self.assertEqual(self.api.preview(version), {'version': version, 'name': 'door', 'sample': 8})
        self.assert_error('GET', '/assets/999', 404, 'unknown_asset')

    def test_asset_version_history(self):
        first = self.api.asset('door', 8)
        second = self.api.asset('door', -3)
        self.assertNotEqual(first, second)
        self.assertEqual(self.api.preview(second), {'version': second, 'name': 'door', 'sample': -3})
        self.assertEqual(self.api.preview(first), {'version': first, 'name': 'door', 'sample': 8})
        self.api.scene('opening', 'right', 2)
        self.api.cue(first, 0)
        self.api.cue(second, 1)
        self.assert_air(0, 8, 0)
        self.assert_air(1, -3, 0)
        self.assert_air(2, 0, 8)
        self.assert_air(3, 0, -3)

    def test_invalid_sample(self):
        first = self.api.asset('door', 8)
        for invalid in (True, False, 1.5, '8', None, []):
            with self.subTest(sample=invalid):
                self.assert_error('POST', '/assets', 400, 'invalid_sample', {'name': 'door', 'sample': invalid})
        self.assert_error('POST', '/assets', 400, 'invalid_request', {'name': 'door'})
        self.assert_error('POST', '/assets', 400, 'invalid_name', {'name': ' ', 'sample': 1})
        self.assert_error('GET', f'/assets/{first + 1}', 404, 'unknown_asset')
        self.assertEqual(self.api.preview(first)['sample'], 8)
        zero = self.api.asset('silence', 0)
        self.assertEqual(self.api.preview(zero)['sample'], 0)

    def test_first_publish(self):
        cue = {'asset_version': self.api.asset('chime', 5), 'dry_frame': 0, 'dry_output': 'left'}
        self.assert_error('POST', '/shows/studio/cues', 409, 'show_not_open', cue)
        invalid = {'revision': 'opening', 'echo_output': 'right', 'echo_delay': False}
        self.assert_error('POST', '/shows/studio/scenes', 400, 'invalid_delay', invalid)
        self.assert_error('POST', '/shows/studio/cues', 409, 'show_not_open', cue)
        self.assert_error('POST', '/shows/unknown/scenes', 404, 'unknown_show', {
            'revision': 'opening', 'echo_output': 'right', 'echo_delay': 1,
        })
        self.assertEqual(self.api.scene('opening', 'right', 1), {
            'show': 'studio', 'revision': 'opening', 'echo_output': 'right', 'echo_delay': 1,
        })
        self.api.cue(cue['asset_version'], 0)
        self.assert_air(0, 5, 0)
        self.assert_air(1, 0, 5)

    def test_reject_zero_delay(self):
        self.api.scene('opening', 'left', 2)
        path = '/shows/studio/scenes'
        for delay in (0, -1, True, 1.0, '2', None):
            with self.subTest(delay=delay):
                self.assert_error('POST', path, 400, 'invalid_delay', {
                    'revision': 'change', 'echo_output': 'right', 'echo_delay': delay,
                })
        self.assert_error('POST', path, 400, 'invalid_output', {
            'revision': 'change', 'echo_output': 'middle', 'echo_delay': 1,
        })
        self.assert_error('POST', path, 409, 'revision_exists', {
            'revision': 'opening', 'echo_output': 'right', 'echo_delay': 1,
        })
        self.api.cue(self.api.asset('door', 8), 0, 'right')
        self.assert_air(0, 0, 8)
        self.assert_air(1, 0, 0)
        self.assert_air(2, 8, 0)
        self.assertEqual(self.api.scene('change', 'right', 1)['revision'], 'change')
