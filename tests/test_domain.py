import pytest

from scrollsense.domain import ClipAnalysis, Embedding, VideoId, semantic_points
from scrollsense.schemas import CRITERIA, ClipScores

from .fakes import instant_mock

ID = "dQw4w9WgXcQ"


@pytest.mark.parametrize("text", [
    ID, f" {ID} ", f"https://www.youtube.com/shorts/{ID}", f"https://youtu.be/{ID}?si=x",
    f"https://m.youtube.com/watch?v={ID}&t=1", f"https://www.youtube.com/embed/{ID}",
])
def test_parse_accepts_ids_and_urls(text: str) -> None:
    assert VideoId.parse(text) == VideoId(ID)


@pytest.mark.parametrize("text", ["", "not a url", "https://example.com/watch", "short"])
def test_parse_rejects_non_youtube(text: str) -> None:
    with pytest.raises(ValueError):
        VideoId.parse(text)


def test_watch_url() -> None:
    assert VideoId(ID).watch_url == f"https://www.youtube.com/watch?v={ID}"


def scores(**overrides: int) -> ClipScores:
    base = {c.key: 1 for c in CRITERIA} | {"negative_affect": 0, "positive_affect": 0, "arousal": 3}
    return ClipScores(rationale="r", stance="unrelated", hopeful=False, evidence="e",
                      **(base | overrides))


def test_clamped_forces_ranges() -> None:
    clamped = scores(a1_depressed_mood=7, a2_anhedonia=-2, arousal=0,
                     negative_affect=5, positive_affect=-1).clamped()
    assert (clamped.a1_depressed_mood, clamped.a2_anhedonia) == (3, 0)
    assert (clamped.negative_affect, clamped.positive_affect, clamped.arousal) == (3, 0, 1)
    assert scores(arousal=9).clamped().arousal == 5


@pytest.mark.parametrize(("negative", "positive", "valence"), [
    (3, 0, 1), (2, 0, 2), (1, 0, 2), (3, 1, 2), (2, 1, 2),
    (0, 0, 3), (2, 2, 3), (3, 3, 3),
    (0, 1, 4), (1, 3, 4), (0, 3, 5),
])
def test_valence_is_derived_from_affect(negative: int, positive: int, valence: int) -> None:
    assert scores(negative_affect=negative, positive_affect=positive).valence == valence


def test_valence_stays_in_range_before_clamping() -> None:
    assert scores(negative_affect=9).valence == 1 and scores(positive_affect=9).valence == 5


def test_rationale_is_generated_before_any_score() -> None:
    fields = list(ClipScores.model_json_schema()["properties"])
    assert fields[0] == "rationale" and fields.index("evidence") < fields.index("negative_affect")


def test_theme_load_sums_nine_criteria() -> None:
    assert scores().theme_load == 9


def analysis(video_id: str, vector: tuple[float, ...] | None) -> ClipAnalysis:
    mock = instant_mock()
    package = mock.describe(VideoId(video_id))
    return ClipAnalysis(video_id=video_id, analyser=mock.label, created=0.0, package=package,
                        scores=mock.score(package), embedding=Embedding(vector=vector))


def test_semantic_points_skips_missing_embeddings() -> None:
    points = semantic_points([analysis("aaaaaaaaaaa", None), analysis("bbbbbbbbbbb", (1.0, 2.0))])
    assert list(points) == ["bbbbbbbbbbb"]


def test_semantic_points_scaled_to_unit_box() -> None:
    vectors = [(0.0, 0.0, 1.0), (4.0, 1.0, 0.0), (1.0, 3.0, 2.0)]
    points = semantic_points([analysis(c * 11, v) for c, v in zip("abc", vectors)])
    assert len(points) == 3
    assert all(-1 <= p.x <= 1 and -1 <= p.y <= 1 for p in points.values())


def test_semantic_points_two_clips_pads_second_axis() -> None:
    points = semantic_points([analysis("a" * 11, (0.0, 1.0)), analysis("b" * 11, (1.0, 0.0))])
    assert {p.y for p in points.values()} == {0.0}
