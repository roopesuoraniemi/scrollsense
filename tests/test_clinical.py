from fractions import Fraction

import pytest

from scrollsense.drift.clinical import (FREQUENCY_LABELS, ClinicalExposure, ClinicalItem,
                                        band_of, item_score, pattern_of)
from scrollsense.schemas import CRITERIA

from .test_drift import NEUTRAL


def items(**scores: int) -> tuple[ClinicalItem, ...]:
    """The nine items, scored as given by code (A1=2, ...), else 0."""
    return tuple(ClinicalItem(code=c.code, label=c.label, present=0, share=0.0,
                              score=scores.get(c.code, 0),
                              frequency_label=FREQUENCY_LABELS[scores.get(c.code, 0)])
                 for c in CRITERIA)


@pytest.mark.parametrize(("present", "of", "score"), [
    (0, 14, 0), (1, 14, 0), (2, 14, 1), (7, 14, 1), (8, 14, 2), (11, 14, 2), (12, 14, 3),
    (14, 14, 3), (1, 10, 0), (2, 10, 1), (5, 10, 1), (6, 10, 2), (8, 10, 2), (9, 10, 3)])
def test_item_score_at_each_phq_frequency_boundary(present: int, of: int, score: int) -> None:
    assert item_score(Fraction(present, of)) == score


@pytest.mark.parametrize(("total", "band"), [
    (0, "minimal"), (4, "minimal"), (5, "mild"), (9, "mild"), (10, "moderate"), (14, "moderate"),
    (15, "moderately severe"), (19, "moderately severe"), (20, "severe"), (27, "severe")])
def test_kroenke_bands(total: int, band: str) -> None:
    assert band_of(total) == band


def test_algorithm_major_other_none_needs_mood_or_anhedonia() -> None:
    assert pattern_of(items(A1=2, A3=2, A4=3, A6=2, A8=2)) == "major"
    assert pattern_of(items(A2=3, A4=2, A6=2, A7=2, A8=2, A9=2)) == "major"
    assert pattern_of(items(A2=2, A6=2)) == "other"
    assert pattern_of(items(A1=3, A3=2, A4=2, A5=2)) == "other"
    assert pattern_of(items(A3=3, A4=3, A5=3, A6=3, A7=3, A8=3)) == "none"
    assert pattern_of(items(A1=3, A4=1, A6=1)) == "none"   # "several days" does not count


def test_a9_counts_like_every_other_item() -> None:
    assert pattern_of(items(A1=2, A9=2)) == "other"
    assert pattern_of(items(A1=2, A9=1)) == "none"


def test_exposure_counts_central_themes_only_and_sums_items() -> None:
    mood = NEUTRAL.model_copy(update={"a1_depressed_mood": 2})
    sleep = NEUTRAL.model_copy(update={"a4_sleep": 3})
    mention = NEUTRAL.model_copy(update={"a6_fatigue": 1})
    exposure = ClinicalExposure.of([mood] * 8 + [sleep] * 3 + [mention] * 3)
    scored = {i.code: (i.present, i.score, i.frequency_label) for i in exposure.items if i.present}
    assert scored == {"A1": (8, 2, "more than half the days"), "A4": (3, 1, "several days")}
    assert (exposure.window_n, exposure.total, exposure.band, exposure.pattern) == (
        14, 3, "minimal", "none")
    assert exposure.level == "normal" and "not the person's symptoms" in exposure.reference


def test_clinical_levels_follow_the_fixed_cutoffs() -> None:
    def level(**scores: int) -> str:
        chosen = items(**scores)
        total = sum(i.score for i in chosen)
        return ClinicalExposure(window_n=14, items=chosen, total=total, band=band_of(total),
                                pattern=pattern_of(chosen)).level
    assert level(A3=3, A4=3, A5=3, A6=1) == "warning"           # total 10, no mood item
    assert level(A3=3, A4=3, A5=3) == "watch"                   # total 9
    assert level(A3=2, A4=2, A5=1) == "watch"                   # total 5
    assert level(A1=2, A4=2) == "watch"                         # pattern "other", total 4
    assert level(A3=2, A4=2) == "normal"                        # total 4, no pattern
