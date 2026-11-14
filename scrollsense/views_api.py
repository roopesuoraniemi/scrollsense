"""HTTP adapter for the phone prototype: view batches in, feeds and readouts out."""
from dataclasses import dataclass
from operator import attrgetter
from typing import Annotated, Callable, Literal, Mapping, Sequence

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import Field

from .analysis_queue import AnalysisQueue, QueueStatus
from .api import ClipSummary
from .domain import ClipAnalysis, Point, VideoId, semantic_points
from .feed import (Composition, EvidenceItem, Readout, Shift, TrajectoryPoint, composition,
                   evidence_items, readout, trajectory)
from .intake import LiveWatchers, Receipt, ViewIntake
from .loop import LoopGuidance, guidance
from .ports import AnalysisStore, ViewLog
from .schemas import Frozen
from .views import EVER, ViewBatch, ViewerId, ViewEvent, Window

ClipState = Literal["scored", "queued", "failed", "pending"]
DAY_S = 86_400.0


class ViewerSummary(Frozen):
    """One known viewer, their logged event count, and any Short currently open."""

    viewer: str
    events: int
    last_seen: float | None
    watching: str | None = None


class FeedItem(Frozen):
    """One shown event and what is known about its clip so far."""

    event: ViewEvent
    state: ClipState
    error: str | None
    clip: ClipSummary | None
    live: bool = False


class Spans(Frozen):
    """Comparison windows in epoch seconds."""

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
    """Complete longitudinal readout, supporting evidence, trajectory, and closed-loop view."""

    windows: Spans
    current: Composition
    baseline: Composition
    control: Shift | None
    readout: Readout
    evidence: tuple[EvidenceItem, ...]
    trajectory: tuple[TrajectoryPoint, ...]
    guidance: LoopGuidance


@dataclass(frozen=True)
class FeedContext:
    """Preloaded analyses and viewer-scoped PCA coordinates for rendering feed items."""

    analyses: Mapping[str, ClipAnalysis]
    points: Mapping[str, Point]


