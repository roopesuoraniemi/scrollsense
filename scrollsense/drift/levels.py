"""Drift levels and their order of severity."""
from typing import Iterable, Literal

Level = Literal["learning", "normal", "watch", "warning"]
SEVERITY: dict[Level, int] = {"learning": 0, "normal": 1, "watch": 2, "warning": 3}
# Scores are sums of floats, so a threshold of 0.8 must still match a score of 0.8.
TOLERANCE = 1e-9


def most_severe(levels: Iterable[Level]) -> Level:
    """The most severe of `levels` (`learning` ranks lowest). Raises ValueError if empty."""
    return max(levels, key=SEVERITY.__getitem__)
