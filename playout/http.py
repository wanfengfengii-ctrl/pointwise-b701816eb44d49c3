import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from mix.errors import BroadcastError
from playout.service import PlayoutService


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


class PlayoutRequestHandler(BaseHTTPRequestHandler):
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
        if method == 'GET' and len(parts) == 3 and parts[0] == 'shows' and parts[2] == 'aired':
            if query.keys() != {'start'} or any(len(values) != 1 for values in query.values()):
                raise BroadcastError(400, 'invalid_request', 'aired evidence requires one start')
            start = _decimal(query['start'][0])
            return 200, {'frames': service.aired_since(parts[1], start)}
        if query:
            raise BroadcastError(400, 'invalid_request', 'this endpoint takes no query parameters')
        match method, parts:
            case 'GET', ['ready']:
                return 200, {'ready': True}
            case 'POST', ['shows', show, 'tick']:
                return 200, service.tick(show, **self._body('frame'))
            case 'POST', ['shows', show, 'candidates']:
                return 200, service.accept_candidate(
                    show, **self._body('frame', 'request_id', 'left', 'right'))
            case _:
                raise BroadcastError(404, 'unknown_endpoint', 'endpoint does not exist')


class PlayoutHTTPServer(ThreadingHTTPServer):
    def __init__(self, port: int, service: PlayoutService, handler=PlayoutRequestHandler, *, host='127.0.0.1'):
        if host != '127.0.0.1':
            raise ValueError('playout server must listen on 127.0.0.1')
        self.service = service
        super().__init__((host, port), handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Serve a local relay playout endpoint')
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--show', required=True, action='append')
    parser.add_argument('--host', default='127.0.0.1', choices=('127.0.0.1',))
    parser.add_argument('--port', type=int, default=8766, choices=range(0, 65536), metavar='PORT')
    parser.add_argument('--init-only', action='store_true')
    args = parser.parse_args(argv)
    try:
        service = PlayoutService(args.db)
        for show in args.show:
            service.prepare_show(show)
        if args.init_only:
            return 0
        with PlayoutHTTPServer(args.port, service, host=args.host) as server:
            print(f'Relay playout listening on 127.0.0.1:{server.server_port}', flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except (BroadcastError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
