import time

import pytest

from scrollsense.analysis_queue import AnalysisQueue, Pacer
from scrollsense.domain import AnalysisRequest, VideoId
from scrollsense.scheduling import (CachedScheduler, LiveScheduler, QuotaExceeded, RunBudget,
                                    RunLimits)
from scrollsense.service import AnalysisService
from scrollsense.views import ViewerId

from .fakes import MemoryStore, instant_mock, no_wait

A, B, C = VideoId("aaaaaaaaaaa"), VideoId("bbbbbbbbbbb"), VideoId("ccccccccccc")
ANN, BOB = ViewerId("demo-ann"), ViewerId("demo-bob")


def stored_queue() -> AnalysisQueue:
    """A queue (workers not started) over a store that already holds A."""
    store = MemoryStore()
    service = AnalysisService(instant_mock(), store, time.time)
    service.run(AnalysisRequest(video=A), lambda stage: None)
    return AnalysisQueue(service, store, Pacer(0.0, time.monotonic, no_wait))


def test_budget_per_viewer_and_total() -> None:
    budget = RunBudget(RunLimits(per_viewer=1, total=2))
    budget.spend(ANN)
    assert not budget.has_room(ANN) and budget.has_room(BOB)
    budget.spend(BOB)
    with pytest.raises(QuotaExceeded):
        budget.check(ViewerId("demo-cat"))


def test_live_first_view_reruns_a_stored_short() -> None:
    queue = stored_queue()
    live = LiveScheduler(queue, RunBudget(RunLimits()))
    assert live.viewed(ANN, A, first=True) is True
    assert queue.state_of(A) == "queued"


def test_live_repeat_view_uses_the_cache() -> None:
    queue = stored_queue()
    assert LiveScheduler(queue, RunBudget(RunLimits())).viewed(ANN, A, first=False) is False


def test_live_over_budget_falls_back_to_the_cache() -> None:
    queue = stored_queue()
    live = LiveScheduler(queue, RunBudget(RunLimits(per_viewer=0)))
    assert live.viewed(ANN, A, first=True) is False
    assert live.viewed(ANN, B, first=True) is True   # never analysed: still queued


def test_live_paste_only_checks_the_budget() -> None:
    queue = stored_queue()
    LiveScheduler(queue, RunBudget(RunLimits())).added(ANN, B)
    assert queue.state_of(B) == "pending"
    with pytest.raises(QuotaExceeded):
        LiveScheduler(queue, RunBudget(RunLimits(per_viewer=0))).added(ANN, B)


def test_cached_paste_is_budgeted_and_views_are_not() -> None:
    queue = stored_queue()
    cached = CachedScheduler(queue, RunBudget(RunLimits(per_viewer=1)))
    cached.added(ANN, A)            # stored: free
    cached.added(ANN, B)
    with pytest.raises(QuotaExceeded):
        cached.added(ANN, C)
    assert cached.viewed(ANN, C, first=True) is True
