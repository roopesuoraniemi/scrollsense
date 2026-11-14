import math
from typing import Sequence

import pytest

from scrollsense.affect_norms import load_affect_norms
from scrollsense.domain import ClipAnalysis, Embedding
from scrollsense.drift.affect import FEATURES
from scrollsense.drift.core import DriftConfig, DriftDetector, DriftReport
from scrollsense.drift.levels import most_severe
from scrollsense.drift.observe import Observed, observe
from scrollsense.schemas import CRITERIA, ClipScores, TextPackage
from scrollsense.views import ViewEvent

from .fakes import label

NORMS = load_affect_norms()
NORM = NORMS.baseline
# valence 4, arousal 3, no negative affect, no themes, unrelated stance.
NEUTRAL = ClipScores(rationale="r", evidence="calm", negative_affect=0, positive_affect=2,
                     arousal=3, stance="unrelated", hopeful=False, **{c.key: 0 for c in CRITERIA})
# valence 1, arousal 1, depressed mood and anhedonia intense.
SAD = NEUTRAL.model_copy(update={"negative_affect": 3, "positive_affect": 0, "arousal": 1,
                                 "stance": "dwelling_or_romanticising", "a1_depressed_mood": 3,
                                 "a2_anhedonia": 3})
HAPPY = NEUTRAL.model_copy(update={"positive_affect": 3, "arousal": 5})
# Upbeat delivery (valence 4, arousal 3), but five criteria are central themes.
THEMED = NEUTRAL.model_copy(update={c.key: 2 for c in CRITERIA[:5]})
SMALL = DriftConfig(window=4)


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


def judge(clips: Sequence[ClipScores], config: DriftConfig = SMALL) -> DriftReport:
    return DriftDetector(config, NORM).report("patient-01", feed(clips))


def test_norms_json_holds_the_mapped_warriner_baseline_and_its_sources() -> None:
    assert (NORM.centre.valence, NORM.centre.arousal) == (3.032, 2.605)
    assert (NORM.sd.valence, NORM.sd.arousal) == (0.637, 0.448)
    warriner, nrc = NORMS.sources
    assert (warriner.n_words, warriner.valence.mean, warriner.arousal.sd) == (13915, 5.0638, 0.8964)
    assert (nrc.n_words, nrc.valence.mapped_sd, nrc.arousal.mapped_sd) == (19971, 0.863, 0.684)
    assert (NORMS.cross_check.n_shared_words, NORMS.cross_check.r_valence) == (13855, 0.814)
    assert "non-commercial" in nrc.licence and NORM.cite == "Warriner 2013"


def test_features_are_falls_in_valence_and_arousal() -> None:
    values = {f.name: (f.extract(SAD), f.direction, f.spread(NORM)) for f in FEATURES}
    assert values == {"valence": (1, -1, 0.637), "arousal": (1, -1, 0.448)}


def test_observe_keeps_first_views_in_seen_order_and_counts_pending() -> None:
    watch = view(4, 5.0).model_copy(update={"surface": "watch"})
    events = [view(2, 30.0), view(1, 20.0), view(1, 99.0), view(3, 40.0), watch]
    result = observe(events, {vid(1): analysis(1, NEUTRAL), vid(2): analysis(2, SAD),
                              vid(4): analysis(4, SAD)})
    assert [(o.video_id, o.seen_at) for o in result.analysed] == [(vid(1), 20.0), (vid(2), 30.0)]
    assert result.pending == 1


def test_affect_score_is_the_drift_length_in_research_sds() -> None:
    calm_low = NEUTRAL.model_copy(update={"positive_affect": 0, "arousal": 2})  # valence 3
    report = judge([calm_low] * 4)
    rows = {r.name: r for r in report.features}
    assert rows["valence"].effect == pytest.approx((3 - 3.032) / 0.637)
    assert rows["arousal"].effect == pytest.approx((2 - 2.605) / 0.448)
    assert rows["arousal"].norm_sd == 0.448 and rows["arousal"].norm_mean == 2.605
    expected = math.hypot((3 - 3.032) / 0.637, (2 - 2.605) / 0.448)
    assert report.score == pytest.approx(expected) and report.affect_level == "warning"
    assert report.affect_baseline == NORM


def test_affect_deviates_only_past_1_sd_in_the_bottom_left_quadrant() -> None:
    flat = NEUTRAL.model_copy(update={"positive_affect": 0})  # valence 3, arousal 3
    within = judge([flat, flat.model_copy(update={"arousal": 2})] * 2)  # mean arousal 2.5
    assert 0 < (within.score or 0) <= 1 and within.affect_level == "normal"
    agitated_sad = SAD.model_copy(update={"arousal": 5})  # valence 1, arousal 5: top left
    assert judge([agitated_sad] * 4).score == 0.0
    calm_happy = HAPPY.model_copy(update={"arousal": 1})  # valence 5, arousal 1: bottom right
    assert judge([calm_happy] * 4).affect_level == "normal"


