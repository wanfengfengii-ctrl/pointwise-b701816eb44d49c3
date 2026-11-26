import http.client
import json
from urllib.parse import quote, urlsplit


class PlayoutUnavailable(Exception):
    """The playout endpoint's decision could not be determined."""


class PlayoutClient:
    """Loopback HTTP client for one relay show's playout endpoint."""

    def __init__(self, base_url: str):
        parts = urlsplit(base_url)
        if parts.scheme != 'http' or not parts.hostname or parts.port is None:
            raise ValueError(f'invalid relay base URL: {base_url!r}')
        self.host = parts.hostname
        self.port = parts.port

    def _request(self, method: str, path: str, payload=None):
        body = None if payload is None else json.dumps(payload).encode('utf-8')
        headers = {} if body is None else {'Content-Type': 'application/json'}
        connection = http.client.HTTPConnection(self.host, self.port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            status = response.status
            document = json.loads(raw.decode('utf-8'))
        except (OSError, http.client.HTTPException, ValueError, UnicodeDecodeError) as error:
            raise PlayoutUnavailable(f'playout endpoint did not answer: {error}') from error
        finally:
            connection.close()
        if not isinstance(document, dict):
            raise PlayoutUnavailable('playout endpoint returned a non-object response')
        return status, document

    def post_candidate(self, show: str, frame: int, request_id: str, left: int, right: int):
        path = f'/shows/{quote(show, safe="")}/candidates'
        return self._request('POST', path, {
            'frame': frame, 'request_id': request_id, 'left': left, 'right': right,
        })

    def aired_since(self, show: str, start: int) -> list[dict]:
        path = f'/shows/{quote(show, safe="")}/aired?start={start}'
        status, document = self._request('GET', path)
        if status != 200:
            raise PlayoutUnavailable(f'aired evidence request returned HTTP {status}')
        frames = document.get('frames')
        if not isinstance(frames, list):
            raise PlayoutUnavailable('aired evidence response is missing its frame list')
        return [_validate_aired(item) for item in frames]


def _validate_aired(item) -> dict:
    if not isinstance(item, dict):
        raise PlayoutUnavailable('aired evidence entry is not an object')
    frame, left, right = item.get('frame'), item.get('left'), item.get('right')
    request_id = item.get('request_id')
    if type(frame) is not int or frame < 0:
        raise PlayoutUnavailable('aired evidence entry has an invalid frame')
    for level in (left, right):
        if type(level) is not int or not -10 <= level <= 10:
            raise PlayoutUnavailable('aired evidence entry has an invalid level')
    if request_id is not None and not isinstance(request_id, str):
        raise PlayoutUnavailable('aired evidence entry has an invalid request_id')
    return {'frame': frame, 'left': left, 'right': right, 'request_id': request_id}
