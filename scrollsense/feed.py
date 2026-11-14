"""Feed composition and the readout against a baseline and a control, as pure functions.

These numbers describe what a feed *showed*, not how anyone feels. Thresholds are
hackathon defaults, picked to be visible in a demo, not validated.
"""
import math
import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence, get_args

import numpy as np

from .domain import ClipAnalysis
from .schemas import CRITERIA, Criterion, Format, Frozen, Stance
from .views import EVER, ViewEvent, Window

NIGHT_END_HOUR = 5
NEGATIVE_VALENCE_MAX = 2
LOW_AROUSAL_MAX = 2
THEME_SCORE_MIN = 2
DWELLING = "dwelling_or_romanticising"
MAX_EVIDENCE = 24
MAX_TRAJECTORY = 12
__FORMATS = len(get_args(Format))

# Signed: a positive threshold flags a rise, a negative one a fall.
THEME_SHARE_RISE = 0.15
MEAN_VALENCE_DROP = -0.5
NEGATIVE_SHARE_RISE = 0.15
DWELL_SHARE_RISE = 0.20
NIGHT_SHARE_RISE = 0.15
FORMAT_ENTROPY_DROP = -0.15
SEMANTIC_DISPERSION_DROP = -0.12
# Shares are differences of fractions, so 0.35 - 0.20 must still count as +0.15.
TOLERANCE = 1e-9


class SafetyHit(Frozen):
    """A shown clip with any A9 (death/suicide) theme: route to a human, never to a score."""

    video_id: str
    seen_at: float
    evidence: str


class Composition(Frozen):
    """What one viewer was shown in one window. Shares are 0-1 and None when undefined
    (nothing shown, or nothing scored yet).

    `n_shown` counts every event in the window; theme, affect, format and semantic metrics
    use only the `n_scored` events whose clip has been analysed.
    """

    n_shown: int
    n_scored: int
    theme_share: dict[str, float | None]
    mean_valence: float | None
    mean_arousal: float | None
    negative_share: float | None
    low_arousal_negative_share: float | None = None
    dwell_negative_share: float | None = None
    hopeful_share: float | None
    format_entropy: float | None
    semantic_dispersion: float | None = None
    night_share: float | None
    median_dwell_s: float | None
    completion_rate: float | None = None
    loop_share: float | None = None
    safety_hits: tuple[SafetyHit, ...]

    @property
    def metrics(self) -> dict[str, float | None]:
        """Every comparable number, keyed by criterion key or field name."""
        return self.theme_share | {
            "mean_valence": self.mean_valence,
            "mean_arousal": self.mean_arousal,
            "negative_share": self.negative_share,
            "low_arousal_negative_share": self.low_arousal_negative_share,
            "dwell_negative_share": self.dwell_negative_share,
            "hopeful_share": self.hopeful_share,
            "format_entropy": self.format_entropy,
            "semantic_dispersion": self.semantic_dispersion,
            "night_share": self.night_share,
            "median_dwell_s": self.median_dwell_s,
            "completion_rate": self.completion_rate,
            "loop_share": self.loop_share,
        }


@dataclass(frozen=True)
class Exposure:
    """A shown event joined with the analysis of its clip."""

    event: ViewEvent
    analysis: ClipAnalysis

    def dwells_on(self, criterion: Criterion) -> bool:
        """Whether this clip has `criterion` as a central theme with a dwelling stance."""
        scores = self.analysis.scores
        return scores.score_of(criterion) >= THEME_SCORE_MIN and scores.stance == DWELLING

    @property
    def is_negative(self) -> bool:
        """Whether derived viewer valence sits on the negative side (1 or 2 of 5)."""
        return self.analysis.scores.valence <= NEGATIVE_VALENCE_MAX

    @property
    def is_low_arousal_negative(self) -> bool:
        """Russell's calm-negative quadrant (valence <= 2 and arousal <= 2)."""
        return self.is_negative and self.analysis.scores.arousal <= LOW_AROUSAL_MAX

    @property
    def safety_hit(self) -> SafetyHit | None:
        """Non-None whenever A9 death/suicide theme score is at least 1."""
        if self.analysis.scores.a9_death_suicide < 1:
            return None
        return SafetyHit(video_id=self.event.video_id, seen_at=self.event.seen_at,
                         evidence=self.analysis.scores.evidence)

    @property
    def triggered_metrics(self) -> tuple[str, ...]:
        """Metric keys exemplified by this exposure, used for evidence drill-down."""
        themes = [c.key for c in CRITERIA if self.dwells_on(c)]
        affect = self.__affect_metrics()
        diversity = self.__diversity_metrics()
        night = ["night_share"] if self.event.local_hour < NIGHT_END_HOUR else []
        return tuple([*themes, *affect, *diversity, *night])

    def __affect_metrics(self) -> list[str]:
        if not self.is_negative:
            return []
        low = ["low_arousal_negative_share"] if self.is_low_arousal_negative else []
        dwell = ["dwell_negative_share"] if (self.event.dwell_s or 0.0) > 0.0 else []
        return ["negative_share", "mean_valence", *low, *dwell]

    def __diversity_metrics(self) -> list[str]:
        if self.analysis.scores.stance != DWELLING and not self.is_negative:
            return []
        sem = ["semantic_dispersion"] if self.analysis.embedding.vector else []
        return [*sem, "format_entropy"]


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
        low_arousal_negative_share=__share([x.is_low_arousal_negative for x in scored]),
        dwell_negative_share=__dwell_negative_share(scored),
        hopeful_share=__share([x.analysis.scores.hopeful for x in scored]),
        format_entropy=__entropy(Counter(x.analysis.package.format for x in scored)),
        semantic_dispersion=__semantic_dispersion(scored),
        night_share=__share([e.local_hour < NIGHT_END_HOUR for e in shown]),
        median_dwell_s=__median([e.dwell_s for e in shown if e.dwell_s is not None]),
        completion_rate=__completion_rate(shown),
        loop_share=__loop_share(shown),
        safety_hits=tuple(hit for x in scored if (hit := x.safety_hit) is not None))


