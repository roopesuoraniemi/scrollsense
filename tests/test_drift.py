from typing import Sequence

import pytest

from scrollsense.domain import ClipAnalysis, Embedding
from scrollsense.drift.core import (FEATURES, BaselineMark, DriftConfig, DriftDetector, Observed,
                                    observe)
from scrollsense.schemas import CRITERIA, ClipScores, TextPackage
from scrollsense.views import ViewEvent

from .fakes import label

# valence 4, arousal 3, no negative affect, no themes, unrelated stance.
NEUTRAL = ClipScores(rationale="r", evidence="calm", negative_affect=0, positive_affect=2,
                     arousal=3, stance="unrelated", hopeful=False, **{c.key: 0 for c in CRITERIA})
# valence 1, arousal 1, negative affect 3, theme load 6, dwelling.
SAD = NEUTRAL.model_copy(update={"negative_affect": 3, "positive_affect": 0, "arousal": 1,
                                 "stance": "dwelling_or_romanticising", "a1_depressed_mood": 3,
                                 "a2_anhedonia": 3})
HAPPY = NEUTRAL.model_copy(update={"positive_affect": 3, "arousal": 5})
SMALL = DriftConfig(baseline_n=8, min_baseline=8, window=4)


def vid(i: int) -> str:
    return f"v{i:010d}"


def view(i: int, seen_at: float) -> ViewEvent:
    return ViewEvent(event_id=f"e{i}-{seen_at}", viewer="patient-01", video_id=vid(i),
                     seen_at=seen_at)


def analysis(i: int, scores: ClipScores) -> ClipAnalysis:
    package = TextPackage(title=f"clip {i}", transcript="", on_screen_text="",
                          visual_description="", audio_description="", emotional_cues="",
                          intended_meaning="", main_message="", format="other",
                          people_present=False, language="en")
    return ClipAnalysis(video_id=vid(i), analyser=label(), created=0.0, package=package,
                        scores=scores, embedding=Embedding())


def feed(clips: Sequence[ClipScores]) -> Observed:
    """One view per clip, 10 s apart, all analysed."""
    analyses = {vid(i): analysis(i, s) for i, s in enumerate(clips)}
    return observe([view(i, 10.0 * i) for i in range(len(clips))], analyses)


def test_features_follow_the_spec() -> None:
    values = {f.name: (f.extract(SAD), f.direction, f.weight, f.sd_floor) for f in FEATURES}
    assert values == {"valence": (1, -1, 1.0, 0.5), "arousal": (1, -1, 0.5, 0.5),
                      "negative_affect": (3, 1, 1.0, 0.5), "theme_load": (6, 1, 1.0, 1.5),
                      "dwelling": (1.0, 1, 1.0, 0.15)}
    assert {f.name: f.extract(NEUTRAL) for f in FEATURES}["dwelling"] == 0.0


def test_observe_keeps_first_views_in_seen_order_and_counts_pending() -> None:
    watch = view(4, 5.0).model_copy(update={"surface": "watch"})
    events = [view(2, 30.0), view(1, 20.0), view(1, 99.0), view(3, 40.0), watch]
    result = observe(events, {vid(1): analysis(1, NEUTRAL), vid(2): analysis(2, SAD),
                              vid(4): analysis(4, SAD)})
    assert [(o.video_id, o.seen_at) for o in result.analysed] == [(vid(1), 20.0), (vid(2), 30.0)]
    assert result.pending == 1


def test_default_baseline_is_the_first_n_and_drift_is_scored() -> None:
    report = DriftDetector(SMALL).report("patient-01", feed([NEUTRAL] * 8 + [SAD] * 4), None)
    assert (report.baseline.n, report.baseline.source, report.recent.n) == (8, "default", 4)
    assert report.baseline.centroid is not None and report.baseline.centroid.valence == 4.0
    assert report.recent.first_seen_at == 80.0 and report.level == "warning"
    # Uniform baseline, so every SD is floored: (6 + 0.5*4 + 6 + 4 + 1/0.15) / 4.5.
    assert report.score == pytest.approx((6 + 2 + 6 + 4 + 1 / 0.15) / 4.5)
    assert report.reasons[0] == "dwelling stance 6.7 SD above normal (1.0 vs 0.0)"
    assert len(report.reasons) == 3


def test_sd_floor_and_population_sd() -> None:
    lower = NEUTRAL.model_copy(update={"positive_affect": 0})   # valence 4 -> 3
    report = DriftDetector(SMALL).report("p", feed([NEUTRAL] * 8 + [lower] * 4), None)
    rows = {r.name: r for r in report.features}
    assert rows["valence"].effect == pytest.approx(-2.0) and rows["valence"].risk_effect == 2.0
    assert report.score == pytest.approx(2.0 / 4.5) and report.level == "normal"
    spread = DriftDetector(SMALL).report("p", feed([NEUTRAL, SAD] * 4 + [SAD] * 4), None)
    valence = {r.name: r for r in spread.features}["valence"]
    assert valence.baseline_sd == pytest.approx(1.5)
    assert valence.effect == pytest.approx((1 - 2.5) / 1.5)


