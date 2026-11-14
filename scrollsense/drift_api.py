"""HTTP adapter for drift: each viewer's report against the global norms."""
from fastapi import APIRouter, HTTPException

from .domain import ClipAnalysis, VideoId
from .drift.core import DriftDetector, DriftReport
from .drift.observe import Observed, observe
from .ports import AnalysisStore, ViewLog
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
    """Drift reports per viewer."""

    def __init__(self, observer: FeedObserver, detector: DriftDetector) -> None:
        self.__observer = observer
        self.__detector = detector

    def report(self, viewer: ViewerId) -> DriftReport:
        return self.__detector.report(viewer.value, self.__observer.observed(viewer))


class DriftApi:
    """Routes under /api for the drift banner."""

    def __init__(self, drift: ViewerDrift) -> None:
        self.__drift = drift

    def router(self) -> APIRouter:
        router = APIRouter(prefix="/api")
        router.add_api_route("/viewers/{viewer}/drift", self.drift, methods=["GET"])
        return router

    def drift(self, viewer: str) -> DriftReport:
        """400 for a malformed viewer pseudonym."""
        try:
            return self.__drift.report(ViewerId(viewer))
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
