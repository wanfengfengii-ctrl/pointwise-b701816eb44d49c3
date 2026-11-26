from pathlib import Path
from sqlite3 import Connection

from mix.errors import BroadcastError
from mix.values import frame_from_key, frame_key, require_frame, require_name, require_request_id
from playout.database import initialize_database, read_snapshot, write_transaction


def _require_level(value, field: str) -> int:
    if type(value) is not int or not -10 <= value <= 10:
        raise BroadcastError(400, 'invalid_request', f'{field} must be an integer between -10 and 10')
    return value


def _require_show(db: Connection, show) -> str:
    show = require_name(show, 'show')
    row = db.execute('SELECT show FROM playout_shows WHERE show = ?', (show,)).fetchone()
    if row is None:
        raise BroadcastError(404, 'unknown_show', 'show has not been prepared')
    return show


def _clock(db: Connection, show: str) -> int:
    row = db.execute('SELECT next_frame FROM playout_clock WHERE show = ?', (show,)).fetchone()
    if row is None:
        raise BroadcastError(503, 'storage_failure', 'prepared show has no frame clock')
    return frame_from_key(row['next_frame'])


def _fetch_candidate(db: Connection, show: str, frame: int):
    return db.execute('''
        SELECT request_id, left_level, right_level FROM playout_candidates
        WHERE show = ? AND frame = ?
    ''', (show, frame_key(frame))).fetchone()


class PlayoutService:
    """The playout endpoint: accepts candidates, follows the external frame clock."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        initialize_database(self.path)

    def prepare_show(self, show):
        show = require_name(show, 'show')
        with write_transaction(self.path) as db:
            db.execute('INSERT INTO playout_shows (show) VALUES (?) ON CONFLICT (show) DO NOTHING', (show,))
            db.execute(
                'INSERT INTO playout_clock (show, next_frame) VALUES (?, ?) ON CONFLICT (show) DO NOTHING',
                (show, frame_key(0)),
            )
        return show

    def accept_candidate(self, show, frame, request_id, left, right):
        with write_transaction(self.path) as db:
            show = _require_show(db, show)
            frame = require_frame(frame)
            request_id = require_request_id(request_id)
            left = _require_level(left, 'left')
            right = _require_level(right, 'right')
            document = {'show': show, 'frame': frame, 'request_id': request_id}
            next_frame = _clock(db, show)
            if frame > next_frame:
                raise BroadcastError(
                    409, 'not_next_frame', 'candidates are only accepted for the next frame to air')
            candidate = _fetch_candidate(db, show, frame)
            if frame < next_frame:
                if candidate is not None and candidate['request_id'] == request_id:
                    return {**document, 'status': 'accepted',
                            'left': candidate['left_level'], 'right': candidate['right_level']}
                return {**document, 'status': 'expired'}
            if candidate is not None:
                if candidate['request_id'] == request_id:
                    return {**document, 'status': 'accepted',
                            'left': candidate['left_level'], 'right': candidate['right_level']}
                raise BroadcastError(
                    409, 'candidate_exists', 'another candidate was already accepted for this frame')
            db.execute('''
                INSERT INTO playout_candidates (show, frame, request_id, left_level, right_level)
                VALUES (?, ?, ?, ?, ?)
            ''', (show, frame_key(frame), request_id, left, right))
            return {**document, 'status': 'accepted', 'left': left, 'right': right}

    def tick(self, show, frame):
        with write_transaction(self.path) as db:
            show = _require_show(db, show)
            frame = require_frame(frame)
            next_frame = _clock(db, show)
            if frame > next_frame:
                raise BroadcastError(409, 'not_next_frame', 'only the next frame may be ticked')
            if frame < next_frame:
                row = db.execute('''
                    SELECT left_level, right_level, request_id FROM playout_aired
                    WHERE show = ? AND frame = ?
                ''', (show, frame_key(frame))).fetchone()
                if row is None:
                    raise BroadcastError(503, 'storage_failure', 'aired frame record is missing')
                return {'show': show, 'frame': frame, 'left': row['left_level'],
                        'right': row['right_level'], 'request_id': row['request_id']}
            candidate = _fetch_candidate(db, show, frame)
            if candidate is not None:
                left, right = candidate['left_level'], candidate['right_level']
                request_id = candidate['request_id']
            else:
                left, right, request_id = 0, 0, None
            db.execute('''
                INSERT INTO playout_aired (show, frame, left_level, right_level, request_id)
                VALUES (?, ?, ?, ?, ?)
            ''', (show, frame_key(frame), left, right, request_id))
            cursor = db.execute(
                'UPDATE playout_clock SET next_frame = ? WHERE show = ? AND next_frame = ?',
                (frame_key(frame + 1), show, frame_key(frame)),
            )
            if cursor.rowcount != 1:
                raise BroadcastError(409, 'not_next_frame', 'only the next frame may be ticked')
            return {'show': show, 'frame': frame, 'left': left, 'right': right,
                    'request_id': request_id}

    def aired_since(self, show, start):
        start = require_frame(start, 'start')
        with read_snapshot(self.path) as db:
            show = _require_show(db, show)
            rows = db.execute('''
                SELECT frame, left_level, right_level, request_id FROM playout_aired
                WHERE show = ? AND frame >= ?
                ORDER BY frame
            ''', (show, frame_key(start))).fetchall()
            return [
                {'frame': frame_from_key(row['frame']), 'left': row['left_level'],
                 'right': row['right_level'], 'request_id': row['request_id']}
                for row in rows
            ]
