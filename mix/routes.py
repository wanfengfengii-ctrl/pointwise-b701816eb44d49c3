from dataclasses import dataclass

from cues.dispatch import PlaybackIntent


@dataclass(frozen=True)
class Contribution:
    show: str
    cue_id: int
    kind: str
    frame: int
    output: str
    sample: int


def route_contributions(intent: PlaybackIntent) -> tuple[Contribution, Contribution]:
    dry = Contribution(intent.show, intent.cue_id, 'dry', intent.dry_frame, intent.dry_output, intent.sample)
    echo = Contribution(intent.show, intent.cue_id, 'echo', intent.dry_frame + intent.echo_delay,
                        intent.echo_output, intent.sample)
    return dry, echo
