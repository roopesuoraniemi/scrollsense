import pytest

from scrollsense.domain import VideoId
from scrollsense.schemas import ClipScores

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
    base = {"negative_affect": 0, "positive_affect": 0, "arousal": 3}
    return ClipScores(rationale="r", stance="unrelated", hopeful=False, evidence="e",
                      **(base | overrides))


def test_clamped_forces_ranges() -> None:
    clamped = scores(arousal=0, negative_affect=5, positive_affect=-1).clamped()
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
