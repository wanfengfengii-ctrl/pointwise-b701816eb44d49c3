"""Loopback process and transport fixtures for the studio's HTTP examples."""
import http.client
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, Queue
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread

from tests.support import StudioClient


_ADDRESS = re.compile(r'\b127\.0\.0\.1:(\d+)\b')


@contextmanager
def running_endpoint(*argv):
    command = [sys.executable, '-B', '-u', *argv, '--host', '127.0.0.1', '--port', '0']
    announced = Queue()
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as process:
        def read_stdout():
            published = False
            for line in process.stdout:
                if not published and (match := _ADDRESS.search(line)):
                    announced.put(int(match.group(1)))
                    published = True
            if not published:
                announced.put(None)

        reader = Thread(target=read_stdout, daemon=True)
        reader.start()
        try:
            try:
                port = announced.get(timeout=10)
            except Empty as error:
                raise RuntimeError(f'endpoint did not announce its address: {argv!r}') from error
            if port is None:
                raise RuntimeError(f'endpoint exited before announcing its address: {argv!r}')
            api = StudioClient(port)
            ready = api.expect('GET', '/ready', 200)
            if ready != {'ready': True}:
                raise AssertionError(f'expected readiness document, got {ready!r}')
            yield api
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            reader.join(timeout=5)


@dataclass
class Interception:
    method: str
    path: str | None
    drop: bool
    arrived: Event = field(default_factory=Event)
    release: Event = field(default_factory=Event)
    finished: Event = field(default_factory=Event)
    upstream_status: int | None = None


class _ForwardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._forward()

    def do_POST(self):
        self._forward()

    def log_message(self, format, *args):
        pass

    def _forward(self):
        length = int(self.headers.get('Content-Length', '0'))
        body = self.rfile.read(length) if length else None
        headers = {}
        if self.headers.get('Content-Type'):
            headers['Content-Type'] = self.headers['Content-Type']
        gate = self.server.take_interception(self.command, self.path)
        if gate is not None:
            gate.arrived.set()
            if not gate.release.wait(timeout=8):
                self.send_error(504, 'fixture did not release the request')
                return
        connection = http.client.HTTPConnection('127.0.0.1', self.server.upstream_port, timeout=8)
        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            reply = connection.getresponse()
            status = reply.status
            content_type = reply.getheader('Content-Type')
            payload = reply.read()
        except (OSError, http.client.HTTPException):
            self.send_error(502, 'fixture could not read the upstream response')
            return
        finally:
            connection.close()
        if gate is not None:
            gate.upstream_status = status
            gate.finished.set()
            if gate.drop:
                self.close_connection = True
                return
        try:
            self.send_response(status)
            if content_type:
                self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True


class _Forwarder(ThreadingHTTPServer):
    def __init__(self, upstream_port):
        self.upstream_port = upstream_port
        self._lock = Lock()
        self._armed = None
        super().__init__(('127.0.0.1', 0), _ForwardHandler)

    @property
    def address(self):
        return f'http://127.0.0.1:{self.server_port}'

    def intercept_once(self, method, path=None, *, hold=False, drop=False):
        gate = Interception(method, path, drop)
        if not hold:
            gate.release.set()
        with self._lock:
            if self._armed is not None:
                raise RuntimeError('an interception is already armed')
            self._armed = gate
        return gate

    def take_interception(self, method, path):
        with self._lock:
            gate = self._armed
            if gate is not None and gate.method == method and gate.path in (None, path):
                self._armed = None
                return gate
        return None


@contextmanager
def forwarding(upstream_port):
    with _Forwarder(upstream_port) as proxy:
        worker = Thread(target=proxy.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        worker.start()
        try:
            yield proxy
        finally:
            proxy.shutdown()
            worker.join(timeout=5)
            if worker.is_alive():
                raise RuntimeError('HTTP forwarder did not stop')


def main():
    with TemporaryDirectory(prefix='studio-relay-fixture-') as directory:
        path = Path(directory) / 'studio.sqlite'
        command = ('-m', 'mix.http', '--db', str(path), '--show', 'studio')
        expected = {'version': 1, 'name': 'fixture-bell', 'sample': 8}
        with running_endpoint(*command) as direct, forwarding(direct.port) as proxy:
            client = StudioClient(proxy.server_port)
            with ThreadPoolExecutor(max_workers=1) as worker:
                gate = proxy.intercept_once('POST', '/assets', hold=True, drop=True)
                response = worker.submit(client.asset, 'fixture-bell', 8)
                try:
                    if not gate.arrived.wait(timeout=5):
                        raise AssertionError('asset submission never reached the transport gate')
                    missing = direct.expect('GET', '/assets/1', 404)
                    if missing['error'] != 'unknown_asset':
                        raise AssertionError(f'wrong pre-delivery state: {missing!r}')
                finally:
                    gate.release.set()
                try:
                    response.result(timeout=12)
                except http.client.RemoteDisconnected:
                    pass
                else:
                    raise AssertionError('asset submission received the reply that should be dropped')
                if not gate.finished.is_set() or gate.upstream_status != 201:
                    raise AssertionError('upstream did not successfully complete the submitted request')
            if client.preview(1) != expected:
                raise AssertionError('ordinary forwarded read did not return the posted asset')
        with running_endpoint(*command) as reopened:
            actual = reopened.preview(1)
            if actual != expected:
                raise AssertionError(f'reopened endpoint returned {actual!r}')
            print(f'V1 transport probe recovered asset {actual!r} after a held request and a lost reply')


if __name__ == '__main__':
    main()
