"""HTTP adapter: clip analyses for the web UI, under /api."""
from fastapi import APIRouter, HTTPException

from .domain import AnalyserLabel, ClipAnalysis, VideoId
from .ports import AnalysisStore
from .schemas import ClipScores, Frozen, Stance, TextPackage
from .service import AnalysisService


class Meta(Frozen):
    """`live`: each viewer's first view of a Short starts a fresh analysis."""

    analyser: AnalyserLabel
    live: bool = False


class ClipSummary(Frozen):
    """One clip on the affect map: enough to plot and label it."""

    id: str
    title: str
    valence: int
    arousal: int
    stance: Stance

    @classmethod
    def of(cls, analysis: ClipAnalysis) -> "ClipSummary":
        s = analysis.scores
        return cls(id=analysis.video_id, title=analysis.package.title, valence=s.valence,
                   arousal=s.arousal, stance=s.stance)


class ClipDetail(Frozen):
    """A full analysis for display, with the derived valence."""

    id: str
    url: str
    analyser: AnalyserLabel
    package: TextPackage
    scores: ClipScores
    valence: int

    @classmethod
    def of(cls, analysis: ClipAnalysis) -> "ClipDetail":
        return cls(id=analysis.video_id, url=analysis.video.watch_url, analyser=analysis.analyser,
                   package=analysis.package, scores=analysis.scores,
                   valence=analysis.scores.valence)


class ClipCatalog:
    """Read side of the clip store for the UI."""

    def __init__(self, store: AnalysisStore) -> None:
        self.__store = store

    def summaries(self) -> list[ClipSummary]:
        """Every stored clip, oldest first."""
        return [ClipSummary.of(a) for a in self.__store.list_all()]

    def detail(self, video: VideoId) -> ClipDetail | None:
        analysis = self.__store.load(video)
        return ClipDetail.of(analysis) if analysis else None


class Api:
    """Routes for the web UI. `router()` builds a fresh router bound to this instance."""

    def __init__(self, service: AnalysisService, catalog: ClipCatalog, live: bool = False) -> None:
        self.__service = service
        self.__catalog = catalog
        self.__live = live

    def router(self) -> APIRouter:
        router = APIRouter(prefix="/api")
        router.add_api_route("/meta", self.meta, methods=["GET"])
        router.add_api_route("/clips", self.clips, methods=["GET"])
        router.add_api_route("/clips/{video_id}", self.clip, methods=["GET"])
        return router

    def meta(self) -> Meta:
        return Meta(analyser=self.__service.label, live=self.__live)

    def clips(self) -> list[ClipSummary]:
        return self.__catalog.summaries()

    def clip(self, video_id: str) -> ClipDetail:
        try:
            video = VideoId.parse(video_id)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        detail = self.__catalog.detail(video)
        if detail is None:
            raise HTTPException(404, "Not analysed yet")
        return detail
