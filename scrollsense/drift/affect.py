"""Affect of recent Shorts against a global norm from published word-affect ratings.

The norm (`AffectNorm`) is where everyday English words sit on valence and arousal, mapped
onto the scoring model's 1-5 scales (see `scrollsense/reference/affect_norms.json`). Effects
are in norm SDs. The drift is the vector of both effects from the norm centre: it counts only
when it points into the bottom-left quadrant (valence and arousal both at or below the norm),
and then by its length, so anything within 1 SD stays in the normal range. The mapping from
word ratings to video scores is nominal, not calibrated.
"""
import math
from dataclasses import dataclass
from typing import Callable

from ..schemas import ClipScores, Frozen
from .observe import AffectPoint, Group


class AffectNorm(Frozen):
    """The global affect baseline: centre and SD on the 1-5 scales, and where they come from.
    `cite` is a short citation for reasons, e.g. "Warriner 2013"."""

    source: str
    cite: str
    centre: AffectPoint
    sd: AffectPoint


@dataclass(frozen=True)
class Feature:
    """One affect axis. `direction` is -1 when a fall is the risky move. `name` is the
    AffectPoint field."""

    name: str
    direction: int
    extract: Callable[[ClipScores], float]

    def centre(self, norm: AffectNorm) -> float:
        return float(getattr(norm.centre, self.name))

    def spread(self, norm: AffectNorm) -> float:
        """The norm SD."""
        return float(getattr(norm.sd, self.name))

    def effect(self, norm: AffectNorm, value: float) -> float:
        """How many norm SDs `value` sits from the norm centre, signed."""
        return (value - self.centre(norm)) / self.spread(norm)

    def risk(self, effect: float) -> float:
        """`effect` in the risk direction, clipped at 0: moves the safe way never count."""
        return max(0.0, effect * self.direction)


VALENCE = Feature("valence", direction=-1, extract=lambda s: s.valence)
AROUSAL = Feature("arousal", direction=-1, extract=lambda s: s.arousal)
FEATURES: tuple[Feature, ...] = (VALENCE, AROUSAL)


class FeatureRow(Frozen):
    """One feature of a group of Shorts compared with the norm. `norm_sd` is the SD the
    effect is measured in."""

    name: str
    direction: int
    norm_mean: float
    norm_sd: float
    recent_mean: float
    effect: float
    risk_effect: float

    @classmethod
    def compare(cls, feature: Feature, norm: AffectNorm, group: Group) -> "FeatureRow":
        """Raises statistics.StatisticsError if `group` is empty."""
        now = group.mean(feature.extract)
        effect = feature.effect(norm, now)
        return cls(name=feature.name, direction=feature.direction,
                   norm_mean=feature.centre(norm), norm_sd=feature.spread(norm), recent_mean=now,
                   effect=effect, risk_effect=feature.risk(effect))

    @property
    def risky(self) -> bool:
        """At the norm or past it in the risk direction."""
        return self.effect * self.direction >= 0

    def part(self) -> str:
        return f"{self.name} {self.recent_mean:.1f} vs {self.norm_mean:.2f}"


@dataclass(frozen=True)
class AffectComparison:
    """Every feature of one group compared with the norm; no rows when the group is empty."""

    norm: AffectNorm
    rows: tuple[FeatureRow, ...]

    @classmethod
    def of(cls, norm: AffectNorm, group: Group) -> "AffectComparison":
        rows = tuple(FeatureRow.compare(f, norm, group) for f in FEATURES) if group else ()
        return cls(norm=norm, rows=rows)

    @property
    def distance(self) -> float | None:
        """Length of the drift vector in norm SDs, whatever its direction; None without rows."""
        return math.hypot(*(r.effect for r in self.rows)) if self.rows else None

    @property
    def score(self) -> float | None:
        """The drift length when it points into the risk quadrant, else 0.0; None without rows."""
        if self.distance is None:
            return None
        return self.distance if all(r.risky for r in self.rows) else 0.0

    def reasons(self) -> tuple[str, ...]:
        """One line on the drift when it points into the risk quadrant, else none."""
        if not self.score:
            return ()
        parts = ", ".join(r.part() for r in self.rows)
        return (f"valence and arousal {self.score:.1f} SD from the norm towards the bottom left "
                f"({parts}, {self.norm.cite})",)


def affect_risk(norm: AffectNorm, group: Group) -> float:
    """The affect score of `group` against `norm`, 0.0 when the group is empty."""
    return AffectComparison.of(norm, group).score or 0.0
