"""Drift from one viewer's normal feed, as pure functions.

A viewer's *normal* is where their scrolled Shorts sit in affect and theme space during a
baseline: by default their first analysed Shorts, or a set frozen by hand (`BaselineMark`).
*Drift* is how far their most recent analysed Shorts have moved from there, in baseline
standard deviations, counting only moves in each feature's risk direction.

The numbers describe what a feed *showed*, not how anyone feels, and are not a diagnosis.
Thresholds and windows are placeholders, to be tuned on real data through `DriftConfig`.
"""
import math
import statistics
from dataclasses import dataclass
from operator import attrgetter
from typing import Callable, Literal, Mapping, Sequence

from pydantic import Field, model_validator

from ..domain import ClipAnalysis
from ..schemas import ClipScores, Frozen, Stance
from ..views import ViewEvent

Level = Literal["learning", "normal", "watch", "warning"]
BaselineSource = Literal["default", "marked"]
DWELLING: Stance = "dwelling_or_romanticising"

# Reasons name only moves big enough to matter, and only the few that matter most.
REASON_MIN_EFFECT = 0.5
MAX_REASONS = 3
MAX_EVIDENCE = 3
SAFETY_MIN_A9 = 1
# Scores are sums of floats, so a threshold of 0.8 must still match a score of 0.8.
TOLERANCE = 1e-9

ENV_VARS: dict[str, str] = {
    "baseline_n": "SCROLLSENSE_BASELINE_N",
    "min_baseline": "SCROLLSENSE_MIN_BASELINE",
    "window": "SCROLLSENSE_DRIFT_WINDOW",
    "watch": "SCROLLSENSE_DRIFT_WATCH",
    "warn": "SCROLLSENSE_DRIFT_WARN",
}


class DriftConfig(Frozen):
    """Windows (counted in analysed Shorts) and score thresholds.

    The default baseline is the first `baseline_n` analysed Shorts. No level is given until
    the baseline holds at least `min_baseline` Shorts and the recent window (the last
    `window` analysed Shorts after the baseline) at least `min_recent`, half of `window`.
    Raises ValueError unless min_baseline <= baseline_n and watch <= warn.
    """

    baseline_n: int = Field(default=20, ge=1)
    min_baseline: int = Field(default=8, ge=1)
    window: int = Field(default=10, ge=1)
    watch: float = Field(default=1.2, gt=0)  # tuned on simulated feeds of 50 real Shorts, see docs/drift-tuning.md
    warn: float = Field(default=1.5, gt=0)

    @model_validator(mode="after")
    def __consistent(self) -> "DriftConfig":
        if self.min_baseline > self.baseline_n:
            raise ValueError(f"min_baseline {self.min_baseline} > baseline_n {self.baseline_n}")
        if self.watch > self.warn:
            raise ValueError(f"watch threshold {self.watch} > warn threshold {self.warn}")
        return self

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "DriftConfig":
        """The defaults, overridden by each of `ENV_VARS` that is set and non-empty in `env`.
        Raises ValueError on a malformed or inconsistent value."""
        return cls.model_validate({field: env[name] for field, name in ENV_VARS.items()
                                   if env.get(name)})

    @property
    def min_recent(self) -> int:
        return math.ceil(self.window / 2)

    def level_of(self, score: float) -> Level:
        """normal, watch or warning; each threshold counts as reached when met exactly."""
        if score >= self.warn - TOLERANCE:
            return "warning"
        return "watch" if score >= self.watch - TOLERANCE else "normal"


@dataclass(frozen=True)
class Feature:
    """One axis of the drift space. `direction` is +1 when a rise is the risky move and -1
    when a fall is; `sd_floor` stops a near-uniform baseline from turning tiny moves into
    huge effects."""

    name: str
    label: str
    direction: int
    weight: float
    sd_floor: float
    extract: Callable[[ClipScores], float]

    def effect(self, baseline: "Stats", value: float) -> float:
        """How many (floored) baseline SDs `value` sits from the baseline mean, signed."""
        return (value - baseline.mean) / max(baseline.sd, self.sd_floor)

    def risk(self, effect: float) -> float:
        """`effect` in the risk direction, clipped at 0: moves the safe way never count."""
        return max(0.0, effect * self.direction)


