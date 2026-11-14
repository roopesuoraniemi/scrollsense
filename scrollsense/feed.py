"""Feed composition and the readout against a baseline and a control, as pure functions.

These numbers describe what a feed *showed*, not how anyone feels. Thresholds are
hackathon defaults, picked to be visible in a demo, not validated.
"""
import math
import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence, get_args

from .domain import ClipAnalysis
from .schemas import CRITERIA, Criterion, Format, Frozen
from .views import ViewEvent, Window

NIGHT_END_HOUR = 5
NEGATIVE_VALENCE_MAX = 2
THEME_SCORE_MIN = 2
DWELLING = "dwelling_or_romanticising"
__FORMATS = len(get_args(Format))

# Signed: a positive threshold flags a rise, a negative one a fall.
THEME_SHARE_RISE = 0.15
MEAN_VALENCE_DROP = -0.5
NEGATIVE_SHARE_RISE = 0.15
NIGHT_SHARE_RISE = 0.15
FORMAT_ENTROPY_DROP = -0.15
# Shares are differences of fractions, so 0.35 - 0.20 must still count as +0.15.
TOLERANCE = 1e-9


class Composition(Frozen):
    """What one viewer was shown in one window. Shares are 0-1 and None when undefined
    (nothing shown, or nothing scored yet).

    `n_shown` counts every event in the window; theme, affect and format metrics use
    only the `n_scored` events whose clip has been analysed.
    """

    n_shown: int
    n_scored: int
    theme_share: dict[str, float | None]
    mean_valence: float | None
    mean_arousal: float | None
    negative_share: float | None
    hopeful_share: float | None
    format_entropy: float | None
    night_share: float | None
    median_dwell_s: float | None

    @property
    def metrics(self) -> dict[str, float | None]:
        """Every comparable number, keyed by criterion key or field name."""
        return self.theme_share | {
            "mean_valence": self.mean_valence, "mean_arousal": self.mean_arousal,
            "negative_share": self.negative_share, "hopeful_share": self.hopeful_share,
            "format_entropy": self.format_entropy, "night_share": self.night_share,
            "median_dwell_s": self.median_dwell_s}


@dataclass(frozen=True)
class Exposure:
    """A shown event joined with the analysis of its clip."""

    event: ViewEvent
    analysis: ClipAnalysis

    def dwells_on(self, criterion: Criterion) -> bool:
        scores = self.analysis.scores
        return scores.score_of(criterion) >= THEME_SCORE_MIN and scores.stance == DWELLING

    @property
    def is_negative(self) -> bool:
        return self.analysis.scores.valence <= NEGATIVE_VALENCE_MAX


def composition(events: Sequence[ViewEvent], analyses: Mapping[str, ClipAnalysis],
                window: Window) -> Composition:
    """Compose the events inside `window`, joined by video id with whatever `analyses` holds.

    Each event counts, so a clip shown twice weighs twice: the feed is the exposure.
    """
    shown = tuple(e for e in events if window.contains(e.seen_at))
    scored = tuple(Exposure(e, analyses[e.video_id]) for e in shown if e.video_id in analyses)
    return Composition(
        n_shown=len(shown), n_scored=len(scored),
        theme_share={c.key: __share([x.dwells_on(c) for x in scored]) for c in CRITERIA},
        mean_valence=__mean([x.analysis.scores.valence for x in scored]),
        mean_arousal=__mean([x.analysis.scores.arousal for x in scored]),
        negative_share=__share([x.is_negative for x in scored]),
        hopeful_share=__share([x.analysis.scores.hopeful for x in scored]),
        format_entropy=__entropy(Counter(x.analysis.package.format for x in scored)),
        night_share=__share([e.local_hour < NIGHT_END_HOUR for e in shown]),
        median_dwell_s=__median([e.dwell_s for e in shown if e.dwell_s is not None]))


