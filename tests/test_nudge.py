import time
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from scrollsense.analysis_queue import AnalysisQueue, Pacer
from scrollsense.drift.core import DriftDetector, DriftReport, TimelinePoint
from scrollsense.drift_api import FeedObserver, ViewerDrift
from scrollsense.scheduling import CachedScheduler
from scrollsense.intake import ViewerExtras, ViewIntake
from scrollsense.nudge import (AlreadyAnswered, BadChoice, Nudge, NudgeEntry, NudgeHistory,
                               NudgePolicy, NudgeResponse, NudgeSettings, warning_streak)
from scrollsense.nudge_api import NudgeApi, NudgeDesk, NudgeJudge
from scrollsense.nudgelog import JsonlNudgeLog
from scrollsense.schemas import ClipScores
from scrollsense.service import AnalysisService
from scrollsense.store import JsonFileStore
from scrollsense.viewlog import JsonlViewLog
from scrollsense.views import ViewerId, ViewEvent
from scrollsense.views_api import ViewerReports, ViewsApi

from .fakes import instant_mock, no_wait
from .test_drift import NEUTRAL, NORM, SAD, SMALL, analysis, judge, vid
from .test_views_api import NOW

SETTINGS = NudgeSettings()
POLICY = NudgePolicy(SETTINGS)
VIEWER = ViewerId("patient-01")
# "video" is allowed: the card asks how the videos feel, without naming any content.
CLINICAL_WORDS = ("depress", "diagnos", "drift", "warning", "suicid")


def report(*recent: ClipScores) -> DriftReport:
    return judge([NEUTRAL] * 8 + list(recent))


def issued(policy: NudgePolicy, recent: tuple[ClipScores, ...], at: float) -> Nudge:
    nudge = policy.decide(report(*recent), NudgeHistory(), at)
    assert nudge is not None
    return nudge


def history(nudge: Nudge, choice: str | None) -> NudgeHistory:
    answers = [NudgeResponse(nudge_id=nudge.id, choice=choice, at=nudge.created_at + 1)] \
        if choice else []
    return NudgeHistory.fold([nudge], answers)


def point(level: str) -> TimelinePoint:
    return TimelinePoint(video_id=vid(0), seen_at=0.0, score=0.0, level=level)


def test_warning_streak_counts_only_judged_points() -> None:
    assert warning_streak([point("learning"), point("warning"), point("warning")], 2)
    assert not warning_streak([point("warning"), point("watch"), point("warning")], 2)
    assert warning_streak([point("warning"), point("learning"), point("warning")], 2)
    assert not warning_streak([point("learning"), point("warning")], 2)


def test_support_nudge_on_the_first_warning() -> None:
    assert POLICY.decide(report(SAD), NudgeHistory(), NOW) is None  # no warning yet
    nudge = issued(POLICY, (SAD, SAD), NOW)
    assert nudge.card.kind == "support" and nudge.video_id is None
    assert nudge.card.title == "How do these videos feel right now?"
    assert [o.choice for o in nudge.card.options] == ["ok", "take_break", "not_now"]
    assert nudge.card.expires_at == NOW + 900
    patient_text = nudge.card.model_dump_json().lower()
    assert not any(word in patient_text for word in CLINICAL_WORDS)


def test_cooldown_and_im_ok_doubling() -> None:
    earlier = issued(POLICY, (SAD, SAD, SAD), NOW)
    sad = report(SAD, SAD, SAD)
    assert POLICY.decide(sad, history(earlier, "not_now"), NOW + 599) is None
    assert POLICY.decide(sad, history(earlier, "not_now"), NOW + 600) is not None
    assert POLICY.decide(sad, history(earlier, "ok"), NOW + 1199) is None
    assert POLICY.decide(sad, history(earlier, "ok"), NOW + 1200) is not None


