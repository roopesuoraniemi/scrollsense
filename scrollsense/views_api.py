"""HTTP adapter for the phone prototype: view batches in, feeds and readouts out."""
from operator import attrgetter
from typing import Annotated, Callable, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import Field

from .analysis_queue import AnalysisQueue, QueueStatus
from .api import ClipSummary
from .domain import ClipAnalysis, VideoId
from .feed import Composition, Readout, Shift, composition, readout
from .intake import Receipt, ViewIntake
from .ports import AnalysisStore, ViewLog
from .schemas import Frozen
from .views import EVER, ViewBatch, ViewerId, ViewEvent, Window

ClipState = Literal["scored", "queued", "failed", "pending"]
DAY_S = 86_400.0


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


class Spans(Frozen):
    current: Window
    baseline: Window


class ReadoutQuery(Frozen):
    """Epoch-second bounds. Defaults: the last 24 h, against everything before it."""

    from_: float | None = Field(default=None, alias="from")
    to: float | None = None
    baseline_from: float = 0.0
    baseline_to: float | None = None
    control: str | None = None

    def spans(self, now: float) -> Spans:
        """Raises ValueError if a window would end before it starts."""
        end = self.to if self.to is not None else now
        start = self.from_ if self.from_ is not None else end - DAY_S
        baseline_end = self.baseline_to if self.baseline_to is not None else start
        return Spans(current=Window(start=start, end=end),
                     baseline=Window(start=self.baseline_from, end=baseline_end))


class ReadoutView(Frozen):
    windows: Spans
    current: Composition
    baseline: Composition
    control: Shift | None
    readout: Readout


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

    def readout(self, viewer: ViewerId, spans: Spans, control: ViewerId | None) -> ReadoutView:
        """`viewer` over `spans`, compared with `control` over the same spans if given."""
        shift = self.__shift(viewer, spans)
        control_shift = self.__shift(control, spans) if control is not None else None
        return ReadoutView(windows=spans, current=shift.current, baseline=shift.baseline,
                           control=control_shift,
                           readout=readout(shift.current, shift.baseline, control_shift))

    def queue_status(self) -> QueueStatus:
        return self.__queue.status()

    def __summary(self, viewer: ViewerId) -> ViewerSummary:
        events = self.__log.between(viewer, EVER)
        return ViewerSummary(viewer=viewer.value, events=len(events),
                             last_seen=max((e.seen_at for e in events), default=None))

    def __item(self, event: ViewEvent) -> FeedItem:
        analysis = self.__store.load(event.video)
        if analysis is not None:
            return FeedItem(event=event, state="scored", error=None,
                            clip=ClipSummary.of(analysis, None))
        failure = self.__queue.failure(event.video)
        return FeedItem(event=event, state=self.__queue.state_of(event.video),
                        error=failure.error if failure else None, clip=None)

    def __shift(self, viewer: ViewerId, spans: Spans) -> Shift:
        return Shift(current=self.__composition(viewer, spans.current),
                     baseline=self.__composition(viewer, spans.baseline))

    def __composition(self, viewer: ViewerId, window: Window) -> Composition:
        events = self.__log.between(viewer, window)
        return composition(events, self.__analyses({e.video_id for e in events}), window)

    def __analyses(self, video_ids: set[str]) -> dict[str, ClipAnalysis]:
        loaded = (self.__store.load(VideoId(v)) for v in video_ids)
        return {a.video_id: a for a in loaded if a is not None}


class ViewsApi:
    """Routes under /api for the phone userscript and the dashboard."""

    def __init__(self, intake: ViewIntake, reports: ViewerReports,
                 clock: Callable[[], float]) -> None:
        self.__intake = intake
        self.__reports = reports
        self.__clock = clock

    def router(self) -> APIRouter:
        router = APIRouter(prefix="/api")
        router.add_api_route("/views", self.post_views, methods=["POST"], status_code=202)
        router.add_api_route("/viewers", self.viewers, methods=["GET"])
        router.add_api_route("/viewers/{viewer}/feed", self.feed, methods=["GET"])
        router.add_api_route("/viewers/{viewer}/readout", self.readout, methods=["GET"])
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

    def readout(self, viewer: str, query: Annotated[ReadoutQuery, Query()]) -> ReadoutView:
        control = self.__viewer(query.control) if query.control else None
        try:
            spans = query.spans(self.__clock())
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return self.__reports.readout(self.__viewer(viewer), spans, control)

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