def __share(flags: Sequence[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def __mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def __median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def __dwell_negative_share(scored: Sequence[Exposure]) -> float | None:
    weighted = [(x.event.dwell_s, x.is_negative) for x in scored
                if x.event.dwell_s is not None and x.event.dwell_s > 0]
    total = sum(dwell for dwell, _ in weighted)
    if total <= 0:
        return None
    return sum(dwell for dwell, neg in weighted if neg) / total


def __completion_rate(shown: Sequence[ViewEvent]) -> float | None:
    ratios = [min(1.0, max(0.0, e.dwell_s / e.duration_s)) for e in shown
              if e.dwell_s is not None and e.duration_s is not None and e.duration_s > 0]
    return __median(ratios)


def __loop_share(shown: Sequence[ViewEvent]) -> float | None:
    return __share([e.loops >= 1 for e in shown if e.loops is not None])


def __entropy(counts: Counter[str]) -> float | None:
    """Shannon entropy over all possible formats, scaled to 0 (one format) .. 1 (uniform)."""
    total = sum(counts.values())
    if total == 0:
        return None
    entropy = sum(n / total * math.log(total / n) for n in counts.values())
    return entropy / math.log(__FORMATS)


def __unit_vectors(scored: Sequence[Exposure]) -> np.ndarray | None:
    raw = [x.analysis.embedding.vector for x in scored if x.analysis.embedding.vector]
    if len(raw) < 2:
        return None
    dim = min(len(v) for v in raw)
    matrix = np.array([v[:dim] for v in raw], dtype=float)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    keep = norms[:, 0] > 1e-12
    valid = matrix[keep] / norms[keep]
    return valid if len(valid) >= 2 else None


def __semantic_dispersion(scored: Sequence[Exposure]) -> float | None:
    """Sample-size-invariant cosine dispersion 1 - max(0, mean_off_diag_cos) in [0, 1]."""
    unit = __unit_vectors(scored)
    if unit is None:
        return None
    k = len(unit)
    mean_norm_sq = float(np.sum(unit.mean(axis=0) ** 2))
    mean_cos = (k * mean_norm_sq - 1.0) / (k - 1.0)
    return min(1.0, max(0.0, 1.0 - max(0.0, mean_cos)))


Metrics = Mapping[str, float | None]
ClusterLevel = Literal["stable", "watch", "flag"]
LEVELS: tuple[ClusterLevel, ...] = ("stable", "watch", "flag")


@dataclass(frozen=True)
class Rule:
    """Flag `metric` when its delta reaches the signed `threshold`."""

    metric: str
    threshold: float

    def crosses(self, delta: float | None) -> bool:
        """Whether `delta` meets or exceeds `threshold` in the signed direction."""
        if delta is None:
            return False
        return (delta >= self.threshold - TOLERANCE if self.threshold > 0
                else delta <= self.threshold + TOLERANCE)

    def flags(self, deltas: Metrics, control: Metrics | None) -> bool:
        """Crossed here, and not also in the control feed (then it is a platform-wide drift)."""
        in_control = control is not None and self.crosses(control[self.metric])
        return self.crosses(deltas[self.metric]) and not in_control


RULES: tuple[Rule, ...] = (
    *(Rule(c.key, THEME_SHARE_RISE) for c in CRITERIA),
    Rule("mean_valence", MEAN_VALENCE_DROP),
    Rule("negative_share", NEGATIVE_SHARE_RISE),
    Rule("low_arousal_negative_share", NEGATIVE_SHARE_RISE),
    Rule("dwell_negative_share", DWELL_SHARE_RISE),
    Rule("night_share", NIGHT_SHARE_RISE),
    Rule("format_entropy", FORMAT_ENTROPY_DROP),
    Rule("semantic_dispersion", SEMANTIC_DISPERSION_DROP),
)


class ClusterStatus(Frozen):
    """Triage summary for one clinical symptom/exposure cluster."""

    name: str
    level: ClusterLevel
    flagged: tuple[str, ...]


@dataclass(frozen=True)
class Cluster:
    """Related metrics read together: one flag is `watch`, two or more `flag`."""

    name: str
    metrics: tuple[str, ...]

    def status(self, flags: Sequence[str]) -> ClusterStatus:
        """Evaluate this cluster's level from the active metric `flags`."""
        flagged = tuple(m for m in self.metrics if m in flags)
        return ClusterStatus(name=self.name, level=LEVELS[min(len(flagged), 2)], flagged=flagged)


CLUSTERS: tuple[Cluster, ...] = (
    Cluster("sleep_fatigue", ("a4_sleep", "a6_fatigue", "night_share")),
    Cluster("anhedonia_hopelessness", ("a1_depressed_mood", "a2_anhedonia",
                                       "low_arousal_negative_share", "format_entropy",
                                       "semantic_dispersion")),
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
    safety_hits: tuple[SafetyHit, ...]


def readout(current: Composition, baseline: Composition, control: Shift | None) -> Readout:
    """Compare `current` with `baseline`; with a `control` shift over the same windows, a
    metric that crossed its threshold in the control too is not flagged."""
    deltas = Shift(current=current, baseline=baseline).deltas
    control_deltas = control.deltas if control is not None else None
    flags = tuple(rule.metric for rule in RULES if rule.flags(deltas, control_deltas))
    return Readout(deltas=deltas, control_deltas=control_deltas, flags=flags,
                   clusters=tuple(cluster.status(flags) for cluster in CLUSTERS),
                   safety_hits=current.safety_hits)


class EvidenceItem(Frozen):
    """One scored exposure with its quote and the readout metrics it contributed to."""

    video_id: str
    title: str
    seen_at: float
    local_hour: float
    dwell_s: float | None
    valence: int
    arousal: int
    stance: Stance
    load: int
    quote: str
    metrics: tuple[str, ...]


def evidence_items(events: Sequence[ViewEvent], analyses: Mapping[str, ClipAnalysis],
                   window: Window) -> tuple[EvidenceItem, ...]:
    """Salient scored exposures inside `window`, most clinically weighted first."""
    shown = (e for e in events if window.contains(e.seen_at) and e.video_id in analyses)
    items = [__to_evidence(Exposure(e, analyses[e.video_id])) for e in shown]
    notable = [item for item in items if item.metrics or item.load > 0]
    ranked = sorted(notable, key=__evidence_rank, reverse=True)
    return tuple(ranked[:MAX_EVIDENCE])


def __to_evidence(exposure: Exposure) -> EvidenceItem:
    s = exposure.analysis.scores
    e = exposure.event
    return EvidenceItem(video_id=e.video_id, title=exposure.analysis.package.title,
                        seen_at=e.seen_at, local_hour=round(e.local_hour, 4), dwell_s=e.dwell_s,
                        valence=s.valence, arousal=s.arousal, stance=s.stance,
                        load=s.theme_load, quote=s.evidence, metrics=exposure.triggered_metrics)


def __evidence_rank(item: EvidenceItem) -> tuple[int, int, float, float]:
    return (len(item.metrics), item.load, item.dwell_s or 0.0, item.seen_at)


class TrajectoryPoint(Frozen):
    """Summary of a rolling chronological slice of exposures for session/trend plotting."""

    at: float
    n_shown: int
    n_scored: int
    mean_valence: float | None
    mean_arousal: float | None
    negative_share: float | None
    low_arousal_negative_share: float | None
    semantic_dispersion: float | None
    night_share: float | None


def trajectory(events: Sequence[ViewEvent],
               analyses: Mapping[str, ClipAnalysis]) -> tuple[TrajectoryPoint, ...]:
    """Up to `MAX_TRAJECTORY` rolling exposure snapshots in chronological order."""
    ordered = sorted(events, key=lambda e: e.seen_at)
    if not ordered:
        return ()
    span = min(6, max(2, math.ceil(len(ordered) / 3)))
    ends = __sample_ends(len(ordered), MAX_TRAJECTORY)
    return tuple(__point_at(ordered[max(0, end - span):end], analyses) for end in ends)


def __sample_ends(total: int, cap: int) -> list[int]:
    if total <= cap:
        return list(range(1, total + 1))
    return sorted({max(1, round((i + 1) * total / cap)) for i in range(cap)})


def __point_at(slice_events: Sequence[ViewEvent],
               analyses: Mapping[str, ClipAnalysis]) -> TrajectoryPoint:
    comp = composition(slice_events, analyses, EVER)
    return TrajectoryPoint(at=slice_events[-1].seen_at, n_shown=comp.n_shown,
                           n_scored=comp.n_scored, mean_valence=comp.mean_valence,
                           mean_arousal=comp.mean_arousal, negative_share=comp.negative_share,
                           low_arousal_negative_share=comp.low_arousal_negative_share,
                           semantic_dispersion=comp.semantic_dispersion,
                           night_share=comp.night_share)