def test_an_open_nudge_blocks_a_new_one_until_it_expires() -> None:
    earlier = issued(NudgePolicy(NudgeSettings(cooldown_s=0)), (SAD, SAD, SAD), NOW)
    pending = history(earlier, None)
    assert pending.newest_open(NOW + 899) == earlier
    assert pending.newest_open(NOW + 900) is None
    assert pending.entries[0].state(NOW + 900) == "expired"
    policy = NudgePolicy(NudgeSettings(cooldown_s=0))
    assert policy.decide(report(SAD, SAD, SAD), pending, NOW + 899) is None
    assert policy.decide(report(SAD, SAD, SAD), pending, NOW + 900) is not None


def test_quiet_hours_hold_back_support_nudges() -> None:
    quiet = NudgePolicy(NudgeSettings(quiet_from=0, quiet_to=23, tz_offset_min=0))
    at_noon = 12 * 3600.0
    assert quiet.decide(report(SAD, SAD, SAD), NudgeHistory(), at_noon) is None
    assert quiet.decide(report(SAD, SAD, SAD), NudgeHistory(), 23.5 * 3600) is not None


def test_disabled_and_settings_from_env() -> None:
    off = NudgeSettings.from_env({"SCROLLSENSE_NUDGE_ENABLED": "0"})
    assert NudgePolicy(off).decide(report(SAD, SAD, SAD), NudgeHistory(), NOW) is None
    env = NudgeSettings.from_env({"SCROLLSENSE_NUDGE_COOLDOWN_S": "60"})
    assert env.cooldown_s == 60
    with pytest.raises(ValueError):
        NudgeSettings.from_env({"SCROLLSENSE_NUDGE_QUIET_FROM": "23"})


def test_answering_checks_options_and_answers_once() -> None:
    entry = NudgeEntry(nudge=issued(POLICY, (SAD, SAD, SAD), NOW), response=None)
    assert entry.answer("take_break", NOW + 3).choice == "take_break"
    with pytest.raises(BadChoice):
        entry.answer("dance", NOW + 3)
    answered = entry.model_copy(update={"response": entry.answer("ok", NOW + 3)})
    with pytest.raises(AlreadyAnswered):
        answered.answer("ok", NOW + 4)


def test_nudge_log_round_trip_keeps_the_first_answer(tmp_path: Path) -> None:
    log = JsonlNudgeLog(tmp_path)
    first, second = issued(POLICY, (SAD, SAD, SAD), NOW), issued(POLICY, (SAD, SAD, SAD), NOW + 1)
    for nudge in (first, second):
        log.record(nudge)
    answer = NudgeResponse(nudge_id=first.id, choice="ok", at=NOW + 2)
    log.respond(VIEWER, answer)
    log.respond(VIEWER, answer.model_copy(update={"choice": "not_now"}))
    assert log.history(VIEWER) == NudgeHistory(entries=(
        NudgeEntry(nudge=first, response=answer), NudgeEntry(nudge=second, response=None)))


def test_nudge_log_still_reads_cards_of_retired_kinds(tmp_path: Path) -> None:
    old = issued(POLICY, (SAD, SAD, SAD), NOW)
    retired = old.model_copy(update={"card": old.card.model_copy(update={"kind": "retired"})})
    JsonlNudgeLog(tmp_path).record(retired)
    read_back = JsonlNudgeLog(tmp_path).history(VIEWER)
    assert read_back.entries[0].nudge == retired and read_back.last_support() is None


def test_viewers_ignore_nudge_files_which_erase_removes(tmp_path: Path) -> None:
    JsonlNudgeLog(tmp_path).record(issued(POLICY, (SAD, SAD, SAD), NOW))
    views = JsonlViewLog(tmp_path)
    views.append([ViewEvent(event_id="e", viewer="patient-01", video_id=vid(1), seen_at=NOW)])
    assert views.viewers() == (VIEWER,)
    JsonlNudgeLog(tmp_path).erase(VIEWER)
    assert JsonlNudgeLog(tmp_path).history(VIEWER) == NudgeHistory()


def shorts(*indices: int) -> dict:
    """Views of the Shorts `vid(i)`, seen 10 s apart in index order."""
    events = [{"event_id": f"e{i}", "url": f"https://m.youtube.com/shorts/{vid(i)}",
               "seen_at": NOW - 600 + 10 * i} for i in indices]
    return {"viewer": "patient-01", "events": events}


