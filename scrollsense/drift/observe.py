"""A viewer's analysed Shorts in seen order, and where groups of them sit on the affect map."""
import statistics
from dataclasses import dataclass
from operator import attrgetter
from typing import Callable, Mapping, Sequence

from ..domain import ClipAnalysis
from ..schemas import ClipScores, Frozen
from ..views import ViewEvent


@dataclass(frozen=True)
class Observation:
    """The first view of one analysed Short."""

    video_id: str
    title: str
    seen_at: float
    scores: ClipScores

    @classmethod
    def of(cls, event: ViewEvent, analysis: ClipAnalysis) -> "Observation":
        return cls(video_id=event.video_id, title=analysis.package.title, seen_at=event.seen_at,
                   scores=analysis.scores)


@dataclass(frozen=True)
class Observed:
    """A viewer's analysed Shorts in seen order, and how many seen Shorts await analysis."""

    analysed: tuple[Observation, ...]
    pending: int


def first_views(events: Sequence[ViewEvent]) -> tuple[ViewEvent, ...]:
    """The first view of each Short (surface `shorts`), in seen order."""
    seen: set[str] = set()
    kept: list[ViewEvent] = []
    for event in sorted(events, key=attrgetter("seen_at")):
        if event.surface == "shorts" and event.video_id not in seen:
            seen.add(event.video_id)
            kept.append(event)
    return tuple(kept)


def observe(events: Sequence[ViewEvent], analyses: Mapping[str, ClipAnalysis]) -> Observed:
    """Join each Short's first view with its analysis; unanalysed Shorts are only counted.

    A Short seen twice counts once: drift is about what the feed brought, not replays.
    """
    views = first_views(events)
    analysed = tuple(Observation.of(e, analyses[e.video_id]) for e in views
                     if e.video_id in analyses)
    return Observed(analysed=analysed, pending=len(views) - len(analysed))


class AffectPoint(Frozen):
    """A place on the 1-5 valence x 1-5 arousal map (or a spread along both axes)."""

    valence: float
    arousal: float


class Summary(Frozen):
    """Where a group of Shorts sits on the affect map (population SD); None fields when empty."""

    n: int
    centroid: AffectPoint | None
    sd: AffectPoint | None
    first_seen_at: float | None
    last_seen_at: float | None


@dataclass(frozen=True)
class Group:
    """Analysed Shorts in seen order."""

    members: tuple[Observation, ...]

    def __len__(self) -> int:
        return len(self.members)

    def mean(self, extract: Callable[[ClipScores], float]) -> float:
        """Raises statistics.StatisticsError if the group is empty."""
        return statistics.fmean(extract(m.scores) for m in self.members)

    def last(self, n: int) -> "Group":
        return Group(self.members[-n:])

    def upto(self, end: int) -> "Group":
        """The first `end` members."""
        return Group(self.members[:end])

    def summary(self) -> Summary:
        if not self.members:
            return Summary(n=0, centroid=None, sd=None, first_seen_at=None, last_seen_at=None)
        valence = [float(m.scores.valence) for m in self.members]
        arousal = [float(m.scores.arousal) for m in self.members]
        return Summary(n=len(self.members),
                       centroid=AffectPoint(valence=statistics.fmean(valence),
                                            arousal=statistics.fmean(arousal)),
                       sd=AffectPoint(valence=statistics.pstdev(valence),
                                      arousal=statistics.pstdev(arousal)),
                       first_seen_at=self.members[0].seen_at, last_seen_at=self.members[-1].seen_at)
