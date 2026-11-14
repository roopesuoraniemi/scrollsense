"""HTTP adapter for drift: each viewer's report, and their hand-set baseline."""
from typing import Callable

from fastapi import APIRouter, HTTPException, Response
from pydantic import Field

from .domain import ClipAnalysis, VideoId
from .drift.core import DriftDetector, DriftReport, Observed, observe
from .ports import AnalysisStore, BaselineStore, ViewLog
from .schemas import Frozen
from .views import EVER, ViewerId


class FeedObserver:
    """Reads one viewer's view log joined with the stored analyses of their Shorts."""

    def __init__(self, log: ViewLog, store: AnalysisStore) -> None:
        self.__log = log
        self.__store = store

    def observed(self, viewer: ViewerId) -> Observed:
        events = self.__log.between(viewer, EVER)
        return observe(events, self.__analyses({e.video_id for e in events}))

    def __analyses(self, video_ids: set[str]) -> dict[str, ClipAnalysis]:
        loaded = (self.__store.load(VideoId(v)) for v in video_ids)
        return {a.video_id: a for a in loaded if a is not None}


class ViewerDrift:
    """Drift reports per viewer, and the commands that set or reset their baseline."""

    def __init__(self, observer: FeedObserver, baselines: BaselineStore,
                 detector: DriftDetector) -> None:
        self.__observer = observer
        self.__baselines = baselines
        self.__detector = detector

    def report(self, viewer: ViewerId) -> DriftReport:
        return self.__detector.report(viewer.value, self.__observer.observed(viewer),
                                      self.__baselines.mark_of(viewer))

    def mark(self, viewer: ViewerId, size: int | None, now: float) -> None:
        """Freeze `viewer`'s most recent `size` analysed Shorts as their baseline.
        Raises ValueError if too few are analysed (see `DriftDetector.mark`)."""
        mark = self.__detector.mark(self.__observer.observed(viewer), size, now)
        self.__baselines.mark(viewer, mark)

    def clear(self, viewer: ViewerId) -> None:
        """Back to the default baseline (the first analysed Shorts)."""
        self.__baselines.clear(viewer)


class BaselineBody(Frozen):
    """`size`: how many of the most recent analysed Shorts to freeze; default baseline_n."""

    size: int | None = Field(default=None, ge=1, le=1000)


class DriftApi:
    """Routes under /api for the drift banner and the baseline buttons."""

    def __init__(self, drift: ViewerDrift, clock: Callable[[], float]) -> None:
        self.__drift = drift
        self.__clock = clock

    def router(self) -> APIRouter:
        router = APIRouter(prefix="/api")
        router.add_api_route("/viewers/{viewer}/drift", self.drift, methods=["GET"])
        router.add_api_route("/viewers/{viewer}/baseline", self.mark, methods=["POST"],
                             status_code=204, response_class=Response)
        router.add_api_route("/viewers/{viewer}/baseline", self.clear, methods=["DELETE"],
                             status_code=204, response_class=Response)
        return router

    def drift(self, viewer: str) -> DriftReport:
        return self.__drift.report(self.__viewer(viewer))

    def mark(self, viewer: str, body: BaselineBody | None = None) -> Response:
        """409 when too few Shorts are analysed to form a baseline."""
        size = body.size if body is not None else None
        try:
            self.__drift.mark(self.__viewer(viewer), size, self.__clock())
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return Response(status_code=204)

    def clear(self, viewer: str) -> Response:
        self.__drift.clear(self.__viewer(viewer))
        return Response(status_code=204)

    @staticmethod
    def __viewer(text: str) -> ViewerId:
        try:
            return ViewerId(text)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
