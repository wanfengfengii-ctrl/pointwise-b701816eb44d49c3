import http.client
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from urllib.parse import quote, urlencode

from mix.http import BroadcastHTTPServer, BroadcastRequestHandler
from mix.service import BroadcastService


def show_path(show):
    return '/shows/' + quote(show, safe='')


def frame_result(frame, left, right, show='studio'):
    return {'show': show, 'frame': frame, 'left': left, 'right': right}


class StudioClient:
    def __init__(self, port):
        self.port = port

    def request(self, method, path, data=None):
        body = None if data is None else json.dumps(data).encode('utf-8')
        headers = {} if body is None else {'Content-Type': 'application/json'}
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=12)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def expect(self, method, path, status, data=None):
        actual_status, result = self.request(method, path, data)
        if actual_status != status:
            raise AssertionError(f'{method} {path}: expected HTTP {status}, got {actual_status}: {result!r}')
        return result

    def asset(self, name, sample):
        return self.expect('POST', '/assets', 201, {'name': name, 'sample': sample})['version']

    def preview(self, version):
        return self.expect('GET', f'/assets/{version}', 200)

    def scene(self, revision, output, delay, show='studio'):
        return self.expect('POST', show_path(show) + '/scenes', 201, {
            'revision': revision, 'echo_output': output, 'echo_delay': delay,
        })

    def cue(self, version, frame, output='left', show='studio'):
        return self.expect('POST', show_path(show) + '/cues', 201, {
            'asset_version': version, 'dry_frame': frame, 'dry_output': output,
        })['cue_id']

    def stop(self, cue_id, show='studio'):
        return self.expect('POST', show_path(show) + f'/cues/{cue_id}/stop', 200)

    def emit(self, frame, show='studio'):
        return self.expect('POST', show_path(show) + '/frames', 201, {'frame': frame})

    def read(self, frame, show='studio'):
        return self.expect('GET', show_path(show) + f'/frames/{frame}', 200)

    def replay(self, start, end, show='studio'):
        query = urlencode({'start': start, 'end': end})
        return self.expect('GET', show_path(show) + '/replay?' + query, 200)['frames']


class QuietHandler(BroadcastRequestHandler):
    def log_message(self, format, *args):
        pass


@contextmanager
def running_service(service):
    with BroadcastHTTPServer(0, service, QuietHandler) as server:
        worker = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        worker.start()
        try:
            yield StudioClient(server.server_port)
        finally:
            server.shutdown()
            worker.join(timeout=5)
            if worker.is_alive():
                raise RuntimeError('HTTP fixture did not stop')


class GatedService(BroadcastService):
    def __init__(self, path, frame):
        super().__init__(path)
        self.frame = frame
        self.arrived = Event()
        self.release = Event()

    def emit_frame(self, show, frame):
        if frame == self.frame:
            self.arrived.set()
            if not self.release.wait(timeout=10):
                raise RuntimeError('frame request was never released by the fixture')
        return super().emit_frame(show, frame)


class StudioCase(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory(prefix='live-mix-test-'))
        self.path = Path(directory) / 'studio.sqlite'
        self.host = self.enterContext(ExitStack())
        self.start()

    def start(self, service=None):
        self.host.close()
        self.service = service if service is not None else BroadcastService(self.path)
        self.service.prepare_show('studio')
        self.api = self.host.enter_context(running_service(self.service))

    def assert_error(self, method, path, status, code, data=None):
        result = self.api.expect(method, path, status, data)
        self.assertEqual(result['error'], code)
        self.assertTrue(result['message'])

    def assert_air(self, frame, left, right, show='studio'):
        expected = frame_result(frame, left, right, show)
        self.assertEqual(self.api.emit(frame, show), expected)
        self.assertEqual(self.api.read(frame, show), expected)

    @contextmanager
    def paused_emission(self, frame):
        service = GatedService(self.path, frame)
        self.start(service)
        with ThreadPoolExecutor(max_workers=1) as worker:
            pending = worker.submit(self.api.emit, frame)
            try:
                if not service.arrived.wait(timeout=5):
                    if pending.done():
                        pending.result()
                    self.fail('HTTP frame request did not reach the emission gate')
                yield pending
            finally:
                service.release.set()
