from dataclasses import dataclass

from mix.errors import BroadcastError
from mix.values import require_name


@dataclass(frozen=True)
class SceneDraft:
    revision: str
    echo_output: str
    echo_delay: int


def validate_output(value, field: str = 'output') -> str:
    if not isinstance(value, str) or value not in ('left', 'right'):
        raise BroadcastError(400, 'invalid_output', f'{field} must be left or right')
    return value


def validate_draft(revision, echo_output, echo_delay) -> SceneDraft:
    revision = require_name(revision, 'revision')
    echo_output = validate_output(echo_output, 'echo_output')
    if type(echo_delay) is not int or echo_delay <= 0:
        raise BroadcastError(400, 'invalid_delay', 'echo_delay must be a positive integer')
    return SceneDraft(revision, echo_output, echo_delay)
