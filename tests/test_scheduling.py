import time

from scrollsense.analysis_queue import AnalysisQueue, Pacer
from scrollsense.domain import AnalysisRequest, VideoId
from scrollsense.scheduling import CachedScheduler, LiveScheduler
from scrollsense.service import AnalysisService
from scrollsense.views import ViewerId

from .fakes import MemoryStore, instant_mock, no_wait

A, B = VideoId("aaaaaaaaaaa"), VideoId("bbbbbbbbbbb")
ANN = ViewerId("demo-ann")


def stored_queue() -> AnalysisQueue:
    """A queue (workers not started) over a store that already holds A."""
    store = MemoryStore()
    service = AnalysisService(instant_mock(), store, time.time)
    service.run(AnalysisRequest(video=A), lambda stage: None)
    return AnalysisQueue(service, store, Pacer(0.0, time.monotonic, no_wait))


def test_live_first_view_reruns_a_stored_short() -> None:
    queue = stored_queue()
    assert LiveScheduler(queue).viewed(ANN, A, first=True) is True
    assert queue.state_of(A) == "queued"


def test_live_repeat_view_uses_the_cache_and_analyses_only_new_shorts() -> None:
    queue = stored_queue()
    assert LiveScheduler(queue).viewed(ANN, A, first=False) is False
    assert LiveScheduler(queue).viewed(ANN, B, first=False) is True


def test_live_paste_waits_for_the_view() -> None:
    queue = stored_queue()
    LiveScheduler(queue).added(ANN, B)
    assert queue.state_of(B) == "pending"


def test_cached_analyses_each_short_once() -> None:
    queue = stored_queue()
    cached = CachedScheduler(queue)
    assert cached.viewed(ANN, A, first=True) is False
    cached.added(ANN, B)
    assert queue.state_of(B) == "queued"
