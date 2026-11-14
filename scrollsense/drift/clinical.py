"""A PHQ-9-style score of the *content* a feed showed, as pure functions.

The PHQ-9 (Kroenke, Spitzer & Williams 2001, J Gen Intern Med 16:606-613) scores each of the
nine DSM criteria for a major depressive episode 0 "not at all" .. 3 "nearly every day" over
two weeks; totals of 5, 10, 15 and 20 mark mild, moderate, moderately severe and severe
depression, and a total >= 10 had 88% sensitivity and 88% specificity for major depression.

Here a recent window of analysed Shorts stands in for the two weeks and each Short for a day:
a criterion is present in a Short when its theme is central (score >= 2), and its share of
Shorts maps onto the PHQ frequency wording. This measures content exposure, not the
person's symptoms; it is a screening-style signal about a feed, never a diagnosis.

Deviation from the PHQ-9: some versions count the suicide item (A9) at "several days" in the
diagnostic algorithm; A9 alerts were removed from this app, so A9 counts like every item.
"""
from fractions import Fraction
from typing import Literal, Sequence

from ..schemas import CRITERIA, ClipScores, Criterion, Frozen
from .levels import Level

# A theme counts as present in a Short only when central (2) or intense (3); 1 = mentioned.
CENTRAL_THEME = 2
PHQ_DAYS = 14
# Shares of the window's Shorts, named by the PHQ-9 answer they reach.
SEVERAL_DAYS_FROM = Fraction(2, PHQ_DAYS)
MORE_THAN_HALF_THE_DAYS_ABOVE = Fraction(1, 2)   # strictly more than half: 7 of 14 is not
NEARLY_EVERY_DAY_FROM = Fraction(12, PHQ_DAYS)
FREQUENCY_LABELS: tuple[str, ...] = ("not at all", "several days", "more than half the days",
                                     "nearly every day")
# An item at "more than half the days" or more counts towards the diagnostic algorithm.
ALGORITHM_ITEM_SCORE = 2
CORE_CODES = frozenset({"A1", "A2"})   # depressed mood or anhedonia must be among them
MAJOR_MIN_ITEMS = 5
OTHER_MIN_ITEMS = 2
MAX_SCORE = 27
# Kroenke 2001 cutoffs; >= 10 is the validated one (sensitivity 88%, specificity 88%).
MILD_FROM = 5
MODERATE_FROM = 10
MAX_REASON_ITEMS = 3

Band = Literal["minimal", "mild", "moderate", "moderately severe", "severe"]
BANDS: tuple[tuple[int, Band], ...] = ((20, "severe"), (15, "moderately severe"),
                                        (MODERATE_FROM, "moderate"), (MILD_FROM, "mild"),
                                        (0, "minimal"))
Pattern = Literal["major", "other", "none"]
REFERENCE = ("PHQ-9 (Kroenke, Spitzer & Williams 2001, J Gen Intern Med 16:606-613) applied to "
             "content exposure, not the person's symptoms; a screening-style signal, not a "
             "diagnosis")


def item_score(share: Fraction) -> int:
    """The PHQ-9 item score (0-3) for a criterion present in `share` of the window's Shorts."""
    if share >= NEARLY_EVERY_DAY_FROM:
        return 3
    if share > MORE_THAN_HALF_THE_DAYS_ABOVE:
        return 2
    return 1 if share >= SEVERAL_DAYS_FROM else 0


def band_of(total: int) -> Band:
    """Kroenke 2001 severity band of a 0-27 total."""
    return next(band for floor, band in BANDS if total >= floor)


class ClinicalItem(Frozen):
    """One criterion over the window: `present` of the window's Shorts had it as a central theme."""

    code: str
    label: str
    present: int
    share: float
    score: int
    frequency_label: str

    @classmethod
    def of(cls, criterion: Criterion, window: Sequence[ClipScores]) -> "ClinicalItem":
        """Raises ZeroDivisionError if `window` is empty."""
        present = sum(s.score_of(criterion) >= CENTRAL_THEME for s in window)
        share = Fraction(present, len(window))
        score = item_score(share)
        return cls(code=criterion.code, label=criterion.label, present=present,
                   share=float(share), score=score, frequency_label=FREQUENCY_LABELS[score])


def pattern_of(items: Sequence[ClinicalItem]) -> Pattern:
    """The PHQ-9 diagnostic algorithm: "major" with 5+ items at "more than half the days" or
    more, "other" with 2-4; either needs depressed mood (A1) or anhedonia (A2) among them."""
    frequent = {i.code for i in items if i.score >= ALGORITHM_ITEM_SCORE}
    if not frequent & CORE_CODES:
        return "none"
    if len(frequent) >= MAJOR_MIN_ITEMS:
        return "major"
    return "other" if len(frequent) >= OTHER_MIN_ITEMS else "none"


class ClinicalExposure(Frozen):
    """The PHQ-9-style content exposure of one window of Shorts (`window_n` of them)."""

    window_n: int
    items: tuple[ClinicalItem, ...]
    total: int
    band: Band
    pattern: Pattern
    reference: str = REFERENCE

    @classmethod
    def of(cls, window: Sequence[ClipScores]) -> "ClinicalExposure":
        """Raises ZeroDivisionError if `window` is empty."""
        items = tuple(ClinicalItem.of(c, window) for c in CRITERIA)
        total = sum(i.score for i in items)
        return cls(window_n=len(window), items=items, total=total, band=band_of(total),
                   pattern=pattern_of(items))

    @property
    def level(self) -> Level:
        """warning at the validated cutoff (>= 10) or a "major" pattern; watch at >= 5 or an
        "other" pattern; else normal. Fixed by the research, not tuned."""
        if self.total >= MODERATE_FROM or self.pattern == "major":
            return "warning"
        return "watch" if self.total >= MILD_FROM or self.pattern == "other" else "normal"

    def reason(self) -> str:
        """e.g. "PHQ-9-style content exposure 12/27 (moderate, pattern other): depressed mood
        more than half the days, sleep several days"."""
        scored = sorted((i for i in self.items if i.score), key=lambda i: -i.score)
        named = ", ".join(f"{i.label.lower()} {i.frequency_label}"
                          for i in scored[:MAX_REASON_ITEMS])
        return (f"PHQ-9-style content exposure {self.total}/{MAX_SCORE} ({self.band}, "
                f"pattern {self.pattern}): {named or 'no theme on several days'}")
