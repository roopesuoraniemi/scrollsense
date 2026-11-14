import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scrollsense.api import Api, ClipCatalog
from scrollsense.domain import AnalysisRequest, VideoId
from scrollsense.service import AnalysisService
from scrollsense.store import JsonFileStore

from .fakes import instant_mock

ID = "dQw4w9WgXcQ"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    store = JsonFileStore(tmp_path)
    service = AnalysisService(instant_mock(), store, time.time)
    service.run(AnalysisRequest(video=VideoId(ID)), lambda stage: None)
    app = FastAPI()
    app.include_router(Api(service, ClipCatalog(store)).router())
    return TestClient(app)


def test_meta_names_the_analyser(client: TestClient) -> None:
    assert client.get("/api/meta").json() == {"analyser": {"name": "mock", "mock": True}, "live": False}


def test_clip_detail_and_summary_agree(client: TestClient) -> None:
    detail = client.get(f"/api/clips/{ID}").json()
    assert detail["package"]["title"].startswith("[MOCK]") and "intended_meaning" in detail["package"]
    assert 1 <= detail["valence"] <= 5
    [summary] = client.get("/api/clips").json()
    assert set(summary) == {"id", "title", "valence", "arousal", "stance"}
    assert (summary["id"], summary["valence"]) == (ID, detail["valence"])


def test_bad_and_unknown_clips(client: TestClient) -> None:
    assert client.get("/api/clips/nope").status_code == 400
    assert client.get("/api/clips/aaaaaaaaaaa").status_code == 404
