import pytest

from scrollsense.domain import AnalysisRequest, Stage, VideoId
from scrollsense.service import AnalysisService

from .fakes import FailingDescribeAnalyser, MemoryStore, instant_mock

VIDEO = VideoId("dQw4w9WgXcQ")


def run(service: AnalysisService, request: AnalysisRequest) -> list[Stage]:
    stages: list[Stage] = []
    service.run(request, stages.append)
    return stages


def test_fresh_run_reports_stages_and_stores() -> None:
    store = MemoryStore()
    service = AnalysisService(instant_mock(), store, lambda: 42.0)
    assert run(service, AnalysisRequest(video=VIDEO)) == [Stage.DESCRIBING, Stage.SCORING]
    stored = store.load(VIDEO)
    assert stored is not None and stored.created == 42.0


def test_stored_video_is_skipped_unless_forced() -> None:
    service = AnalysisService(instant_mock(), MemoryStore(), lambda: 0.0)
    run(service, AnalysisRequest(video=VIDEO))
    assert run(service, AnalysisRequest(video=VIDEO)) == [Stage.CACHED]
    assert Stage.DESCRIBING in run(service, AnalysisRequest(video=VIDEO, force=True))


def test_describe_failure_propagates_and_stores_nothing() -> None:
    store = MemoryStore()
    with pytest.raises(PermissionError):
        AnalysisService(FailingDescribeAnalyser(delay_s=0), store, lambda: 0.0).run(
            AnalysisRequest(video=VIDEO), lambda stage: None)
    assert store.load(VIDEO) is None
