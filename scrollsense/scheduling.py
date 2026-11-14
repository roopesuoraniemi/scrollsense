"""When a viewed or pasted Short is analysed: from the cache (each video once), or live (a fresh
Gemini run on each viewer's first view), within a budget of runs per viewer and per server run."""
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Mapping
from threading import Lock

from pydantic import Field

from .analysis_queue import AnalysisQueue
from .domain import VideoId
from .schemas import Frozen
from .views import ViewerId


class RunLimits(Frozen):
    """At most `per_viewer` budgeted Gemini runs per viewer and `total` per server run."""

    per_viewer: int = Field(default=40, ge=0)
    total: int = Field(default=400, ge=0)

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "RunLimits":
        return cls(per_viewer=int(env.get("SCROLLSENSE_RUNS_PER_VIEWER", "40")),
                   total=int(env.get("SCROLLSENSE_RUNS_TOTAL", "400")))


class QuotaExceeded(Exception):
    pass


class RunBudget:
    """Counts runs against `RunLimits`. Kept in memory, so a restart starts it again; erasing a
    viewer does not refund it."""

    def __init__(self, limits: RunLimits) -> None:
        self.__limits = limits
        self.__spent: Counter[str] = Counter()
        self.__lock = Lock()

    def check(self, viewer: ViewerId) -> None:
        """Raises QuotaExceeded if `viewer` may not start another run."""
        with self.__lock:
            if self.__spent.total() >= self.__limits.total:
                raise QuotaExceeded("The demo has used up its Gemini runs for now")
            if self.__spent[viewer.value] >= self.__limits.per_viewer:
                raise QuotaExceeded(f"Up to {self.__limits.per_viewer} Gemini runs per demo session")

    def has_room(self, viewer: ViewerId) -> bool:
        try:
            self.check(viewer)
        except QuotaExceeded:
            return False
        return True

    def spend(self, viewer: ViewerId) -> None:
        with self.__lock:
            self.__spent[viewer.value] += 1


class AnalysisScheduler(ABC):
    """Decides which analyses a view or a pasted Short starts."""

    @abstractmethod
    def viewed(self, viewer: ViewerId, video: VideoId, first: bool) -> bool:
        """`viewer` was shown `video` (`first`: never before). Returns whether a run was queued."""

    @abstractmethod
    def added(self, viewer: ViewerId, video: VideoId) -> None:
        """`viewer` pasted `video` to watch next. Raises QuotaExceeded."""


class CachedScheduler(AnalysisScheduler):
    """Each video is analysed once and then served from the store. Pasted Shorts are analysed
    ahead of their view, within the budget; views from the phone are not budgeted."""

    def __init__(self, queue: AnalysisQueue, budget: RunBudget) -> None:
        self.__queue = queue
        self.__budget = budget

    def viewed(self, viewer: ViewerId, video: VideoId, first: bool) -> bool:
        return self.__queue.enqueue_if_new(video)

    def added(self, viewer: ViewerId, video: VideoId) -> None:
        self.__budget.check(viewer)
        if self.__queue.enqueue_if_new(video):
            self.__budget.spend(viewer)


class LiveScheduler(AnalysisScheduler):
    """Every viewer's first view of a Short starts a fresh Gemini run, so results arrive after the
    video, as they would for a Short nobody has analysed. Over budget it falls back to the cache."""

    def __init__(self, queue: AnalysisQueue, budget: RunBudget) -> None:
        self.__queue = queue
        self.__budget = budget

    def viewed(self, viewer: ViewerId, video: VideoId, first: bool) -> bool:
        if first and self.__budget.has_room(viewer) and self.__queue.enqueue_fresh(video):
            self.__budget.spend(viewer)
            return True
        return self.__queue.enqueue_if_new(video)

    def added(self, viewer: ViewerId, video: VideoId) -> None:
        self.__budget.check(viewer)   # the run itself starts when the Short is viewed