VALENCE = Feature("valence", "valence", direction=-1, weight=1.0, sd_floor=0.5,
                  extract=lambda s: s.valence)
AROUSAL = Feature("arousal", "arousal", direction=-1, weight=0.5, sd_floor=0.5,
                  extract=lambda s: s.arousal)
NEGATIVE_AFFECT = Feature("negative_affect", "negative affect", direction=1, weight=1.0,
                          sd_floor=0.5, extract=lambda s: s.negative_affect)
THEME_LOAD = Feature("theme_load", "theme load", direction=1, weight=1.0, sd_floor=1.5,
                     extract=lambda s: s.theme_load)
DWELLING_STANCE = Feature("dwelling", "dwelling stance", direction=1, weight=1.0, sd_floor=0.15,
                          extract=lambda s: float(s.stance == DWELLING))
FEATURES: tuple[Feature, ...] = (VALENCE, AROUSAL, NEGATIVE_AFFECT, THEME_LOAD, DWELLING_STANCE)


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

    def value(self, feature: Feature) -> float:
        return float(feature.extract(self.scores))


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


class Stats(Frozen):
    """Mean and population SD of one feature over a group of Shorts."""

    mean: float
    sd: float

    @classmethod
    def of(cls, values: Sequence[float]) -> "Stats":
        """Raises statistics.StatisticsError if `values` is empty."""
        return cls(mean=statistics.fmean(values), sd=statistics.pstdev(values))


class AffectPoint(Frozen):
    valence: float
    arousal: float


class Summary(Frozen):
    """Where a group of Shorts sits on the affect map; None fields when the group is empty."""

    n: int
    centroid: AffectPoint | None
    sd: AffectPoint | None
    first_seen_at: float | None
    last_seen_at: float | None


class BaselineSummary(Summary):
    """`target` is the baseline size the source aims for (baseline_n, or the marked size)."""

    source: BaselineSource
    target: int


@dataclass(frozen=True)
class Group:
    """Analysed Shorts in seen order."""

    members: tuple[Observation, ...]

    def __len__(self) -> int:
        return len(self.members)

    def stats(self, feature: Feature) -> Stats:
        """Raises statistics.StatisticsError if the group is empty."""
        return Stats.of([m.value(feature) for m in self.members])

    def last(self, n: int) -> "Group":
        return Group(self.members[-n:])

    def summary(self) -> Summary:
        if not self.members:
            return Summary(n=0, centroid=None, sd=None, first_seen_at=None, last_seen_at=None)
        valence, arousal = self.stats(VALENCE), self.stats(AROUSAL)
        return Summary(n=len(self.members),
                       centroid=AffectPoint(valence=valence.mean, arousal=arousal.mean),
                       sd=AffectPoint(valence=valence.sd, arousal=arousal.sd),
                       first_seen_at=self.members[0].seen_at, last_seen_at=self.members[-1].seen_at)


class FeatureRow(Frozen):
    """One feature compared between the baseline and a recent group."""

    name: str
    label: str
    direction: int
    weight: float
    sd_floor: float
    baseline_mean: float
    baseline_sd: float
    recent_mean: float
    effect: float
    risk_effect: float

    @classmethod
    def compare(cls, feature: Feature, baseline: Group, recent: Group) -> "FeatureRow":
        """Raises statistics.StatisticsError if either group is empty."""
        before, now = baseline.stats(feature), recent.stats(feature).mean
        effect = feature.effect(before, now)
        return cls(name=feature.name, label=feature.label, direction=feature.direction,
                   weight=feature.weight, sd_floor=feature.sd_floor, baseline_mean=before.mean,
                   baseline_sd=before.sd, recent_mean=now, effect=effect,
                   risk_effect=feature.risk(effect))

    @property
    def weighted_risk(self) -> float:
        return self.weight * self.risk_effect

    @property
    def reason(self) -> str:
        side = "above" if self.effect > 0 else "below"
        return (f"{self.label} {abs(self.effect):.1f} SD {side} normal "
                f"({self.recent_mean:.1f} vs {self.baseline_mean:.1f})")


def compare(baseline: Group, recent: Group) -> tuple[FeatureRow, ...]:
    """Every feature compared; empty when either group is."""
    if not (baseline and recent):
        return ()
    return tuple(FeatureRow.compare(f, baseline, recent) for f in FEATURES)