def scored_store(directory: Path) -> JsonFileStore:
    """Eight neutral Shorts, then three sad ones, already analysed."""
    store = JsonFileStore(directory)
    for i, scores in enumerate([NEUTRAL] * 8 + [SAD] * 3):
        store.save(analysis(i, scores))
    return store


def routers(tmp_path: Path) -> tuple[APIRouter, ...]:
    store, log = scored_store(tmp_path / "clips"), JsonlViewLog(tmp_path / "views")
    queue = AnalysisQueue(AnalysisService(instant_mock(), store, time.time), store,
                          Pacer(0.0, time.monotonic, no_wait))
    drift = ViewerDrift(FeedObserver(log, store), DriftDetector(SMALL, NORM))
    desk = NudgeDesk(JsonlNudgeLog(tmp_path / "views"), NudgeJudge(drift, POLICY), lambda: NOW)
    views = ViewsApi(ViewIntake(log, CachedScheduler(queue), ViewerExtras(desk)),
                     ViewerReports(log, store, queue))
    return views.router(), NudgeApi(desk).router()


def nudge_app(tmp_path: Path) -> FastAPI:
    built = FastAPI()
    for router in routers(tmp_path):
        built.include_router(router)
    return built


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(nudge_app(tmp_path))


def open_card(client: TestClient) -> dict:
    client.post("/api/views", json=shorts(*range(11)))
    return client.post("/api/views", json=shorts(10)).json()["nudge"]


def answer(client: TestClient, nudge_id: str, body: dict) -> int:
    return client.post(f"/api/viewers/patient-01/nudges/{nudge_id}/response", json=body).status_code


def test_a_longer_streak_waits_for_more_warnings() -> None:
    patient = NudgePolicy(SETTINGS.model_copy(update={"streak": 2}))
    assert patient.decide(report(SAD, SAD), NudgeHistory(), NOW) is None
    assert patient.decide(report(SAD, SAD, SAD), NudgeHistory(), NOW) is not None


def test_receipt_carries_the_open_nudge_only_once_due(client: TestClient) -> None:
    assert client.post("/api/views", json=shorts(*range(9))).json()["nudge"] is None
    card = client.post("/api/views", json=shorts(9)).json()["nudge"]
    assert card["kind"] == "support" and set(card) == {"id", "kind", "title", "message", "options",
                                                       "expires_at"}
    assert client.post("/api/views", json=shorts(10)).json()["nudge"] == card


def test_answered_nudge_leaves_the_receipt_and_shows_in_history(client: TestClient) -> None:
    card = open_card(client)
    assert answer(client, card["id"], {"choice": "take_break"}) == 204
    assert client.post("/api/views", json=shorts(10)).json()["nudge"] is None
    [item] = client.get("/api/viewers/patient-01/nudges").json()
    assert item["state"] == "answered" and item["response"]["choice"] == "take_break"
    assert item["nudge"]["card"] == card and item["nudge"]["reason"].startswith("Drift warning")
    assert "SD into the bottom left" in item["nudge"]["reason"]


def test_response_status_codes(client: TestClient) -> None:
    card = open_card(client)
    assert answer(client, "nope", {"choice": "ok"}) == 404
    assert answer(client, card["id"], {"choice": "dance"}) == 422
    assert answer(client, card["id"], {}) == 422
    assert answer(client, card["id"], {"choice": "ok"}) == 204
    assert answer(client, card["id"], {"choice": "ok"}) == 409


def test_erasing_a_viewer_removes_their_nudges(client: TestClient, tmp_path: Path) -> None:
    open_card(client)
    nudges = tmp_path / "views" / "patient-01.nudges.jsonl"
    assert nudges.exists()
    assert client.delete("/api/viewers/patient-01").status_code == 204
    assert not nudges.exists() and client.get("/api/viewers/patient-01/nudges").json() == []
