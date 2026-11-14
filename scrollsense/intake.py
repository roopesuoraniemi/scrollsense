"""Accepting batches of view events: validate, dedupe against the log, record, queue analysis."""
from threading import Lock

from .analysis_queue import AnalysisQueue
from .ports import BaselineStore, ViewLog
from .schemas import Frozen
from .views import EVER, Rejection, ViewBatch, ViewerId, fresh, parse_events


class Receipt(Frozen):
    """`accepted` new events were logged, `duplicates` repeated known ones, and `queued`
    videos were newly sent for analysis."""

    accepted: int
    duplicates: int
    queued: int
    rejected: tuple[Rejection, ...]


class ViewIntake:
    """Records client batches. Only `shorts` events are analysed; the rest are just logged."""

    def __init__(self, log: ViewLog, queue: AnalysisQueue, baselines: BaselineStore) -> None:
        self.__log = log
        self.__queue = queue
        self.__baselines = baselines
        self.__lock = Lock()

    def record(self, batch: ViewBatch) -> Receipt:
        """Atomically log the batch's new events and queue their videos; reports what happened.

        Raises ValueError if `batch.viewer` is not a valid pseudonym. Idempotent per event id,
        so a client may resend a batch whose response it never received.
        """
        viewer = ViewerId(batch.viewer)
        parsed = parse_events(viewer, batch.events)
        with self.__lock:
            new = fresh(self.__log.between(viewer, EVER), parsed.events)
            self.__log.append(new)
        queued = [self.__queue.enqueue_if_new(e.video) for e in new if e.surface == "shorts"]
        return Receipt(accepted=len(new), duplicates=len(parsed.events) - len(new),
                       queued=sum(queued), rejected=parsed.rejected)

    def erase(self, viewer: ViewerId) -> None:
        """Delete `viewer`'s view log and baseline mark (GDPR erasure); waits for any batch
        being recorded. Shared clip analyses are kept: they describe public videos, not the viewer."""
        with self.__lock:
            self.__log.erase(viewer)
            self.__baselines.clear(viewer)