class ViewerReports:
    """Read side: joins the view log with stored analyses, live arrivals, and queue state."""

    def __init__(self, log: ViewLog, store: AnalysisStore, queue: AnalysisQueue) -> None:
        self.__log = log
        self.__store = store
        self.__queue = queue
        self.__live = LiveWatchers()

    def tracking(self, live: LiveWatchers) -> "ViewerReports":
        """Return a view sharing `live` with `ViewIntake` so open Shorts appear before swipe-out."""
        bound = ViewerReports(self.__log, self.__store, self.__queue)
        bound.__live = live
        return bound

    def viewers(self, now: float | None = None) -> tuple[ViewerSummary, ...]:
        """Every viewer with logged events or an active Short, sorted by pseudonym."""
        known = {*self.__log.viewers(), *self.__live.viewers(now)}
        ordered = sorted(known, key=str)
        return tuple(self.__summary(v, now) for v in ordered)

    def feed(self, viewer: ViewerId, limit: int,
             now: float | None = None) -> tuple[FeedItem, ...]:
        """Up to `limit` most recent events (including any active Short), newest first."""
        logged = sorted(self.__log.between(viewer, EVER), key=attrgetter("seen_at"), reverse=True)
        active = self.__live_event(viewer, logged, now)
        ctx = self.__feed_context({e.video_id for e in logged} | ({active.video_id} if active else set()))
        head = (self.__item(active, ctx, live=True),) if active else ()
        tail = tuple(self.__item(e, ctx, live=False) for e in logged)
        return (*head, *tail)[:limit]

    def readout(self, viewer: ViewerId, spans: Spans, control: ViewerId | None) -> ReadoutView:
        """`viewer` over `spans`, compared with `control` over the same spans if given."""
        events = self.__log.between(viewer, EVER)
        analyses = self.__analyses({e.video_id for e in events})
        shift = self.__shift_from(events, analyses, spans)
        ctrl = self.__viewer_shift(control, spans) if control is not None else None
        result = readout(shift.current, shift.baseline, ctrl)
        return ReadoutView(windows=spans, current=shift.current, baseline=shift.baseline,
                           control=ctrl, readout=result,
                           evidence=evidence_items(events, analyses, spans.current),
                           trajectory=trajectory(events, analyses),
                           guidance=guidance(shift.current, result))

    def queue_status(self) -> QueueStatus:
        """Current background worker queue metrics."""
        return self.__queue.status()

    def __summary(self, viewer: ViewerId, now: float | None) -> ViewerSummary:
        events = self.__log.between(viewer, EVER)
        watch = self.__live.current(viewer, now)
        times = [*(e.seen_at for e in events), *([watch.started_at] if watch else [])]
        return ViewerSummary(viewer=viewer.value, events=len(events),
                             last_seen=max(times, default=None),
                             watching=watch.video_id if watch else None)

    def __live_event(self, viewer: ViewerId, logged: Sequence[ViewEvent],
                     now: float | None) -> ViewEvent | None:
        watch = self.__live.current(viewer, now)
        if watch is None:
            return None
        candidate = watch.as_event(viewer, now if now is not None else watch.started_at)
        return None if any(candidate.repeats(e) for e in logged) else candidate

    def __feed_context(self, video_ids: set[str]) -> FeedContext:
        analyses = self.__analyses(video_ids)
        return FeedContext(analyses=analyses, points=semantic_points(tuple(analyses.values())))

    def __item(self, event: ViewEvent, ctx: FeedContext, live: bool = False) -> FeedItem:
        analysis = ctx.analyses.get(event.video_id)
        if analysis is not None:
            summary = ClipSummary.of(analysis, ctx.points.get(analysis.video_id))
            return FeedItem(event=event, state="scored", error=None, clip=summary, live=live)
        failure = self.__queue.failure(event.video)
        return FeedItem(event=event, state=self.__queue.state_of(event.video),
                        error=failure.error if failure else None, clip=None, live=live)

    def __viewer_shift(self, viewer: ViewerId, spans: Spans) -> Shift:
        events = self.__log.between(viewer, EVER)
        analyses = self.__analyses({e.video_id for e in events})
        return self.__shift_from(events, analyses, spans)

    @staticmethod
    def __shift_from(events: Sequence[ViewEvent], analyses: Mapping[str, ClipAnalysis],
                     spans: Spans) -> Shift:
        return Shift(current=composition(events, analyses, spans.current),
                     baseline=composition(events, analyses, spans.baseline))

    def __analyses(self, video_ids: set[str]) -> dict[str, ClipAnalysis]:
        loaded = (self.__store.load(VideoId(v)) for v in sorted(video_ids))
        return {a.video_id: a for a in loaded if a is not None}


class ViewsApi:
    """Routes under /api for the phone userscript and the dashboard."""

    def __init__(self, intake: ViewIntake, reports: ViewerReports,
                 clock: Callable[[], float]) -> None:
        self.__intake = intake
        self.__reports = reports
        self.__clock = clock

    def router(self) -> APIRouter:
        """Build the FastAPI router bound to this instance."""
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
        """Accept a batch of view events (and optional active Short) from a viewer."""
        try:
            return self.__intake.record(batch)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    def viewers(self) -> tuple[ViewerSummary, ...]:
        """List known viewers with event counts and active watch status."""
        return self.__reports.viewers(self.__clock())

    def feed(self, viewer: str,
             limit: Annotated[int, Query(ge=1, le=500)] = 50) -> tuple[FeedItem, ...]:
        """Newest feed items for `viewer`."""
        return self.__reports.feed(self.__viewer(viewer), limit, self.__clock())

    def readout(self, viewer: str, query: Annotated[ReadoutQuery, Query()]) -> ReadoutView:
        """Longitudinal composition readout, evidence, trajectory and closed-loop view."""
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
        """Status of the background video-analysis queue."""
        return self.__reports.queue_status()

    @staticmethod
    def __viewer(text: str) -> ViewerId:
        try:
            return ViewerId(text)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
