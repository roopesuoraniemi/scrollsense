"""Accepting batches of view events: validate, dedupe against the log, record, queue analysis,
and offer any nudge that is due."""
from collections.abc import Sequence
from dataclasses import dataclass
from threading import Lock

from .nudge import NudgeCard
from .ports import Nudger, ViewLog
from .scheduling import AnalysisScheduler
from .schemas import Frozen
from .views import EVER, Rejection, ViewBatch, ViewerId, ViewEvent, fresh, parse_events


class Receipt(Frozen):
    """`accepted` new events were logged, `duplicates` repeated known ones, and `queued`
    videos were newly sent for analysis. `nudge` is the viewer's open card, if any."""

    accepted: int
    duplicates: int
    queued: int
    rejected: tuple[Rejection, ...]
    nudge: NudgeCard | None = None


@dataclass(frozen=True)
class ViewerExtras:
    """Per-viewer state kept beside the view log: erased with it, and `nudges` is asked for a
    card after each batch."""

    nudges: Nudger


class ViewIntake:
    """Records client batches. Only `shorts` events are analysed (as `scheduler` decides); the
    rest are just logged."""

    def __init__(self, log: ViewLog, scheduler: AnalysisScheduler, extras: ViewerExtras) -> None:
        self.__log = log
        self.__scheduler = scheduler
        self.__extras = extras
        self.__lock = Lock()

    def record(self, batch: ViewBatch) -> Receipt:
        """Atomically log the batch's new events and queue their videos; reports what happened.
        Then issues a nudge if one is due (see `Nudger.issue_if_due`) and returns the open one.

        Raises ValueError if `batch.viewer` is not a valid pseudonym. Idempotent per event id,
        so a client may resend a batch whose response it never received.
        """
        viewer = ViewerId(batch.viewer)
        parsed = parse_events(viewer, batch.events)
        with self.__lock:
            logged = self.__log.between(viewer, EVER)
            new = fresh(logged, parsed.events)
            self.__log.append(new)
        queued = self.__schedule(viewer, logged, new)
        return Receipt(accepted=len(new), duplicates=len(parsed.events) - len(new),
                       queued=queued, rejected=parsed.rejected,
                       nudge=self.__extras.nudges.issue_if_due(viewer))

    def __schedule(self, viewer: ViewerId, logged: Sequence[ViewEvent],
                   new: Sequence[ViewEvent]) -> int:
        seen = {e.video_id for e in logged}
        queued = 0
        for event in (e for e in new if e.surface == "shorts"):
            queued += self.__scheduler.viewed(viewer, event.video, event.video_id not in seen)
            seen.add(event.video_id)
        return queued

    def erase(self, viewer: ViewerId) -> None:
        """Delete `viewer`'s view log and nudges (GDPR erasure); waits for any batch
        being recorded. Shared clip analyses are kept: they describe public videos, not the viewer."""
        with self.__lock:
            self.__log.erase(viewer)
            self.__extras.nudges.erase(viewer)
