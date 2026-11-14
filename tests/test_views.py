import pytest

from scrollsense.views import (Rejection, ViewerId, ViewEvent, ViewInput, Window, dedupe, fresh,
                               parse_events)

PATIENT = ViewerId("patient-01")
ID = "dQw4w9WgXcQ"


def event(event_id: str, seen_at: float, video_id: str = ID) -> ViewEvent:
    return ViewEvent(event_id=event_id, viewer="patient-01", video_id=video_id, seen_at=seen_at)


@pytest.mark.parametrize("value", ["patient-01", "abc", "control-2", "a" * 32])
def test_viewer_id_accepts_pseudonyms(value: str) -> None:
    assert ViewerId(value).value == value


@pytest.mark.parametrize("value", ["ab", "a" * 33, "Patient-01", "pat_01", "pat ient", "../etc"])
def test_viewer_id_rejects_others(value: str) -> None:
    with pytest.raises(ValueError):
        ViewerId(value)


def test_event_rejects_bad_viewer_and_video() -> None:
    with pytest.raises(ValueError):
        ViewEvent(event_id="e", viewer="Bob", video_id=ID, seen_at=0.0)
    with pytest.raises(ValueError):
        event("e", 0.0, video_id="short")


def test_input_takes_video_id_or_url() -> None:
    by_url = ViewInput(event_id="a", url=f"https://m.youtube.com/shorts/{ID}", seen_at=1.0)
    by_id = ViewInput(event_id="b", video_id=ID, seen_at=1.0, dwell_s=4.5)
    assert by_url.event(PATIENT).video_id == ID and by_id.event(PATIENT).dwell_s == 4.5
    assert by_id.event(PATIENT).viewer == "patient-01"


def test_parse_events_rejects_one_without_sinking_the_batch() -> None:
    inputs = [ViewInput(event_id="ok", video_id=ID, seen_at=1.0),
              ViewInput(event_id="none", seen_at=1.0),
              ViewInput(event_id="bad", url="https://example.com/x", seen_at=1.0)]
    parsed = parse_events(PATIENT, inputs)
    assert [e.event_id for e in parsed.events] == ["ok"]
    assert [r.event_id for r in parsed.rejected] == ["none", "bad"]
    assert parsed.rejected[0] == Rejection(event_id="none", reason="needs video_id or url")


def test_dedupe_drops_repeated_ids_and_quick_rewatches() -> None:
    events = [event("a", 100.0), event("a", 500.0), event("b", 120.0), event("c", 131.0),
              event("d", 110.0, video_id="aaaaaaaaaaa"), event("e", 100.0).model_copy(update={"viewer": "control-01"})]
    assert [e.event_id for e in dedupe(events)] == ["a", "c", "d", "e"]


def test_fresh_keeps_only_events_not_in_the_log() -> None:
    logged = [event("a", 100.0)]
    incoming = [event("a", 100.0), event("b", 110.0), event("c", 400.0), event("c", 400.0)]
    assert [e.event_id for e in fresh(logged, incoming)] == ["c"]


def test_window_is_half_open_and_ordered() -> None:
    window = Window(start=10.0, end=20.0)
    assert window.contains(10.0) and not window.contains(20.0)
    with pytest.raises(ValueError):
        Window(start=2.0, end=1.0)


def test_local_hour_uses_offset() -> None:
    utc_2330 = 23.5 * 3600
    shifted = event("a", utc_2330).model_copy(update={"tz_offset_min": 120})
    assert shifted.local_hour == pytest.approx(1.5)
    assert event("a", utc_2330).model_copy(update={"tz_offset_min": -60}).local_hour == pytest.approx(22.5)