def drift_score(rows: Sequence[FeatureRow]) -> float | None:
    """Weighted mean of the risk effects, or None without rows."""
    if not rows:
        return None
    return sum(r.weighted_risk for r in rows) / sum(r.weight for r in rows)


def reasons(rows: Sequence[FeatureRow]) -> tuple[str, ...]:
    """Lines for the features that push the score most, largest first."""
    strong = [r for r in rows if r.risk_effect >= REASON_MIN_EFFECT - TOLERANCE]
    ranked = sorted(strong, key=attrgetter("weighted_risk"), reverse=True)
    return tuple(r.reason for r in ranked[:MAX_REASONS])


class EvidenceItem(Frozen):
    """A recent Short and its own drift score against the baseline."""

    video_id: str
    title: str
    seen_at: float
    valence: int
    theme_load: int
    stance: Stance
    risk: float

    @classmethod
    def of(cls, shown: Observation, risk: float) -> "EvidenceItem":
        s = shown.scores
        return cls(video_id=shown.video_id, title=shown.title, seen_at=shown.seen_at,
                   valence=s.valence, theme_load=s.theme_load, stance=s.stance, risk=risk)


def evidence(baseline: Group, recent: Group) -> tuple[EvidenceItem, ...]:
    """Up to MAX_EVIDENCE recent Shorts with the highest positive individual risk."""
    items = [EvidenceItem.of(o, drift_score(compare(baseline, Group((o,)))) or 0.0)
             for o in recent.members]
    ranked = sorted((i for i in items if i.risk > 0), key=attrgetter("risk"), reverse=True)
    return tuple(ranked[:MAX_EVIDENCE])


class SafetyItem(Frozen):
    """A recent Short with an A9 (death/suicide) theme: route to a human, whatever the level."""

    video_id: str
    title: str
    seen_at: float
    a9: int
    evidence: str

    @classmethod
    def of(cls, shown: Observation) -> "SafetyItem":
        return cls(video_id=shown.video_id, title=shown.title, seen_at=shown.seen_at,
                   a9=shown.scores.a9_death_suicide, evidence=shown.scores.evidence)


def safety(recent: Group) -> tuple[SafetyItem, ...]:
    return tuple(SafetyItem.of(o) for o in recent.members
                 if o.scores.a9_death_suicide >= SAFETY_MIN_A9)


class TimelinePoint(Frozen):
    """The drift score of the window ending at one analysed Short after the baseline."""

    video_id: str
    seen_at: float
    score: float
    level: Level


@dataclass(frozen=True)
class Split:
    """The baseline and the analysed Shorts seen after it, both in seen order."""

    baseline: Group
    after: Group
    source: BaselineSource
    target: int

    @classmethod
    def first(cls, analysed: Sequence[Observation], n: int) -> "Split":
        """The default: the first `n` analysed Shorts are the baseline."""
        return cls(baseline=Group(tuple(analysed[:n])), after=Group(tuple(analysed[n:])),
                   source="default", target=n)

    def summary(self) -> BaselineSummary:
        return BaselineSummary.model_validate(
            self.baseline.summary().model_dump() | {"source": self.source, "target": self.target})


class BaselineMark(Frozen):
    """A baseline frozen by hand: exactly the Shorts in `video_ids`, marked at `marked_at`.

    Stored by video id rather than a time bound, so a Short whose analysis finishes after
    marking cannot slip into (or shift) the baseline.
    """

    video_ids: tuple[str, ...]
    marked_at: float

    def split(self, analysed: Sequence[Observation]) -> Split:
        """Marked Shorts that are still analysed form the baseline; the rest seen after the
        last of them are `after`. Unknown ids are ignored, so an erased log gives an empty
        baseline."""
        chosen = set(self.video_ids)
        baseline = tuple(o for o in analysed if o.video_id in chosen)
        end = baseline[-1].seen_at if baseline else math.inf
        after = tuple(o for o in analysed if o.seen_at > end and o.video_id not in chosen)
        return Split(baseline=Group(baseline), after=Group(after), source="marked",
                     target=len(self.video_ids))


class Verdict(Frozen):
    level: Level
    note: str


