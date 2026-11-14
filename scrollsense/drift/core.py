"""Drift of one viewer's recent Shorts against a global affect norm, as pure functions.

The recent window's mean valence and arousal are compared with published word-affect norms
(Warriner et al. 2013) mapped onto the 1-5 scales, in norm SDs (`affect.py`). The window
deviates when its drift points into the bottom-left quadrant (lower valence and arousal) and
is longer than 1 SD: within 1 SD is the normal range by definition. There is no personal
baseline and no learning phase beyond a half-full window.

The numbers describe what a feed *showed*, not how anyone feels, and are not a diagnosis.
"""
import math
from dataclasses import dataclass
from operator import attrgetter
from typing import Mapping

from pydantic import Field, model_validator

from ..schemas import Frozen
from .affect import AffectComparison, AffectNorm, FeatureRow, affect_risk
from .levels import TOLERANCE, Level
from .observe import Group, Observation, Observed, Summary

MAX_EVIDENCE = 3
FLAGGED: frozenset[Level] = frozenset({"watch", "warning"})

ENV_VARS: dict[str, str] = {
    "window": "SCROLLSENSE_DRIFT_WINDOW",
    "watch": "SCROLLSENSE_DRIFT_WATCH",
    "warn": "SCROLLSENSE_DRIFT_WARN",
}


class DriftConfig(Frozen):
    """The recent window (counted in analysed Shorts) and the affect-score thresholds, in norm
    SDs of drift into the bottom-left quadrant.

    `window` defaults to 10, for a quick demo. No level is given until the window holds
    at least `min_recent` Shorts, half of `window`. Both thresholds default to 1 SD, so affect
    goes straight from normal to warning; neither may be below 1 SD, the edge of the normal
    range. A higher `warn` brings back an affect `watch` band. Raises ValueError unless
    watch <= warn.
    """

    window: int = Field(default=10, ge=1)
    watch: float = Field(default=1.0, ge=1.0)
    warn: float = Field(default=1.0, ge=1.0)

    @model_validator(mode="after")
    def __consistent(self) -> "DriftConfig":
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
        """normal, watch or warning for an affect score; a score must pass a threshold, so
        exactly 1 SD is still normal."""
        if score > self.warn + TOLERANCE:
            return "warning"
        return "watch" if score > self.watch + TOLERANCE else "normal"


@dataclass(frozen=True)
class Judgement:
    """The affect yardstick applied to one window of Shorts; `level` stays `learning` while
    the window holds fewer than `min_recent`."""

    window: Group
    affect: AffectComparison
    level: Level

    @property
    def score(self) -> float | None:
        return self.affect.score


class TimelinePoint(Frozen):
    """The judgement of the window ending at one analysed Short: affect `score` and `level`."""

    video_id: str
    seen_at: float
    score: float
    level: Level


class EvidenceItem(Frozen):
    """A recent Short and its own affect score against the norm."""

    video_id: str
    title: str
    seen_at: float
    valence: int
    arousal: int
    risk: float

    @classmethod
    def of(cls, shown: Observation, norm: AffectNorm) -> "EvidenceItem":
        s = shown.scores
        return cls(video_id=shown.video_id, title=shown.title, seen_at=shown.seen_at,
                   valence=s.valence, arousal=s.arousal, risk=affect_risk(norm, Group((shown,))))


def evidence(norm: AffectNorm, recent: Group) -> tuple[EvidenceItem, ...]:
    """Up to MAX_EVIDENCE recent Shorts drifting furthest into the bottom-left quadrant."""
    items = (EvidenceItem.of(o, norm) for o in recent.members)
    ranked = sorted((i for i in items if i.risk > 0), key=attrgetter("risk"), reverse=True)
    return tuple(ranked[:MAX_EVIDENCE])


LEVEL_NOTES: dict[Level, str] = {
    "normal": "Within the normal range",
    "watch": "Drifting towards low mood",
    "warning": "Low-mood drift",
}


class DriftReport(Frozen):
    """The recent Shorts of one viewer against the global affect norm. Not a diagnosis.

    `score` is None until the window holds a Short; `level` stays `learning` until it holds
    `config.min_recent`. `timeline` judges the window ending at each analysed Short, oldest
    first.
    """

    viewer: str
    level: Level
    note: str
    config: DriftConfig
    affect_baseline: AffectNorm
    recent: Summary
    pending: int
    score: float | None
    features: tuple[FeatureRow, ...]
    reasons: tuple[str, ...]
    evidence: tuple[EvidenceItem, ...]
    timeline: tuple[TimelinePoint, ...]


class DriftDetector:
    """Judges drift with one `DriftConfig` against one `AffectNorm`. Holds no state: every
    method is pure."""

    def __init__(self, config: DriftConfig, norm: AffectNorm) -> None:
        self.__config = config
        self.__norm = norm

    @property
    def config(self) -> DriftConfig:
        return self.__config

    def report(self, viewer: str, observed: Observed) -> DriftReport:
        """The drift report for `viewer` over their last `config.window` analysed Shorts."""
        analysed = Group(observed.analysed)
        now = self.judge(analysed.last(self.__config.window))
        return DriftReport(
            viewer=viewer, level=now.level, note=self.__note(now), config=self.__config,
            affect_baseline=self.__norm, recent=now.window.summary(), pending=observed.pending,
            score=now.score, features=now.affect.rows,
            reasons=now.affect.reasons() if now.level in FLAGGED else (),
            evidence=evidence(self.__norm, now.window), timeline=self.__timeline(analysed))

    def judge(self, window: Group) -> Judgement:
        """The affect yardstick over `window` (already cut to at most `config.window` Shorts)."""
        affect = AffectComparison.of(self.__norm, window)
        if len(window) < self.__config.min_recent:
            return Judgement(window, affect, "learning")
        return Judgement(window, affect, self.__config.level_of(affect.score or 0.0))

    def __note(self, now: Judgement) -> str:
        if now.level == "learning":
            return f"Collecting recent Shorts: {len(now.window)}/{self.__config.min_recent} analysed"
        return LEVEL_NOTES[now.level]

    def __timeline(self, analysed: Group) -> tuple[TimelinePoint, ...]:
        return tuple(self.__point(analysed.upto(end)) for end in range(1, len(analysed) + 1))

    def __point(self, upto: Group) -> TimelinePoint:
        judged = self.judge(upto.last(self.__config.window))
        newest = upto.members[-1]
        return TimelinePoint(video_id=newest.video_id, seen_at=newest.seen_at,
                             score=judged.score or 0.0, level=judged.level)
