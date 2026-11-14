"""Drift of one viewer's recent Shorts, calibrated against research norms, as pure functions.

Two global yardsticks, no personal baseline and no learning phase beyond a half-full window:

- *Affect* (`affect.py`): the recent window's mean valence and arousal against published
  word-affect norms (Warriner et al. 2013) mapped onto the 1-5 scales, in norm SDs. It deviates
  when the drift points into the bottom-left quadrant (lower valence and arousal) and is longer
  than 1 SD: within 1 SD is the normal range by definition (`DriftConfig`).
- *Clinical* (`clinical.py`): a PHQ-9-style score of the depressive themes the window showed,
  with the PHQ-9's own cutoffs and diagnostic algorithm. Not tuned.

The overall level is the more severe of the two. The numbers describe what a feed *showed*,
not how anyone feels, and are not a diagnosis.
"""
import math
from dataclasses import dataclass
from operator import attrgetter
from typing import Mapping

from pydantic import Field, model_validator

from ..schemas import CRITERIA, Frozen
from .affect import AffectComparison, AffectNorm, FeatureRow, affect_risk
from .clinical import CENTRAL_THEME, ClinicalExposure
from .levels import TOLERANCE, Level, most_severe
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

    `window` defaults to 10, for a quick demo (14 matches one Short per PHQ-9 day; PHQ-9
    shares are fractions, so either works). No level is given until the window holds
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
    """Both yardsticks applied to one window of Shorts; levels stay `learning` while the
    window holds fewer than `min_recent`."""

    window: Group
    affect: AffectComparison
    clinical: ClinicalExposure | None
    affect_level: Level
    clinical_level: Level

    @property
    def level(self) -> Level:
        return most_severe((self.affect_level, self.clinical_level))

    @property
    def score(self) -> float | None:
        return self.affect.score


class TimelinePoint(Frozen):
    """The judgement of the window ending at one analysed Short: affect `score`, PHQ-9-style
    `exposure` (0-27) and the overall `level`."""

    video_id: str
    seen_at: float
    score: float
    exposure: int
    level: Level


class EvidenceItem(Frozen):
    """A recent Short: its central criteria (theme >= 2) and its own affect score vs the norm."""

    video_id: str
    title: str
    seen_at: float
    valence: int
    arousal: int
    central: tuple[str, ...]
    risk: float

    @classmethod
    def of(cls, shown: Observation, norm: AffectNorm) -> "EvidenceItem":
        s = shown.scores
        central = tuple(c.code for c in CRITERIA if s.score_of(c) >= CENTRAL_THEME)
        return cls(video_id=shown.video_id, title=shown.title, seen_at=shown.seen_at,
                   valence=s.valence, arousal=s.arousal, central=central,
                   risk=affect_risk(norm, Group((shown,))))

    @property
    def weight(self) -> tuple[int, float]:
        return len(self.central), self.risk


def evidence(norm: AffectNorm, recent: Group) -> tuple[EvidenceItem, ...]:
    """Up to MAX_EVIDENCE recent Shorts contributing most: central criteria first, then affect."""
    items = (EvidenceItem.of(o, norm) for o in recent.members)
    ranked = sorted((i for i in items if i.central or i.risk > 0), key=attrgetter("weight"),
                    reverse=True)
    return tuple(ranked[:MAX_EVIDENCE])


LEVEL_NOTES: dict[Level, str] = {
    "normal": "Within 1 SD of typical affect and below the PHQ-9-style cutoffs",
    "watch": "Leaning towards depressive content",
    "warning": "Heavy with depressive content",
}


class DriftReport(Frozen):
    """The recent Shorts of one viewer against global research norms. Not a diagnosis.

    `score` (affect) is None and `clinical` None until the window holds a Short; levels stay
    `learning` until it holds `config.min_recent`. `timeline` judges the window ending at
    each analysed Short, oldest first.
    """

    viewer: str
    level: Level
    note: str
    config: DriftConfig
    affect_baseline: AffectNorm
    recent: Summary
    pending: int
    score: float | None
    affect_level: Level
    features: tuple[FeatureRow, ...]
    clinical: ClinicalExposure | None
    clinical_level: Level
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
            score=now.score, affect_level=now.affect_level, features=now.affect.rows,
            clinical=now.clinical, clinical_level=now.clinical_level, reasons=self.__reasons(now),
            evidence=evidence(self.__norm, now.window), timeline=self.__timeline(analysed))

    def judge(self, window: Group) -> Judgement:
        """Both yardsticks over `window` (already cut to at most `config.window` Shorts)."""
        affect = AffectComparison.of(self.__norm, window)
        clinical = ClinicalExposure.of([m.scores for m in window.members]) if window else None
        if len(window) < self.__config.min_recent or clinical is None:
            return Judgement(window, affect, clinical, "learning", "learning")
        return Judgement(window, affect, clinical, self.__config.level_of(affect.score or 0.0),
                         clinical.level)

    def __note(self, now: Judgement) -> str:
        if now.level == "learning":
            return f"Collecting recent Shorts: {len(now.window)}/{self.__config.min_recent} analysed"
        return LEVEL_NOTES[now.level]

    @staticmethod
    def __reasons(now: Judgement) -> tuple[str, ...]:
        """The PHQ-9-style line, then the affect lines, each only when its level is raised."""
        clinical = now.clinical if now.clinical_level in FLAGGED else None
        affect = now.affect.reasons() if now.affect_level in FLAGGED else ()
        return ((clinical.reason(),) if clinical else ()) + affect

    def __timeline(self, analysed: Group) -> tuple[TimelinePoint, ...]:
        return tuple(self.__point(analysed.upto(end)) for end in range(1, len(analysed) + 1))

    def __point(self, upto: Group) -> TimelinePoint:
        judged = self.judge(upto.last(self.__config.window))
        newest = upto.members[-1]
        exposure = judged.clinical.total if judged.clinical else 0
        return TimelinePoint(video_id=newest.video_id, seen_at=newest.seen_at,
                             score=judged.score or 0.0, exposure=exposure, level=judged.level)