LEVEL_NOTES: dict[Level, str] = {
    "normal": "Close to this person's normal feed",
    "watch": "Drifting from this person's normal feed",
    "warning": "Clearly drifted from this person's normal feed",
}


class DriftReport(Frozen):
    """Drift of one viewer's recent Shorts from their normal feed. Not a diagnosis.

    `score` is None until both baseline and recent window hold a Short; `level` stays
    `learning` until they reach the configured minimums. `safety` lists A9 Shorts among the
    last `window` analysed ones, whatever the level. `timeline` scores the window ending at
    each analysed Short after the baseline (empty until the baseline is big enough).
    """

    viewer: str
    level: Level
    score: float | None
    note: str
    config: DriftConfig
    baseline: BaselineSummary
    recent: Summary
    pending: int
    features: tuple[FeatureRow, ...]
    reasons: tuple[str, ...]
    evidence: tuple[EvidenceItem, ...]
    safety: tuple[SafetyItem, ...]
    timeline: tuple[TimelinePoint, ...]


class DriftDetector:
    """Judges drift with one `DriftConfig`. Holds no state: every method is pure."""

    def __init__(self, config: DriftConfig) -> None:
        self.__config = config

    @property
    def config(self) -> DriftConfig:
        return self.__config

    def report(self, viewer: str, observed: Observed, mark: BaselineMark | None) -> DriftReport:
        """The drift report for `viewer`, against `mark` if given, else the default baseline."""
        parts = mark.split(observed.analysed) if mark else Split.first(observed.analysed,
                                                                       self.__config.baseline_n)
        recent = parts.after.last(self.__config.window)
        rows = compare(parts.baseline, recent)
        score = drift_score(rows)
        verdict = self.__verdict(parts, recent, score)
        return DriftReport(
            viewer=viewer, level=verdict.level, score=score, note=verdict.note,
            config=self.__config, baseline=parts.summary(), recent=recent.summary(),
            pending=observed.pending, features=rows, reasons=reasons(rows),
            evidence=evidence(parts.baseline, recent),
            safety=safety(Group(observed.analysed).last(self.__config.window)),
            timeline=self.__timeline(parts))

    def mark(self, observed: Observed, size: int | None, now: float) -> BaselineMark:
        """The most recent `size` (default `baseline_n`) analysed Shorts as a baseline marked
        at `now`. Raises ValueError if `size` or the number analysed is below `min_baseline`."""
        wanted = size or self.__config.baseline_n
        minimum = self.__config.min_baseline
        if wanted < minimum or len(observed.analysed) < minimum:
            raise ValueError(f"A baseline needs at least {minimum} analysed Shorts "
                             f"(asked for {wanted}, {len(observed.analysed)} analysed)")
        chosen = observed.analysed[-wanted:]
        return BaselineMark(video_ids=tuple(o.video_id for o in chosen), marked_at=now)

    def __required(self, parts: Split) -> int:
        return max(parts.target, self.__config.min_baseline)

    def __verdict(self, parts: Split, recent: Group, score: float | None) -> Verdict:
        required, minimum = self.__required(parts), self.__config.min_recent
        if len(parts.baseline) < required:
            return Verdict(level="learning",
                           note=f"Learning normal: {len(parts.baseline)}/{required} Shorts")
        if score is None or len(recent) < minimum:
            return Verdict(level="learning", note=f"Normal learned from {len(parts.baseline)} "
                           f"Shorts; collecting recent ones: {len(recent)}/{minimum}")
        level = self.__config.level_of(score)
        return Verdict(level=level, note=LEVEL_NOTES[level])

    def __timeline(self, parts: Split) -> tuple[TimelinePoint, ...]:
        if len(parts.baseline) < self.__required(parts):
            return ()
        return tuple(self.__point(parts.baseline, Group(parts.after.members[:end]))
                     for end in range(1, len(parts.after) + 1))

    def __point(self, baseline: Group, upto: Group) -> TimelinePoint:
        window = upto.last(self.__config.window)
        score = drift_score(compare(baseline, window)) or 0.0
        enough = len(window) >= self.__config.min_recent
        newest = window.members[-1]
        return TimelinePoint(video_id=newest.video_id, seen_at=newest.seen_at, score=score,
                             level=self.__config.level_of(score) if enough else "learning")
