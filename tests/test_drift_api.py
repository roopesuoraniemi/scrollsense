import time
from pathlib import Path

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from scrollsense.analysis_queue import AnalysisQueue, Pacer
from scrollsense.auth import BearerToken
from scrollsense.drift.core import DriftConfig, DriftDetector
from scrollsense.drift_api import DriftApi, FeedObserver, ViewerDrift
from scrollsense.intake import ViewerExtras, ViewIntake
from scrollsense.service import AnalysisService
from scrollsense.store import JsonFileStore
from scrollsense.viewlog import JsonlViewLog
from scrollsense.views_api import ViewerReports, ViewsApi

from .fakes import NoNudges, instant_mock, no_wait
from .test_drift import NORM
from .test_views_api import NOW, TOKEN, batch, wait_scored

CONFIG = DriftConfig(window=4)
VIDEOS = [f"vid{i:08d}" for i in range(6)]


def routers(tmp_path: Path) -> list[APIRouter]:
    store = JsonFileStore(tmp_path / "clips")
    log = JsonlViewLog(tmp_path / "views")
    queue = AnalysisQueue(AnalysisService(instant_mock(), store, time.time), store,
                          Pacer(0.0, time.monotonic, no_wait))
    queue.start(2)
    drift = ViewerDrift(FeedObserver(log, store), DriftDetector(CONFIG, NORM))
    return [ViewsApi(ViewIntake(log, queue, ViewerExtras(NoNudges())),
                     ViewerReports(log, store, queue)).router(),
            DriftApi(drift).router()]


def app(tmp_path: Path, token: str | None) -> FastAPI:
    built = FastAPI()
    for router in routers(tmp_path):
        built.include_router(router, dependencies=[Depends(BearerToken(token))] if token else [])
    return built


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(app(tmp_path, None))


def test_drift_report_shape_while_learning(client: TestClient) -> None:
    client.post("/api/views", json=batch("patient-01", VIDEOS[0]))
    wait_scored(client, "patient-01")
    body = client.get("/api/viewers/patient-01/drift").json()
    assert body["level"] == "learning" and body["note"] == "Collecting recent Shorts: 1/2 analysed"
    assert body["config"] == CONFIG.model_dump() and body["pending"] == 0
    assert body["affect_baseline"] == NORM.model_dump() and "baseline" not in body
    assert len(body["timeline"]) == 1 and "clinical" not in body
    assert "safety" not in body


def test_judged_report_has_a_level(client: TestClient) -> None:
    client.post("/api/views", json=batch("patient-01", *VIDEOS))
    wait_scored(client, "patient-01")
    body = client.get("/api/viewers/patient-01/drift").json()
    assert body["level"] in {"normal", "watch", "warning"} and len(body["timeline"]) == 6
    assert body["recent"]["n"] == 4


def test_timeline_and_affect_rows_shape(client: TestClient) -> None:
    client.post("/api/views", json=batch("patient-01", *VIDEOS))
    wait_scored(client, "patient-01")
    body = client.get("/api/viewers/patient-01/drift").json()
    assert set(body["timeline"][0]) == {"video_id", "seen_at", "score", "level"}
    assert [f["name"] for f in body["features"]] == ["valence", "arousal"]


def test_baseline_routes_are_gone_and_bad_viewers_are_400(client: TestClient) -> None:
    assert client.get("/api/viewers/Bob/drift").status_code == 400
    assert client.post("/api/viewers/patient-01/baseline").status_code in {404, 405}
    assert client.delete("/api/viewers/patient-01/baseline").status_code in {404, 405}


def test_drift_routes_need_the_token(tmp_path: Path) -> None:
    client = TestClient(app(tmp_path, TOKEN))
    assert client.get("/api/viewers/patient-01/drift").status_code == 401
    auth = {"Authorization": f"Bearer {TOKEN}"}
    assert client.get("/api/viewers/patient-01/drift", headers=auth).status_code == 200
