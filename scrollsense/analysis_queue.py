"""Background analysis of viewed videos: a deduplicating, dwell-prioritised worker queue."""
import time
from collections import deque
from threading import Condition, Lock, Thread
from typing import Callable, Literal

from .domain import AnalysisRequest, Stage, VideoId
from .ports import AnalysisStore
from .schemas import Frozen
from .service import AnalysisService

QueueState = Literal["queued", "failed", "pending"]
RECENT_FAILURES = 10


class Pacer:
    """Spaces starts at least `interval_s` apart across all threads that share it.

    `clock` and `sleep` are injected so tests need not wait.
    """

    def __init__(self, interval_s: float, clock: Callable[[], float],
                 sleep: Callable[[float], None]) -> None:
        self.__interval_s = interval_s
        self.__clock = clock
        self.__sleep = sleep
        self.__next = -float("inf")
        self.__lock = Lock()

    @classmethod
    def per_minute(cls, rpm: float) -> "Pacer":
        """At most `rpm` starts per minute on the real clock; `rpm <= 0` means unpaced."""
        return cls(60.0 / rpm if rpm > 0 else 0.0, time.monotonic, time.sleep)

    def wait_turn(self) -> None:
        """Block until this caller may start; reserves the slot before sleeping."""
        with self.__lock:
            start = max(self.__clock(), self.__next)
            self.__next = start + self.__interval_s
        self.__sleep(max(0.0, start - self.__clock()))


class Failure(Frozen):
    """A video whose background analysis raised an error."""

    video_id: str
    error: str


class QueueStatus(Frozen):
    """Snapshot of the background analysis queue."""

    depth: int
    in_flight: int
    done: int
    failed: int
    recent_failures: tuple[Failure, ...]


class AnalysisQueue:
    """Analyses each video at most once per process, on `start`-ed daemon worker threads.

    Watched or live Shorts (`priority=True`) run ahead of rapid skips (`priority=False`);
    if a skipped Short is later watched while still waiting, it is promoted in place.
    A video already stored, queued, in flight or failed is never enqueued twice.
    """

    def __init__(self, service: AnalysisService, store: AnalysisStore, pacer: Pacer) -> None:
        self.__service = service
        self.__store = store
        self.__pacer = pacer
        self.__watched: deque[VideoId] = deque()
        self.__skips: deque[VideoId] = deque()
        self.__in_flight: set[VideoId] = set()
        self.__failures: dict[VideoId, Failure] = {}
        self.__done = 0
        self.__ready = Condition()

    def start(self, workers: int) -> None:
        """Launch `workers` daemon threads. Call once."""
        for index in range(workers):
            Thread(target=self.__work, name=f"analysis-{index}", daemon=True).start()

    def enqueue_if_new(self, video: VideoId, priority: bool = True) -> bool:
        """Atomically queue `video` unless it is stored, queued, in flight or failed.

        Promotes an already-waiting skip when `priority` is True, still returning False
        because no second queue entry was added. Reads the store, so it may touch disk.
        """
        if self.__store.load(video) is not None:
            return False
        with self.__ready:
            return self.__admit(video, priority)

    def state_of(self, video: VideoId) -> QueueState:
        """`queued` while waiting or in flight, `failed` after an error, else `pending`."""
        with self.__ready:
            if video in self.__failures:
                return "failed"
            return "queued" if self.__known(video) else "pending"

    def failure(self, video: VideoId) -> Failure | None:
        """Recorded failure for `video`, or None."""
        with self.__ready:
            return self.__failures.get(video)

    def status(self) -> QueueStatus:
        """Current queue depth, active workers, completed count, and recent failures."""
        with self.__ready:
            failures = tuple(self.__failures.values())
            waiting = len(self.__watched) + len(self.__skips)
            return QueueStatus(depth=waiting, in_flight=len(self.__in_flight),
                               done=self.__done, failed=len(failures),
                               recent_failures=failures[-RECENT_FAILURES:])

    def __admit(self, video: VideoId, priority: bool) -> bool:
        if video in self.__skips and priority:
            self.__skips.remove(video)
            self.__watched.append(video)
            return False
        if self.__known(video):
            return False
        (self.__watched if priority else self.__skips).append(video)
        self.__ready.notify()
        return True

    def __known(self, video: VideoId) -> bool:
        waiting = video in self.__watched or video in self.__skips
        return waiting or video in self.__in_flight or video in self.__failures

    def __work(self) -> None:
        while True:
            video = self.__take()
            self.__pacer.wait_turn()
            self.__finish(video, self.__attempt(video))

    def __take(self) -> VideoId:
        with self.__ready:
            self.__ready.wait_for(self.__has_waiting)
            lane = self.__watched if self.__watched else self.__skips
            video = lane.popleft()
            self.__in_flight.add(video)
            return video

    def __has_waiting(self) -> bool:
        return bool(self.__watched or self.__skips)

    def __attempt(self, video: VideoId) -> str | None:
        try:
            self.__service.run(AnalysisRequest(video=video), self.__quiet)
        except Exception as error:  # a worker thread must record, never die silently
            return f"{type(error).__name__}: {error}"
        return None

    def __finish(self, video: VideoId, error: str | None) -> None:
        with self.__ready:
            self.__in_flight.discard(video)
            if error is None:
                self.__done += 1
            else:
                self.__failures[video] = Failure(video_id=video.value, error=error)

    @staticmethod
    def __quiet(stage: Stage) -> None:
        """Queue workers report through `status`, not per stage."""
