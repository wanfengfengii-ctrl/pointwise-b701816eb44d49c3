from collections.abc import Iterable
from dataclasses import dataclass

from mix.routes import Contribution


@dataclass(frozen=True)
class StereoLevels:
    left: int
    right: int


def _clip(sample: int) -> int:
    return min(10, max(-10, sample))


def sum_stereo(contributions: Iterable[Contribution]) -> StereoLevels:
    totals = {'left': 0, 'right': 0}
    for contribution in contributions:
        totals[contribution.output] += contribution.sample
    return StereoLevels(_clip(totals['left']), _clip(totals['right']))
