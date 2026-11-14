import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scrollsense.api import Api, ClipCatalog
from scrollsense.jobs import JobBoard
from scrollsense.service import AnalysisService
from scrollsense.store import JsonFileStore

from .fakes import instant_mock


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    store = JsonFileStore(tmp_path)
    service = AnalysisService(instant_mock(), store, time.time)
    app = FastAPI()
    app.include_router(Api(service, ClipCatalog(store, None), JobBoard(service)).router())
    return TestClient(app)


def wait_for(client: TestClient, job_id: str) -> dict:
    for _ in range(100):
        status = client.get(f"/api/jobs/{job_id}").json()
        if status["stage"] in ("done", "error"):
            return status
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_meta_lists_nine_criteria(client: TestClient) -> None:
    meta = client.get("/api/meta").json()
    assert len(meta["criteria"]) == 9 and meta["analyser"]["mock"] is True


def test_analyse_then_read_back(client: TestClient) -> None:
    accepted = client.post("/api/analyze", json={"url": "https://youtu.be/dQw4w9WgXcQ"}).json()
    assert wait_for(client, accepted["job"]) == {"id": "dQw4w9WgXcQ", "stage": "done", "error": None}
    detail = client.get("/api/clips/dQw4w9WgXcQ").json()
    assert detail["package"]["title"].startswith("[MOCK]") and 0 <= detail["load"] <= 27
    assert 1 <= detail["valence"] <= 5 and "intended_meaning" in detail["package"]
    summaries = client.get("/api/clips").json()
    assert [c["id"] for c in summaries] == ["dQw4w9WgXcQ"] and summaries[0]["valence"] == detail["valence"]


def test_bad_url_is_400(client: TestClient) -> None:
    assert client.post("/api/analyze", json={"url": "nope"}).status_code == 400


def test_unknown_clip_and_job_are_404(client: TestClient) -> None:
    assert client.get("/api/clips/aaaaaaaaaaa").status_code == 404
    assert client.get("/api/jobs/nope").status_code == 404