def __share(flags: Sequence[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def __mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def __median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def __entropy(counts: Counter[str]) -> float | None:
    """Shannon entropy over all possible formats, scaled to 0 (one format) .. 1 (uniform)."""
    total = sum(counts.values())
    if total == 0:
        return None
    entropy = sum(n / total * math.log(total / n) for n in counts.values())
    return entropy / math.log(__FORMATS)


Metrics = Mapping[str, float | None]
ClusterLevel = Literal["stable", "watch", "flag"]
LEVELS: tuple[ClusterLevel, ...] = ("stable", "watch", "flag")


@dataclass(frozen=True)
class Rule:
    """Flag `metric` when its delta reaches the signed `threshold`."""

    metric: str
    threshold: float

    def crosses(self, delta: float | None) -> bool:
        if delta is None:
            return False
        return (delta >= self.threshold - TOLERANCE if self.threshold > 0
                else delta <= self.threshold + TOLERANCE)

    def flags(self, deltas: Metrics, control: Metrics | None) -> bool:
        """Crossed here, and not also in the control feed (then it is a platform-wide drift)."""
        in_control = control is not None and self.crosses(control[self.metric])
        return self.crosses(deltas[self.metric]) and not in_control


RULES: tuple[Rule, ...] = (*(Rule(c.key, THEME_SHARE_RISE) for c in CRITERIA),
                           Rule("mean_valence", MEAN_VALENCE_DROP),
                           Rule("negative_share", NEGATIVE_SHARE_RISE),
                           Rule("night_share", NIGHT_SHARE_RISE),
                           Rule("format_entropy", FORMAT_ENTROPY_DROP))


class ClusterStatus(Frozen):
    name: str
    level: ClusterLevel
    flagged: tuple[str, ...]


@dataclass(frozen=True)
class Cluster:
    """Related metrics read together: one flag is `watch`, two or more `flag`."""

    name: str
    metrics: tuple[str, ...]

    def status(self, flags: Sequence[str]) -> ClusterStatus:
        flagged = tuple(m for m in self.metrics if m in flags)
        return ClusterStatus(name=self.name, level=LEVELS[min(len(flagged), 2)], flagged=flagged)


CLUSTERS: tuple[Cluster, ...] = (
    Cluster("sleep_fatigue", ("a4_sleep", "a6_fatigue", "night_share")),
    Cluster("anhedonia_hopelessness", ("a1_depressed_mood", "a2_anhedonia", "format_entropy")),
    Cluster("worthlessness_guilt", ("a7_worthlessness_guilt",)),
)


class Shift(Frozen):
    """One viewer's composition now and in their own baseline window."""

    current: Composition
    baseline: Composition

    @property
    def deltas(self) -> dict[str, float | None]:
        """current - baseline per metric; None where either side is undefined."""
        before = self.baseline.metrics
        return {name: self.__difference(now, before[name])
                for name, now in self.current.metrics.items()}

    @staticmethod
    def __difference(now: float | None, before: float | None) -> float | None:
        return None if now is None or before is None else now - before


class Readout(Frozen):
    """Deltas against the baseline, flags that the control does not share, and clusters."""

    deltas: dict[str, float | None]
    control_deltas: dict[str, float | None] | None
    flags: tuple[str, ...]
    clusters: tuple[ClusterStatus, ...]


def readout(current: Composition, baseline: Composition, control: Shift | None) -> Readout:
    """Compare `current` with `baseline`; with a `control` shift over the same windows, a
    metric that crossed its threshold in the control too is not flagged."""
    deltas = Shift(current=current, baseline=baseline).deltas
    control_deltas = control.deltas if control is not None else None
    flags = tuple(rule.metric for rule in RULES if rule.flags(deltas, control_deltas))
    return Readout(deltas=deltas, control_deltas=control_deltas, flags=flags,
                   clusters=tuple(cluster.status(flags) for cluster in CLUSTERS))
