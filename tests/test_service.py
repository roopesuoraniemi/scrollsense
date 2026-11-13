from scrollsense.domain import AnalysisRequest, Stage, VideoId
from scrollsense.service import AnalysisService

from .fakes import FailingEmbedAnalyser, MemoryStore, instant_mock

VIDEO = VideoId("dQw4w9WgXcQ")


def run(service: AnalysisService, request: AnalysisRequest) -> list[Stage]:
    stages: list[Stage] = []
    service.run(request, stages.append)
    return stages


def test_fresh_run_reports_stages_and_stores() -> None:
    store = MemoryStore()
    service = AnalysisService(instant_mock(), store, lambda: 42.0)
    assert run(service, AnalysisRequest(video=VIDEO)) == [Stage.DESCRIBING, Stage.SCORING, Stage.EMBEDDING]
    stored = store.load(VIDEO)
    assert stored is not None and stored.created == 42.0 and stored.embedding.vector


def test_stored_video_is_skipped_unless_forced() -> None:
    service = AnalysisService(instant_mock(), MemoryStore(), lambda: 0.0)
    run(service, AnalysisRequest(video=VIDEO))
    assert run(service, AnalysisRequest(video=VIDEO)) == [Stage.CACHED]
    assert Stage.DESCRIBING in run(service, AnalysisRequest(video=VIDEO, force=True))


def test_embedding_failure_is_recorded_not_raised() -> None:
    store = MemoryStore()
    AnalysisService(FailingEmbedAnalyser(delay_s=0), store, lambda: 0.0).run(
        AnalysisRequest(video=VIDEO), lambda stage: None)
    stored = store.load(VIDEO)
    assert stored is not None and stored.embedding.vector is None
    assert stored.embedding.error == "ConnectionError: embedding service down"