def test_affect_reasons_follow_the_affect_level_and_skip_negligible_moves() -> None:
    calm_low = NEUTRAL.model_copy(update={"positive_affect": 0, "arousal": 2})  # valence 3
    assert judge([calm_low] * 4).reasons == (
        "valence and arousal 1.4 SD from the norm towards the bottom left "
        "(valence 3.0 vs 3.03, arousal 2.0 vs 2.60, Warriner 2013)",)
    assert judge([calm_low] * 4, DriftConfig(window=4, watch=5, warn=6)).reasons == ()


def test_moves_in_the_safe_direction_never_count() -> None:
    report = judge([HAPPY] * 4)
    assert report.score == 0.0 and report.level == "normal" and report.reasons == ()
    assert report.evidence == () and report.clinical is not None and report.clinical.total == 0


def test_levels_at_thresholds() -> None:
    assert [DriftConfig().level_of(s) for s in (0.0, 1.0, 1.0001)] == [
        "normal", "normal", "warning"]
    config = DriftConfig(watch=1.0, warn=1.5)
    assert [config.level_of(s) for s in (1.0, 1.0001, 1.5, 1.5001, 9.0)] == [
        "normal", "watch", "watch", "warning", "warning"]
    with pytest.raises(ValueError):
        DriftConfig(watch=0.5)


def test_config_from_env_and_validation() -> None:
    config = DriftConfig.from_env({"SCROLLSENSE_DRIFT_WINDOW": "7", "SCROLLSENSE_DRIFT_WARN": "2.5",
                                   "SCROLLSENSE_BASELINE_N": "20"})
    assert (config.window, config.warn, config.min_recent) == (7, 2.5, 4)
    assert (DriftConfig().window, DriftConfig().min_recent) == (10, 5)
    with pytest.raises(ValueError):
        DriftConfig.from_env({"SCROLLSENSE_DRIFT_WATCH": "2", "SCROLLSENSE_DRIFT_WARN": "1"})


def test_learning_only_until_half_the_window_and_heavy_from_the_start_is_flagged() -> None:
    early = judge([SAD] * 4, DriftConfig())
    assert (early.level, early.note) == ("learning", "Collecting recent Shorts: 4/5 analysed")
    assert early.score is not None and early.clinical is not None
    assert judge([], DriftConfig()).clinical is None
    assert judge([SAD] * 5, DriftConfig()).level == "warning"


def test_overall_level_is_the_more_severe_of_affect_and_clinical() -> None:
    sad = judge([SAD] * 4)
    assert (sad.affect_level, sad.clinical_level, sad.level) == ("warning", "watch", "warning")
    themed = judge([THEMED] * 4)
    assert (themed.affect_level, themed.clinical_level, themed.level) == (
        "normal", "warning", "warning")
    assert themed.clinical is not None and themed.clinical.pattern == "major"
    two = judge([NEUTRAL.model_copy(update={"a1_depressed_mood": 2, "a4_sleep": 2})] * 4)
    assert (two.affect_level, two.clinical_level, two.level) == ("normal", "watch", "watch")
    assert most_severe(["learning", "normal"]) == "normal"


def test_reasons_name_the_clinical_exposure_then_affect() -> None:
    report = judge([SAD] * 4)
    assert report.reasons == (
        "PHQ-9-style content exposure 6/27 (mild, pattern other): depressed mood nearly every "
        "day, anhedonia nearly every day",
        "valence and arousal 4.8 SD from the norm towards the bottom left "
        "(valence 1.0 vs 3.03, arousal 1.0 vs 2.60, Warriner 2013)",)
    assert report.note == "Heavy with depressive content"


def test_timeline_judges_the_window_ending_at_every_short() -> None:
    report = judge([NEUTRAL] * 4 + [SAD] * 4)
    timeline = report.timeline
    assert [p.seen_at for p in timeline] == [10.0 * i for i in range(8)]
    assert [p.level for p in timeline] == ["learning"] + ["normal"] * 4 + ["warning"] * 3
    assert [p.exposure for p in timeline][-4:] == [2, 2, 4, 6]
    assert timeline[-1].score == pytest.approx(report.score)


def test_evidence_ranks_central_themes_then_affect() -> None:
    low = NEUTRAL.model_copy(update={"positive_affect": 0, "arousal": 2})  # valence 3, no themes
    report = judge([NEUTRAL, low, SAD, THEMED])
    assert [e.video_id for e in report.evidence] == [vid(3), vid(2), vid(1)]
    assert report.evidence[0].central == ("A1", "A2", "A3", "A4", "A5")
    assert report.evidence[1].central == ("A1", "A2") and report.evidence[2].risk > 0
