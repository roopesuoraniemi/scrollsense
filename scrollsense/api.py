"""HTTP adapter: JSON endpoints under /api."""
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from .domain import AnalyserLabel, AnalysisRequest, ClipAnalysis, Point, VideoId, semantic_points
from .jobs import JobBoard, JobStatus
from .ports import AnalysisStore
from .schemas import CRITERIA, ClipScores, Criterion, Frozen, Stance, TextPackage
from .service import AnalysisService


class Meta(Frozen):
    criteria: tuple[Criterion, ...]
    analyser: AnalyserLabel


class AnalyseBody(Frozen):
    url: str
    force: bool = False


class JobAccepted(Frozen):
    job: str
    id: str


class ClipSummary(Frozen):
    """One point on the maps: enough to plot and label a clip."""

    id: str
    title: str
    valence: int
    arousal: int
    stance: Stance
    load: int
    a9: int
    semantic: Point | None

    @classmethod
    def of(cls, analysis: ClipAnalysis, semantic: Point | None) -> "ClipSummary":
        s = analysis.scores
        return cls(id=analysis.video_id, title=analysis.package.title, valence=s.valence,
                   arousal=s.arousal, stance=s.stance, load=s.theme_load,
                   a9=s.a9_death_suicide, semantic=semantic)


class ClipDetail(Frozen):
    """A full analysis for display; the embedding vector is left out."""

    id: str
    url: str
    analyser: AnalyserLabel
    package: TextPackage
    scores: ClipScores
    load: int
    embed_error: str | None

    @classmethod
    def of(cls, analysis: ClipAnalysis) -> "ClipDetail":
        return cls(id=analysis.video_id, url=analysis.video.watch_url, analyser=analysis.analyser,
                   package=analysis.package, scores=analysis.scores,
                   load=analysis.scores.theme_load, embed_error=analysis.embedding.error)


class Api:
    """Routes for the web UI. `router()` builds a fresh router bound to this instance."""

    def __init__(self, service: AnalysisService, store: AnalysisStore, board: JobBoard) -> None:
        self.__service = service
        self.__store = store
        self.__board = board

    def router(self) -> APIRouter:
        router = APIRouter(prefix="/api")
        router.add_api_route("/meta", self.meta, methods=["GET"])
        router.add_api_route("/clips", self.clips, methods=["GET"])
        router.add_api_route("/clips/{video_id}", self.clip, methods=["GET"])
        router.add_api_route("/analyze", self.analyse, methods=["POST"])
        router.add_api_route("/jobs/{job_id}", self.job, methods=["GET"])
        return router

    def meta(self) -> Meta:
        return Meta(criteria=CRITERIA, analyser=self.__service.label)

    def clips(self) -> list[ClipSummary]:
        analyses = self.__store.list_all()
        points = semantic_points(analyses)
        return [ClipSummary.of(a, points.get(a.video_id)) for a in analyses]

    def clip(self, video_id: str) -> ClipDetail:
        analysis = self.__store.load(self.__video(video_id))
        if analysis is None:
            raise HTTPException(404, "Not analysed yet")
        return ClipDetail.of(analysis)

    def analyse(self, body: AnalyseBody) -> JobAccepted:
        video = self.__video(body.url)
        job_id = uuid4().hex[:8]
        self.__board.start(job_id, AnalysisRequest(video=video, force=body.force))
        return JobAccepted(job=job_id, id=video.value)

    def job(self, job_id: str) -> JobStatus:
        status = self.__board.status(job_id)
        if status is None:
            raise HTTPException(404, "Unknown job")
        return status

    @staticmethod
    def __video(text: str) -> VideoId:
        try:
            return VideoId.parse(text)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
