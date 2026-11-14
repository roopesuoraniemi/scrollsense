"""When a viewed or pasted Short is analysed: from the cache (each video once), or live (a fresh
Gemini run on each viewer's first view). The analysis queue's pacer is the only limit on Gemini:
at most SCROLLSENSE_RPM analyses start per minute (default 20)."""
from abc import ABC, abstractmethod

from .analysis_queue import AnalysisQueue
from .domain import VideoId
from .views import ViewerId


class AnalysisScheduler(ABC):
    """Decides which analyses a view or a pasted Short starts."""

    @abstractmethod
    def viewed(self, viewer: ViewerId, video: VideoId, first: bool) -> bool:
        """`viewer` was shown `video` (`first`: never before). Returns whether a run was queued."""

    @abstractmethod
    def added(self, viewer: ViewerId, video: VideoId) -> None:
        """`viewer` pasted `video` to watch next."""


class CachedScheduler(AnalysisScheduler):
    """Each video is analysed once and then served from the store. Pasted Shorts are analysed
    ahead of their view."""

    def __init__(self, queue: AnalysisQueue) -> None:
        self.__queue = queue

    def viewed(self, viewer: ViewerId, video: VideoId, first: bool) -> bool:
        return self.__queue.enqueue_if_new(video)

    def added(self, viewer: ViewerId, video: VideoId) -> None:
        self.__queue.enqueue_if_new(video)


class LiveScheduler(AnalysisScheduler):
    """Every viewer's first view of a Short starts a fresh Gemini run, so results arrive after the
    video, as they would for a Short nobody has analysed. A repeat view analyses only a Short not
    stored yet."""

    def __init__(self, queue: AnalysisQueue) -> None:
        self.__queue = queue

    def viewed(self, viewer: ViewerId, video: VideoId, first: bool) -> bool:
        return self.__queue.enqueue_fresh(video) if first else self.__queue.enqueue_if_new(video)

    def added(self, viewer: ViewerId, video: VideoId) -> None:
        """The run itself starts when the Short is viewed."""