def test_moves_in_the_safe_direction_never_count() -> None:
    report = DriftDetector(SMALL).report("p", feed([NEUTRAL] * 8 + [HAPPY] * 4), None)
    assert report.score == 0.0 and report.level == "normal" and report.reasons == ()
    assert report.evidence == ()


def test_levels_at_thresholds() -> None:
    config = DriftConfig(watch=0.8, warn=1.5)
    assert [config.level_of(s) for s in (0.0, 0.7999, 0.8, 1.4999, 1.5, 9.0)] == [
        "normal", "normal", "watch", "watch", "warning", "warning"]


def test_config_from_env_and_validation() -> None:
    config = DriftConfig.from_env({"SCROLLSENSE_DRIFT_WINDOW": "7", "SCROLLSENSE_DRIFT_WARN": "2.5",
                                   "SCROLLSENSE_BASELINE_N": ""})
    assert (config.window, config.warn, config.baseline_n, config.min_recent) == (7, 2.5, 20, 4)
    with pytest.raises(ValueError):
        DriftConfig.from_env({"SCROLLSENSE_DRIFT_WATCH": "2", "SCROLLSENSE_DRIFT_WARN": "1"})
    with pytest.raises(ValueError):
        DriftConfig(baseline_n=5, min_baseline=8)


def test_learning_until_baseline_and_recent_window_fill() -> None:
    detector = DriftDetector(DriftConfig())
    early = detector.report("p", feed([NEUTRAL] * 12), None)
    assert (early.level, early.note, early.score) == ("learning", "Learning normal: 12/20 Shorts", None)
    assert early.timeline == () and early.features == ()
    filling = detector.report("p", feed([NEUTRAL] * 20 + [SAD] * 4), None)
    assert filling.level == "learning" and filling.score is not None
    assert filling.note == "Normal learned from 20 Shorts; collecting recent ones: 4/5"
    assert detector.report("p", feed([NEUTRAL] * 20 + [SAD] * 5), None).level == "warning"


def test_marked_baseline_is_the_most_recent_n_at_marking() -> None:
    detector = DriftDetector(SMALL)
    history = [NEUTRAL] * 8 + [SAD] * 8
    mark = detector.mark(feed(history), None, now=500.0)
    assert mark.video_ids == tuple(vid(i) for i in range(8, 16)) and mark.marked_at == 500.0
    later = detector.report("p", feed(history + [SAD] * 4), mark)
    assert (later.baseline.source, later.baseline.n, later.recent.n) == ("marked", 8, 4)
    assert later.level == "normal" and later.score == 0.0
    assert later.baseline.first_seen_at == 80.0
    assert detector.report("p", feed(history + [SAD] * 4), None).level == "warning"


def test_marking_needs_enough_analysed_shorts() -> None:
    detector = DriftDetector(SMALL)
    with pytest.raises(ValueError):
        detector.mark(feed([NEUTRAL] * 7), None, now=0.0)
    with pytest.raises(ValueError):
        detector.mark(feed([NEUTRAL] * 20), 3, now=0.0)
    assert len(detector.mark(feed([NEUTRAL] * 20), 10, now=0.0).video_ids) == 10


def test_a_mark_whose_shorts_are_gone_is_learning() -> None:
    gone = BaselineMark(video_ids=("zzzzzzzzzzz",), marked_at=0.0)
    report = DriftDetector(SMALL).report("p", feed([NEUTRAL] * 12), gone)
    assert (report.level, report.baseline.n, report.baseline.target) == ("learning", 0, 1)


def test_timeline_scores_the_window_ending_at_each_short_after_the_baseline() -> None:
    report = DriftDetector(SMALL).report("p", feed([NEUTRAL] * 8 + [NEUTRAL, SAD, SAD, SAD, SAD]),
                                         None)
    timeline = report.timeline
    assert [p.seen_at for p in timeline] == [80.0, 90.0, 100.0, 110.0, 120.0]
    assert [p.level for p in timeline][:2] == ["learning", "warning"]
    assert timeline[0].score == 0.0 and timeline[1].score > 0
    assert timeline[-1].score == pytest.approx(report.score)


def test_evidence_ranks_risky_recent_shorts_and_safety_is_always_on() -> None:
    a9 = NEUTRAL.model_copy(update={"a9_death_suicide": 1, "evidence": "unalive"})
    report = DriftDetector(SMALL).report("p", feed([NEUTRAL] * 8 + [NEUTRAL, HAPPY, a9, SAD]),
                                         None)
    assert [e.video_id for e in report.evidence] == [vid(11), vid(10)]
    assert report.evidence[0].risk > report.evidence[1].risk > 0
    assert report.evidence[0].stance == "dwelling_or_romanticising"
    learning = DriftDetector(DriftConfig()).report("p", feed([NEUTRAL, a9]), None)
    assert learning.level == "learning"
    assert [(s.video_id, s.a9, s.evidence) for s in learning.safety] == [(vid(1), 1, "unalive")]
