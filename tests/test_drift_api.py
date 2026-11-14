import time
from pathlib import Path

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from scrollsense.analysis_queue import AnalysisQueue, Pacer
from scrollsense.auth import BearerToken
from scrollsense.baselines import JsonBaselineStore
from scrollsense.drift.core import BaselineMark, DriftConfig, DriftDetector
from scrollsense.drift_api import DriftApi, FeedObserver, ViewerDrift
from scrollsense.intake import ViewIntake
from scrollsense.service import AnalysisService
from scrollsense.store import JsonFileStore
from scrollsense.viewlog import JsonlViewLog
from scrollsense.views import ViewerId
from scrollsense.views_api import ViewerReports, ViewsApi

from .fakes import instant_mock, no_wait
from .test_views_api import NOW, TOKEN, batch, wait_scored

CONFIG = DriftConfig(baseline_n=8, min_baseline=4, window=4)
VIDEOS = [f"vid{i:08d}" for i in range(14)]


def routers(tmp_path: Path) -> list[APIRouter]:
    store = JsonFileStore(tmp_path / "clips")
    log = JsonlViewLog(tmp_path / "views")
    queue = AnalysisQueue(AnalysisService(instant_mock(), store, time.time), store,
                          Pacer(0.0, time.monotonic, no_wait))
    queue.start(2)
    baselines = JsonBaselineStore(tmp_path / "views")
    drift = ViewerDrift(FeedObserver(log, store), baselines, DriftDetector(CONFIG))
    return [ViewsApi(ViewIntake(log, queue, baselines), ViewerReports(log, store, queue), lambda: NOW).router(),
            DriftApi(drift, lambda: NOW).router()]


def app(tmp_path: Path, token: str | None) -> FastAPI:
    built = FastAPI()
    for router in routers(tmp_path):
        built.include_router(router, dependencies=[Depends(BearerToken(token))] if token else [])
    return built


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(app(tmp_path, None))


def test_baseline_store_round_trip(tmp_path: Path) -> None:
    store = JsonBaselineStore(tmp_path / "views")
    viewer = ViewerId("patient-01")
    mark = BaselineMark(video_ids=("aaaaaaaaaaa", "bbbbbbbbbbb"), marked_at=12.5)
    store.mark(viewer, mark)
    assert store.mark_of(viewer) == mark and store.mark_of(ViewerId("control-01")) is None
    assert sorted(p.name for p in (tmp_path / "views").iterdir()) == ["patient-01.baseline.json"]
    store.clear(viewer)
    store.clear(viewer)   # idempotent
    assert store.mark_of(viewer) is None


def test_drift_report_shape_while_learning(client: TestClient) -> None:
    client.post("/api/views", json=batch("patient-01", *VIDEOS[:3]))
    wait_scored(client, "patient-01")
    body = client.get("/api/viewers/patient-01/drift").json()
    assert body["level"] == "learning" and body["note"] == "Learning normal: 3/8 Shorts"
    assert body["config"] == CONFIG.model_dump() and body["pending"] == 0
    assert body["baseline"]["source"] == "default" and body["baseline"]["n"] == 3
    assert set(body) >= {"score", "recent", "features", "reasons", "evidence", "safety", "timeline"}


def test_marking_too_early_is_409(client: TestClient) -> None:
    client.post("/api/views", json=batch("patient-01", *VIDEOS[:3]))
    wait_scored(client, "patient-01")
    assert client.post("/api/viewers/patient-01/baseline").status_code == 409


def test_mark_and_reset_baseline(client: TestClient) -> None:
    client.post("/api/views", json=batch("patient-01", *VIDEOS))
    wait_scored(client, "patient-01")
    judged = client.get("/api/viewers/patient-01/drift").json()
    assert judged["level"] in {"normal", "watch", "warning"} and len(judged["timeline"]) == 6
    assert client.post("/api/viewers/patient-01/baseline", json={"size": 5}).status_code == 204
    marked = client.get("/api/viewers/patient-01/drift").json()
    assert (marked["baseline"]["source"], marked["baseline"]["n"], marked["recent"]["n"]) == (
        "marked", 5, 0) and marked["level"] == "learning"
    assert client.delete("/api/viewers/patient-01/baseline").status_code == 204
    assert client.get("/api/viewers/patient-01/drift").json()["baseline"]["source"] == "default"


def test_erasing_a_viewer_also_removes_the_baseline_mark(client: TestClient, tmp_path: Path) -> None:
    client.post("/api/views", json=batch("patient-01", *VIDEOS))
    wait_scored(client, "patient-01")
    client.post("/api/viewers/patient-01/baseline", json={"size": 5})
    assert client.delete("/api/viewers/patient-01").status_code == 204
    assert not (tmp_path / "views" / "patient-01.baseline.json").exists()


def test_bad_viewer_and_size(client: TestClient) -> None:
    assert client.get("/api/viewers/Bob/drift").status_code == 400
    assert client.post("/api/viewers/patient-01/baseline", json={"size": 0}).status_code == 422
    assert client.delete("/api/viewers/Bob/baseline").status_code == 400


def test_drift_routes_need_the_token(tmp_path: Path) -> None:
    client = TestClient(app(tmp_path, TOKEN))
    assert client.get("/api/viewers/patient-01/drift").status_code == 401
    assert client.post("/api/viewers/patient-01/baseline").status_code == 401
    assert client.delete("/api/viewers/patient-01/baseline").status_code == 401
    auth = {"Authorization": f"Bearer {TOKEN}"}
    assert client.get("/api/viewers/patient-01/drift", headers=auth).status_code == 200
