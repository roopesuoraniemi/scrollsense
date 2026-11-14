import pytest

from scrollsense.api import ClipSummary
from scrollsense.domain import ClipAnalysis, ContentAxis, Embedding, VideoId
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


# A 2-d toy axis: light Shorts point along (1, 0), heavy ones along (0, 1).
AXIS = ContentAxis(embed_model="mock", x=(-0.7071, 0.7071), x_light=-0.7071, x_heavy=0.7071,
                   y=(0.7071, 0.7071), y_mean=0.7071, y_sd=0.5)


def test_content_axis_maps_the_light_and_heavy_centroids_to_0_and_1() -> None:
    light, heavy = AXIS.project(analysis("a" * 11, (2.0, 0.0))), AXIS.project(analysis("b" * 11, (0.0, 3.0)))
    assert light is not None and heavy is not None
    assert (light.x, heavy.x) == pytest.approx((0.0, 1.0), abs=1e-3)
    assert light.y == pytest.approx(0.0, abs=1e-3)


@pytest.mark.parametrize("vector", [None, (), (1.0, 0.0, 0.0)])
def test_content_axis_needs_a_vector_of_the_right_size(vector: tuple[float, ...] | None) -> None:
    assert AXIS.project(analysis("a" * 11, vector)) is None


def test_content_axis_ignores_embeddings_from_another_model() -> None:
    assert AXIS.model_copy(update={"embed_model": "gemini-embedding-2"}).project(analysis("a" * 11, (1.0, 0.0))) is None


def test_summary_places_clip_in_symptom_space() -> None:
    clip = analysis("a" * 11, None)
    s = clip.scores
    point = ClipSummary.of(clip, None).symptoms
    assert (point.x, point.y) == (s.a1_depressed_mood + s.a2_anhedonia, s.a4_sleep + s.a6_fatigue)
