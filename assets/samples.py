from dataclasses import dataclass

from mix.errors import BroadcastError


@dataclass(frozen=True)
class AssetVersion:
    version: int
    name: str
    sample: int


def validate_sample(sample) -> int:
    if type(sample) is not int:
        raise BroadcastError(400, 'invalid_sample', 'sample must be a signed integer')
    return sample
