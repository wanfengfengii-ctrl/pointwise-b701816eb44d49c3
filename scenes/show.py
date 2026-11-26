from sqlite3 import Connection

from mix.errors import BroadcastError
from mix.values import require_name
from scenes.store import ShowState, fetch_show, insert_show_if_missing


def ensure_show(db: Connection, show) -> ShowState:
    show = require_name(show, 'show')
    insert_show_if_missing(db, show)
    return require_show(db, show)


def require_show(db: Connection, show) -> ShowState:
    state = fetch_show(db, require_name(show, 'show'))
    if state is None:
        raise BroadcastError(404, 'unknown_show', 'show has not been prepared')
    return state
