import pytest

from scrollsense.domain import ClipAnalysis, Embedding
from scrollsense.feed import Composition, Shift, composition, readout
from scrollsense.schemas import CRITERIA, ClipScores, Format, Stance, TextPackage
from scrollsense.views import EVER, ViewEvent, Window

from .fakes import label

HOUR = 3600.0
SAD = {"a1_depressed_mood": 3, "a4_sleep": 2}


def package(fmt: Format) -> TextPackage:
    return TextPackage(title="t", transcript="", on_screen_text="", visual_description="",
                       audio_description="", emotional_cues="", intended_meaning="",
                       main_message="", format=fmt, people_present=False, language="en")


def scores(stance: Stance = "unrelated", themes: dict[str, int] | None = None,
           negative: int = 0) -> ClipScores:
    return ClipScores(rationale="r", evidence="evidence", negative_affect=negative,
                      positive_affect=0, arousal=3, stance=stance, hopeful=False,
                      **({c.key: 0 for c in CRITERIA} | (themes or {})))


NEUTRAL = scores()
SAD_SCORES = scores("dwelling_or_romanticising", SAD, negative=3)


def analysis(video_id: str, clip_scores: ClipScores = NEUTRAL, fmt: Format = "other") -> ClipAnalysis:
    return ClipAnalysis(video_id=video_id, analyser=label(), created=0.0, package=package(fmt),
                        scores=clip_scores, embedding=Embedding())


def sad(video_id: str) -> ClipAnalysis:
    return analysis(video_id, SAD_SCORES)


def view(video_id: str, seen_at: float, tz: int = 0) -> ViewEvent:
    return ViewEvent(event_id=f"{video_id}{seen_at}", viewer="patient-01", video_id=video_id,
                     seen_at=seen_at, tz_offset_min=tz)


def dwelled(video_id: str, seen_at: float, dwell: float) -> ViewEvent:
    return view(video_id, seen_at).model_copy(update={"dwell_s": dwell})


def ids(n: int, prefix: str) -> list[str]:
    return [f"{prefix}{i:02d}".ljust(11, "x") for i in range(n)]


def test_theme_share_needs_score_two_and_dwelling_stance() -> None:
    analyses = {a.video_id: a for a in (
        sad("aaaaaaaaaaa"),
        analysis("bbbbbbbbbbb", scores("coping_or_recovery", SAD)),
        analysis("ccccccccccc", scores("dwelling_or_romanticising", {"a1_depressed_mood": 1})),
    )}
    events = [view(v, 12 * HOUR) for v in analyses] + [view("ddddddddddd", 12 * HOUR)]
    result = composition(events, analyses, EVER)
    assert (result.n_shown, result.n_scored) == (4, 3)
    assert result.theme_share["a1_depressed_mood"] == pytest.approx(1 / 3)
    assert result.theme_share["a7_worthlessness_guilt"] == 0.0
    assert result.negative_share == pytest.approx(1 / 3) and result.mean_valence == pytest.approx(7 / 3)


def test_night_share_uses_local_time_and_window() -> None:
    events = [view("aaaaaaaaaaa", 23.5 * HOUR, tz=120),   # 01:30 local
              view("bbbbbbbbbbb", 3 * HOUR, tz=-240),     # 23:00 local
              view("ccccccccccc", 12 * HOUR),
              view("ddddddddddd", 100 * HOUR)]            # outside the window
    result = composition(events, {}, Window(start=0.0, end=24 * HOUR))
    assert result.n_shown == 3 and result.night_share == pytest.approx(1 / 3)
    assert result.n_scored == 0 and result.mean_valence is None and result.theme_share["a1_depressed_mood"] is None


def test_format_entropy_is_zero_for_one_format_and_one_when_uniform() -> None:
    same = [analysis(v, fmt="meme") for v in ids(4, "m")]
    assert composition([view(a.video_id, 0.0) for a in same],
                       {a.video_id: a for a in same}, EVER).format_entropy == 0.0
    formats: list[Format] = ["talking_to_camera", "broll_with_text", "meme", "music_edit", "skit",
                             "tutorial", "animation", "animals_nature", "other"]
    spread = [analysis(v, fmt=f) for v, f in zip(ids(9, "u"), formats)]
    assert composition([view(a.video_id, 0.0) for a in spread],
                       {a.video_id: a for a in spread}, EVER).format_entropy == pytest.approx(1.0)


def test_empty_window_is_all_none() -> None:
    result = composition([], {}, EVER)
    assert (result.n_shown, result.n_scored, result.night_share, result.median_dwell_s) == (0, 0, None, None)
    assert result.format_entropy is None


def test_median_dwell() -> None:
    a9 = analysis("aaaaaaaaaaa", scores(themes={"a9_death_suicide": 1}))
    events = [dwelled("aaaaaaaaaaa", 5.0, 2.0), dwelled("bbbbbbbbbbb", 6.0, 8.0),
              dwelled("ccccccccccc", 7.0, 4.0), view("ddddddddddd", 8.0)]
    result = composition(events, {"aaaaaaaaaaa": a9}, EVER)
    assert result.median_dwell_s == 4.0
    assert "safety_hits" not in result.model_dump()


def mix(n_sad: int, n_neutral: int, night: bool = False) -> Composition:
    analyses = [sad(v) for v in ids(n_sad, "s")] + [analysis(v) for v in ids(n_neutral, "n")]
    hour = 2 * HOUR if night else 12 * HOUR
    return composition([view(a.video_id, hour) for a in analyses],
                       {a.video_id: a for a in analyses}, EVER)


def test_readout_flags_drift_and_rates_clusters() -> None:
    result = readout(mix(5, 5, night=True), mix(1, 9), None)
    assert result.deltas["a1_depressed_mood"] == pytest.approx(0.4)
    assert {"a1_depressed_mood", "a4_sleep", "mean_valence", "negative_share", "night_share"} <= set(result.flags)
    levels = {c.name: c.level for c in result.clusters}
    assert levels == {"sleep_fatigue": "flag", "anhedonia_hopelessness": "watch",
                      "worthlessness_guilt": "stable"}
    assert result.control_deltas is None


def test_readout_threshold_is_inclusive() -> None:
    assert "a1_depressed_mood" in readout(mix(7, 13), mix(4, 16), None).flags   # 0.35 - 0.20
    assert "a1_depressed_mood" not in readout(mix(6, 14), mix(4, 16), None).flags


def test_control_drifting_too_suppresses_the_flag() -> None:
    control = Shift(current=mix(5, 5), baseline=mix(1, 9))
    result = readout(mix(5, 5, night=True), mix(1, 9), control)
    assert "a1_depressed_mood" not in result.flags and "night_share" in result.flags
    assert result.control_deltas is not None and result.control_deltas["a1_depressed_mood"] == pytest.approx(0.4)


def test_readout_of_empty_windows_flags_nothing() -> None:
    empty = composition([], {}, EVER)
    result = readout(empty, empty, Shift(current=empty, baseline=empty))
    assert result.flags == () and all(c.level == "stable" for c in result.clusters)
    assert result.deltas["mean_valence"] is None
