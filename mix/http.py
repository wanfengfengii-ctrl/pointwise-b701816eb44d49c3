import argparse
import json
import sys
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from mix.errors import BroadcastError
from mix.service import BroadcastService


MAX_BODY_BYTES = 65536


def _decimal(value: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise BroadcastError(400, 'invalid_request', 'expected a decimal integer in the URL')
    try:
        return int(value)
    except ValueError as error:
        raise BroadcastError(400, 'invalid_request', 'integer text is too long') from error


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f'{value} is not a JSON constant')


class BroadcastRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._handle('GET')

    def do_POST(self):
        self._handle('POST')

    def _handle(self, method):
        try:
            status, payload = self._dispatch(method)
        except BroadcastError as error:
            status = error.status
            payload = {'error': error.code, 'message': str(error)}
        try:
            self._reply(status, payload)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def _reply(self, status, payload):
        body = json.dumps(payload, ensure_ascii=True, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self, *fields):
        lengths = self.headers.get_all('Content-Length', [])
        if self.headers.get('Transfer-Encoding') or len(lengths) > 1:
            raise BroadcastError(400, 'invalid_request', 'expected one fixed-length request body')
        length = _decimal(lengths[0]) if lengths else 0
        if length > MAX_BODY_BYTES:
            raise BroadcastError(413, 'body_too_large', 'request body exceeds 65536 bytes')
        if length == 0 and not fields:
            return {}
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise BroadcastError(400, 'invalid_request', 'request body is incomplete')
        try:
            data = json.loads(raw.decode('utf-8'), object_pairs_hook=_json_object, parse_constant=_invalid_constant)
        except (ValueError, RecursionError) as error:
            raise BroadcastError(400, 'invalid_request', 'expected a UTF-8 JSON object') from error
        if not isinstance(data, dict) or data.keys() != set(fields):
            raise BroadcastError(400, 'invalid_request', f'expected exactly these fields: {", ".join(fields)}')
        return data

    def _target(self):
        try:
            target = urlsplit(self.path)
            if target.scheme or target.netloc or target.fragment or not target.path.startswith('/'):
                raise ValueError('invalid request target')
            parts = [unquote(part, errors='strict') for part in target.path[1:].split('/')]
            query = parse_qs(target.query, keep_blank_values=True, strict_parsing=True,
                             max_num_fields=2, errors='strict')
        except ValueError as error:
            raise BroadcastError(400, 'invalid_request', 'malformed URL') from error
        return parts, query

    def _dispatch(self, method):
        parts, query = self._target()
        service = self.server.service
        if method == 'GET' and len(parts) == 3 and parts[0] == 'shows' and parts[2] == 'replay':
            if query.keys() != {'start', 'end'} or any(len(values) != 1 for values in query.values()):
                raise BroadcastError(400, 'invalid_request', 'replay requires one start and one end')
            start = _decimal(query['start'][0])
            end = _decimal(query['end'][0])
            return 200, {'frames': [asdict(frame) for frame in service.replay_frames(parts[1], start, end)]}
        if query:
            raise BroadcastError(400, 'invalid_request', 'this endpoint takes no query parameters')
        match method, parts:
            case 'GET', ['ready']:
                return 200, {'ready': True}
            case 'POST', ['assets']:
                return 201, asdict(service.register_asset(**self._body('name', 'sample')))
            case 'GET', ['assets', version]:
                return 200, asdict(service.preview_asset(_decimal(version)))
            case 'POST', ['shows', show, 'scenes']:
                return 201, asdict(service.publish_scene(show, **self._body('revision', 'echo_output', 'echo_delay')))
            case 'POST', ['shows', show, 'cues']:
                cue_id = service.accept_cue(show, **self._body('asset_version', 'dry_frame', 'dry_output'))
                return 201, {'cue_id': cue_id}
            case 'POST', ['shows', show, 'cues', cue, 'stop']:
                self._body()
                return 200, {'cue_id': service.stop_cue(show, _decimal(cue)), 'stopped': True}
            case 'POST', ['shows', show, 'frames']:
                return 201, asdict(service.emit_frame(show, **self._body('frame')))
            case 'GET', ['shows', show, 'frames', frame]:
                return 200, asdict(service.read_frame(show, _decimal(frame)))
            case _:
                raise BroadcastError(404, 'unknown_endpoint', 'endpoint does not exist')


class BroadcastHTTPServer(ThreadingHTTPServer):
    def __init__(self, port: int, service: BroadcastService, handler=BroadcastRequestHandler, *, host='127.0.0.1'):
        if host != '127.0.0.1':
            raise ValueError('studio server must listen on 127.0.0.1')
        self.service = service
        super().__init__((host, port), handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Serve a local live sound-effects studio')
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--show', required=True, action='append')
    parser.add_argument('--host', default='127.0.0.1', choices=('127.0.0.1',))
    parser.add_argument('--port', type=int, default=8765, choices=range(0, 65536), metavar='PORT')
    parser.add_argument('--init-only', action='store_true')
    args = parser.parse_args(argv)
    try:
        service = BroadcastService(args.db)
        for show in args.show:
            service.prepare_show(show)
        if args.init_only:
            return 0
        with BroadcastHTTPServer(args.port, service, host=args.host) as server:
            print(f'Live mix listening on 127.0.0.1:{server.server_port}', flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except (BroadcastError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
