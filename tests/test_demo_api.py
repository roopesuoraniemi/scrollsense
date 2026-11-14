import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from scrollsense.analysis_queue import AnalysisQueue, Pacer
from scrollsense.demo_api import DemoApi, ShortAdder
from scrollsense.domain import AnalysisRequest, VideoId
from scrollsense.scheduling import CachedScheduler, LiveScheduler, RunBudget, RunLimits
from scrollsense.service import AnalysisService
from scrollsense.store import JsonFileStore

from .fakes import instant_mock, no_wait

IDS = ("aaaaaaaaaaa", "bbbbbbbbbbb")


def client(tmp_path: Path, live: bool, limits: RunLimits = RunLimits()) -> TestClient:
    store = JsonFileStore(tmp_path / "clips")
    service = AnalysisService(instant_mock(), store, time.time)
    service.run(AnalysisRequest(VideoId(IDS[0])), lambda stage: None)
    queue = AnalysisQueue(service, store, Pacer(0.0, time.monotonic, no_wait))
    scheduler = (LiveScheduler if live else CachedScheduler)(queue, RunBudget(limits))
    app = FastAPI()
    app.include_router(DemoApi(ShortAdder(scheduler, queue, store)).router())
    return TestClient(app)


def add(test: TestClient, video: str, viewer: str = "demo-ab12") -> tuple[int, dict]:
    response = test.post("/api/demo/shorts",
                         json={"viewer": viewer, "url": f"https://youtube.com/shorts/{video}"})
    return response.status_code, response.json()


def test_cached_mode_queues_a_new_short(tmp_path: Path) -> None:
    assert add(client(tmp_path, live=False), IDS[1]) == (201, {"video_id": IDS[1], "state": "queued"})


def test_cached_mode_reports_a_stored_short(tmp_path: Path) -> None:
    assert add(client(tmp_path, live=False), IDS[0])[1]["state"] == "scored"


def test_live_mode_waits_for_the_view(tmp_path: Path) -> None:
    assert add(client(tmp_path, live=True), IDS[1]) == (201, {"video_id": IDS[1], "state": "pending"})


def test_over_quota_is_429(tmp_path: Path) -> None:
    assert add(client(tmp_path, live=True, limits=RunLimits(per_viewer=0)), IDS[1])[0] == 429


def test_bad_input_is_400(tmp_path: Path) -> None:
    test = client(tmp_path, live=True)
    assert add(test, IDS[0], viewer="Not A Viewer")[0] == 400
    assert test.post("/api/demo/shorts", json={"viewer": "demo-ab12", "url": "nope"}).status_code == 400
