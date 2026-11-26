from mix.errors import BroadcastError


MAX_ROW_ID = (1 << 63) - 1


def require_name(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BroadcastError(400, 'invalid_name', f'{field} must be nonempty text')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as error:
        raise BroadcastError(400, 'invalid_name', f'{field} must be valid Unicode') from error
    return value


def require_id(value, field: str) -> int:
    if type(value) is not int or value < 1:
        raise BroadcastError(400, 'invalid_id', f'{field} must be a positive integer')
    return value


def require_frame(value, field: str = 'frame') -> int:
    if type(value) is not int or value < 0:
        raise BroadcastError(400, 'invalid_frame', f'{field} must be a nonnegative integer')
    return value


def frame_key(frame: int) -> bytes:
    # Among nonnegative integers, magnitude-byte length sorts before magnitude.
    width = max(1, (frame.bit_length() + 7) // 8)
    return width.to_bytes(4, 'big') + frame.to_bytes(width, 'big')


def frame_from_key(key: bytes) -> int:
    return int.from_bytes(key[4:], 'big')
