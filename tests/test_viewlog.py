from pathlib import Path

from scrollsense.viewlog import JsonlViewLog
from scrollsense.views import EVER, ViewerId, ViewEvent, Window

ID = "dQw4w9WgXcQ"


def event(event_id: str, viewer: str, seen_at: float) -> ViewEvent:
    return ViewEvent(event_id=event_id, viewer=viewer, video_id=ID, seen_at=seen_at,
                     tz_offset_min=60, dwell_s=3.5, loops=1)


def test_round_trip_per_viewer(tmp_path: Path) -> None:
    log = JsonlViewLog(tmp_path / "views")
    first = [event("a", "patient-01", 10.0), event("b", "control-01", 11.0)]
    log.append(first)
    log.append([event("c", "patient-01", 20.0)])
    assert log.between(ViewerId("patient-01"), EVER) == (first[0], event("c", "patient-01", 20.0))
    assert log.between(ViewerId("patient-01"), Window(start=15.0, end=30.0))[0].event_id == "c"
    assert log.viewers() == (ViewerId("control-01"), ViewerId("patient-01"))
    assert (tmp_path / "views" / "patient-01.jsonl").read_text().count("\n") == 2


def test_erase_removes_only_that_viewer(tmp_path: Path) -> None:
    log = JsonlViewLog(tmp_path)
    log.append([event("a", "patient-01", 10.0), event("b", "control-01", 11.0)])
    log.erase(ViewerId("patient-01"))
    log.erase(ViewerId("nobody-00"))
    assert log.between(ViewerId("patient-01"), EVER) == ()
    assert log.viewers() == (ViewerId("control-01"),)
