"""HTTP adapter for the phone prototype: view batches in, feeds out."""
from operator import attrgetter
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Response

from .analysis_queue import AnalysisQueue, QueueStatus
from .api import ClipSummary
from .intake import Receipt, ViewIntake
from .ports import AnalysisStore, ViewLog
from .schemas import Frozen
from .views import EVER, ViewBatch, ViewerId, ViewEvent

ClipState = Literal["scored", "queued", "failed", "pending"]


class ViewerSummary(Frozen):
    viewer: str
    events: int
    last_seen: float | None


class FeedItem(Frozen):
    """One shown event and what is known about its clip so far."""

    event: ViewEvent
    state: ClipState
    error: str | None
    clip: ClipSummary | None


class ViewerReports:
    """Read side: joins the view log with stored analyses and the queue's state."""

    def __init__(self, log: ViewLog, store: AnalysisStore, queue: AnalysisQueue) -> None:
        self.__log = log
        self.__store = store
        self.__queue = queue

    def viewers(self) -> tuple[ViewerSummary, ...]:
        return tuple(self.__summary(v) for v in self.__log.viewers())

    def feed(self, viewer: ViewerId, limit: int) -> tuple[FeedItem, ...]:
        """Up to `limit` most recent events, newest first."""
        events = sorted(self.__log.between(viewer, EVER), key=attrgetter("seen_at"), reverse=True)
        return tuple(self.__item(e) for e in events[:limit])

    def queue_status(self) -> QueueStatus:
        return self.__queue.status()

    def __summary(self, viewer: ViewerId) -> ViewerSummary:
        events = self.__log.between(viewer, EVER)
        return ViewerSummary(viewer=viewer.value, events=len(events),
                             last_seen=max((e.seen_at for e in events), default=None))

    def __item(self, event: ViewEvent) -> FeedItem:
        """A video being (re-)analysed or failed shows that state, never an older stored result."""
        state = self.__queue.state_of(event.video)
        analysis = self.__store.load(event.video) if state == "pending" else None
        if analysis is not None:
            return FeedItem(event=event, state="scored", error=None,
                            clip=ClipSummary.of(analysis))
        failure = self.__queue.failure(event.video)
        return FeedItem(event=event, state=state,
                        error=failure.error if failure else None, clip=None)

class ViewsApi:
    """Routes under /api for the phone userscript and the dashboard."""

    def __init__(self, intake: ViewIntake, reports: ViewerReports) -> None:
        self.__intake = intake
        self.__reports = reports

    def router(self) -> APIRouter:
        router = APIRouter(prefix="/api")
        router.add_api_route("/views", self.post_views, methods=["POST"], status_code=202)
        router.add_api_route("/viewers", self.viewers, methods=["GET"])
        router.add_api_route("/viewers/{viewer}/feed", self.feed, methods=["GET"])
        router.add_api_route("/viewers/{viewer}", self.erase, methods=["DELETE"], status_code=204,
                             response_class=Response)
        router.add_api_route("/queue", self.queue, methods=["GET"])
        return router

    def post_views(self, batch: ViewBatch) -> Receipt:
        try:
            return self.__intake.record(batch)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    def viewers(self) -> tuple[ViewerSummary, ...]:
        return self.__reports.viewers()

    def feed(self, viewer: str,
             limit: Annotated[int, Query(ge=1, le=500)] = 50) -> tuple[FeedItem, ...]:
        return self.__reports.feed(self.__viewer(viewer), limit)

    def erase(self, viewer: str) -> Response:
        """GDPR erasure of the view log. Shared clip analyses hold no viewer data and stay."""
        self.__intake.erase(self.__viewer(viewer))
        return Response(status_code=204)

    def queue(self) -> QueueStatus:
        return self.__reports.queue_status()

    @staticmethod
    def __viewer(text: str) -> ViewerId:
        try:
            return ViewerId(text)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
