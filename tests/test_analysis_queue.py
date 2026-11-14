import time

from scrollsense.analysis_queue import AnalysisQueue, Pacer, QueueStatus
from scrollsense.domain import AnalysisRequest, VideoId
from scrollsense.ports import ContentAnalyser
from scrollsense.service import AnalysisService

from .fakes import FailingDescribeAnalyser, MemoryStore, instant_mock, no_wait

A, B = VideoId("aaaaaaaaaaa"), VideoId("bbbbbbbbbbb")


def queue_with(analyser: ContentAnalyser, store: MemoryStore) -> AnalysisQueue:
    service = AnalysisService(analyser, store, time.time)
    return AnalysisQueue(service, store, Pacer(0.0, time.monotonic, no_wait))


def drain(queue: AnalysisQueue) -> QueueStatus:
    for _ in range(200):
        status = queue.status()
        if status.depth == 0 and status.in_flight == 0:
            return status
        time.sleep(0.01)
    raise AssertionError("queue did not drain")


def test_never_enqueues_a_video_twice_or_one_already_stored() -> None:
    store = MemoryStore()
    AnalysisService(instant_mock(), store, time.time).run(AnalysisRequest(video=B), lambda stage: None)
    queue = queue_with(instant_mock(), store)
    assert [queue.enqueue_if_new(v) for v in (A, A, B)] == [True, False, False]
    assert queue.state_of(A) == "queued" and queue.status().depth == 1
    queue.start(2)
    assert drain(queue).done == 1 and store.load(A) is not None
    assert queue.enqueue_if_new(A) is False


def test_failure_is_recorded_and_not_retried() -> None:
    queue = queue_with(FailingDescribeAnalyser(delay_s=0), MemoryStore())
    queue.start(1)
    queue.enqueue_if_new(A)
    status = drain(queue)
    assert (status.failed, status.done) == (1, 0)
    assert status.recent_failures[0].error == "PermissionError: video aaaaaaaaaaa is private"
    assert queue.state_of(A) == "failed" and queue.enqueue_if_new(A) is False
    assert queue.state_of(B) == "pending"


def test_pacer_spaces_starts() -> None:
    now = [100.0]
    sleeps: list[float] = []
    pacer = Pacer(3.0, lambda: now[0], sleeps.append)
    for _ in range(3):
        pacer.wait_turn()
    assert sleeps == [0.0, 3.0, 6.0]
    assert Pacer.per_minute(0) is not None


def test_enqueue_fresh_reruns_a_stored_video() -> None:
    store = MemoryStore()
    AnalysisService(instant_mock(), store, lambda: 1.0).run(AnalysisRequest(video=A), lambda stage: None)
    queue = queue_with(instant_mock(), store)
    assert [queue.enqueue_fresh(A), queue.enqueue_fresh(A)] == [True, False]
    assert queue.state_of(A) == "queued"
    queue.start(1)
    drain(queue)
    assert store.load(A).created > 1.0


def test_enqueue_fresh_retries_a_failure() -> None:
    queue = queue_with(FailingDescribeAnalyser(delay_s=0), MemoryStore())
    queue.start(1)
    queue.enqueue_if_new(A)
    drain(queue)
    assert queue.enqueue_fresh(A) is True
