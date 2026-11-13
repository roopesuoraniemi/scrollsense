import time
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from scrollsense.analysis_queue import AnalysisQueue, Pacer
from scrollsense.auth import BearerToken
from scrollsense.intake import ViewIntake
from scrollsense.service import AnalysisService
from scrollsense.store import JsonFileStore
from scrollsense.viewlog import JsonlViewLog
from scrollsense.views_api import ViewerReports, ViewsApi

from .fakes import instant_mock, no_wait

TOKEN = "s3cret"
NOW = 1_000_000.0


def app(tmp_path: Path, token: str | None) -> FastAPI:
    store = JsonFileStore(tmp_path / "clips")
    log = JsonlViewLog(tmp_path / "views")
    queue = AnalysisQueue(AnalysisService(instant_mock(), store, time.time), store,
                          Pacer(0.0, time.monotonic, no_wait))
    queue.start(2)
    api = ViewsApi(ViewIntake(log, queue), ViewerReports(log, store, queue), lambda: NOW)
    built = FastAPI()
    built.include_router(api.router(), dependencies=[Depends(BearerToken(token))] if token else [])
    return built


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(app(tmp_path, None))


def batch(viewer: str, *video_ids: str) -> dict:
    events = [{"event_id": f"{viewer}-{v}", "url": f"https://m.youtube.com/shorts/{v}",
               "seen_at": NOW - 600 + i, "dwell_s": 4.0} for i, v in enumerate(video_ids)]
    return {"viewer": viewer, "events": events}


def wait_scored(client: TestClient, viewer: str) -> list[dict]:
    for _ in range(200):
        feed = client.get(f"/api/viewers/{viewer}/feed").json()
        if all(item["state"] == "scored" for item in feed):
            return feed
        time.sleep(0.01)
    raise AssertionError("feed never scored")


def test_post_views_then_feed_shows_scored_clips(client: TestClient) -> None:
    body = batch("patient-01", "aaaaaaaaaaa", "bbbbbbbbbbb")
    body["events"].append({"event_id": "x", "url": "https://example.com", "seen_at": NOW})
    response = client.post("/api/views", json=body)
    assert response.status_code == 202
    assert response.json() == {"accepted": 2, "duplicates": 0, "queued": 2,
                               "rejected": [{"event_id": "x", "reason": "Not a YouTube video ID: "
                                             "'https://example.com'"}]}
    feed = wait_scored(client, "patient-01")
    assert [item["event"]["video_id"] for item in feed] == ["bbbbbbbbbbb", "aaaaaaaaaaa"]
    assert feed[0]["clip"]["title"].startswith("[MOCK]")
    assert client.post("/api/views", json=batch("patient-01", "aaaaaaaaaaa")).json()["duplicates"] == 1


def test_non_shorts_events_are_logged_not_queued(client: TestClient) -> None:
    body = batch("patient-01", "ccccccccccc")
    body["events"][0]["surface"] = "watch"
    assert client.post("/api/views", json=body).json()["queued"] == 0
    assert client.get("/api/viewers/patient-01/feed").json()[0]["state"] == "pending"


def test_viewers_readout_and_queue(client: TestClient) -> None:
    client.post("/api/views", json=batch("patient-01", "aaaaaaaaaaa"))
    client.post("/api/views", json=batch("control-01", "bbbbbbbbbbb"))
    wait_scored(client, "patient-01")
    viewers = client.get("/api/viewers").json()
    assert [(v["viewer"], v["events"]) for v in viewers] == [("control-01", 1), ("patient-01", 1)]
    body = client.get("/api/viewers/patient-01/readout?control=control-01").json()
    assert body["current"]["n_shown"] == 1 and body["baseline"]["n_shown"] == 0
    assert body["control"]["current"]["n_shown"] == 1 and "clusters" in body["readout"]
    assert client.get("/api/queue").json()["depth"] >= 0


def test_bad_viewer_and_window_are_400(client: TestClient) -> None:
    assert client.post("/api/views", json={"viewer": "Bob", "events": []}).status_code == 400
    assert client.get("/api/viewers/Bob/feed").status_code == 400
    assert client.get("/api/viewers/patient-01/readout?from=10&to=5").status_code == 400


def test_erase_deletes_the_log(client: TestClient) -> None:
    client.post("/api/views", json=batch("patient-01", "aaaaaaaaaaa"))
    assert client.delete("/api/viewers/patient-01").status_code == 204
    assert client.get("/api/viewers/patient-01/feed").json() == []
    assert client.get("/api/viewers").json() == []


def test_token_is_required_when_set(tmp_path: Path) -> None:
    client = TestClient(app(tmp_path, TOKEN))
    assert client.get("/api/queue").status_code == 401
    assert client.get("/api/queue", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/queue", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200
