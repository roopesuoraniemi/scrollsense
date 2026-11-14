"""Accepting batches of view events: validate, dedupe, record, track live Short, queue analysis."""
from threading import Lock

from .analysis_queue import AnalysisQueue
from .domain import VideoId
from .ports import ViewLog
from .schemas import Frozen
from .views import (EVER, ActiveWatch, Rejection, ViewBatch, ViewerId, ViewEvent, fresh,
                    parse_events)

ACTIVE_TTL_S = 300.0
MIN_PRIORITY_DWELL_S = 2.0


class Receipt(Frozen):
    """`accepted` new events were logged, `duplicates` repeated known ones, and `queued`
    videos were newly sent for analysis."""

    accepted: int
    duplicates: int
    queued: int
    rejected: tuple[Rejection, ...]


class LiveWatchers:
    """Thread-safe in-memory record of which Short each viewer currently has on screen.

    Kept out of `ViewLog` because an open view has no final dwell count yet and must
    never pollute persistent JSONL history if a tab closes ungracefully.
    """

    def __init__(self) -> None:
        self.__active: dict[str, ActiveWatch] = {}
        self.__lock = Lock()

    def update(self, viewer: ViewerId, batch: ViewBatch,
               recorded: tuple[ViewEvent, ...]) -> ActiveWatch | None:
        """Apply `batch`'s live state and return any newly opened `ActiveWatch`."""
        with self.__lock:
            return self.__apply(viewer.value, batch, recorded)

    def current(self, viewer: ViewerId, now: float | None = None) -> ActiveWatch | None:
        """The viewer's active Short if not expired at `now`, else None."""
        with self.__lock:
            watch = self.__active.get(viewer.value)
        if watch is None or (now is not None and now - watch.started_at > ACTIVE_TTL_S):
            return None
        return watch

    def viewers(self, now: float | None = None) -> tuple[ViewerId, ...]:
        """Sorted pseudonyms with a non-expired active Short."""
        with self.__lock:
            items = tuple(self.__active.items())
        names = [k for k, w in items if now is None or now - w.started_at <= ACTIVE_TTL_S]
        return tuple(sorted((ViewerId(n) for n in names), key=str))

    def clear(self, viewer: ViewerId) -> None:
        """Forget any active Short for `viewer`."""
        with self.__lock:
            self.__active.pop(viewer.value, None)

    def __apply(self, viewer: str, batch: ViewBatch,
                recorded: tuple[ViewEvent, ...]) -> ActiveWatch | None:
        if batch.paused:
            self.__active.pop(viewer, None)
            return None
        if batch.watching is not None:
            self.__active[viewer] = batch.watching
            return batch.watching
        if viewer in self.__active and self.__closed(self.__active[viewer], recorded):
            self.__active.pop(viewer, None)
        return None

    @staticmethod
    def __closed(watch: ActiveWatch, recorded: tuple[ViewEvent, ...]) -> bool:
        return any(e.video_id == watch.video_id for e in recorded)


class ViewIntake:
    """Records client batches. Only `shorts` events are analysed; the rest are just logged."""

    def __init__(self, log: ViewLog, queue: AnalysisQueue,
                 live: LiveWatchers | None = None) -> None:
        self.__log = log
        self.__queue = queue
        self.__live = live if live is not None else LiveWatchers()
        self.__lock = Lock()

    def record(self, batch: ViewBatch) -> Receipt:
        """Atomically log the batch's new events, update live watch state, and queue videos.

        Raises ValueError if `batch.viewer` is not a valid pseudonym. Idempotent per event id.
        """
        viewer = ViewerId(batch.viewer)
        parsed = parse_events(viewer, batch.events)
        new = self.__append_fresh(viewer, parsed.events)
        watch = self.__live.update(viewer, batch, new)
        queued = self.__enqueue_all(new, watch)
        return Receipt(accepted=len(new), duplicates=len(parsed.events) - len(new),
                       queued=queued, rejected=parsed.rejected)

    def erase(self, viewer: ViewerId) -> None:
        """Delete `viewer`'s view log and active state; waits for any batch being recorded."""
        with self.__lock:
            self.__log.erase(viewer)
        self.__live.clear(viewer)

    def __append_fresh(self, viewer: ViewerId,
                       events: tuple[ViewEvent, ...]) -> tuple[ViewEvent, ...]:
        with self.__lock:
            new = fresh(self.__log.between(viewer, EVER), events)
            if new:
                self.__log.append(new)
            return new

    def __enqueue_all(self, events: tuple[ViewEvent, ...], watch: ActiveWatch | None) -> int:
        flags = [self.__enqueue_event(e) for e in events if e.surface == "shorts"]
        if watch is not None:
            flags.append(self.__queue.enqueue_if_new(VideoId(watch.video_id), priority=True))
        return sum(flags)

    def __enqueue_event(self, event: ViewEvent) -> bool:
        priority = event.dwell_s is None or event.dwell_s >= MIN_PRIORITY_DWELL_S
        return self.__queue.enqueue_if_new(event.video, priority=priority)
