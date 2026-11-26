from sqlite3 import Connection

from cues.dispatch import load_playback_intents
from mix.routes import Contribution, route_contributions


def contributions_for_frame(db: Connection, show: str, frame: int) -> list[Contribution]:
    # The connection belongs to the same write transaction that will air this frame.
    contributions = []
    for intent in load_playback_intents(db, show):
        for contribution in route_contributions(intent):
            if contribution.frame == frame:
                contributions.append(contribution)
    return contributions
