"""HTTP adapter: JSON endpoints under /api."""
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from .domain import AnalyserLabel, AnalysisRequest, ClipAnalysis, ContentAxis, Point, VideoId
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
    """One point on the maps: enough to plot and label a clip.

    `content`: position on the fixed content-similarity axes (None without a matching embedding).
    `symptoms`: x = low mood + anhedonia (A1 + A2), y = sleep + fatigue (A4 + A6), each 0-6.
    """

    id: str
    title: str
    valence: int
    arousal: int
    stance: Stance
    load: int
    a7: int
    content: Point | None
    symptoms: Point

    @classmethod
    def of(cls, analysis: ClipAnalysis, content: Point | None) -> "ClipSummary":
        s = analysis.scores
        symptoms = Point(x=s.a1_depressed_mood + s.a2_anhedonia, y=s.a4_sleep + s.a6_fatigue)
        return cls(id=analysis.video_id, title=analysis.package.title, valence=s.valence,
                   arousal=s.arousal, stance=s.stance, load=s.theme_load, a7=s.a7_worthlessness_guilt,
                   content=content, symptoms=symptoms)


class ClipCatalog:
    """Read side of the clip store for the UI: analyses placed on the maps."""

    def __init__(self, store: AnalysisStore, axis: ContentAxis | None) -> None:
        self.__store = store
        self.__axis = axis

    def summaries(self) -> list[ClipSummary]:
        """Every stored clip, oldest first, with its map coordinates."""
        return [ClipSummary.of(a, self.__axis.project(a) if self.__axis else None)
                for a in self.__store.list_all()]

    def detail(self, video: VideoId) -> "ClipDetail | None":
        analysis = self.__store.load(video)
        return ClipDetail.of(analysis) if analysis else None


class ClipDetail(Frozen):
    """A full analysis for display, with the derived valence; the embedding vector is left out."""

    id: str
    url: str
    analyser: AnalyserLabel
    package: TextPackage
    scores: ClipScores
    valence: int
    load: int
    embed_error: str | None

    @classmethod
    def of(cls, analysis: ClipAnalysis) -> "ClipDetail":
        return cls(id=analysis.video_id, url=analysis.video.watch_url, analyser=analysis.analyser,
                   package=analysis.package, scores=analysis.scores,
                   valence=analysis.scores.valence, load=analysis.scores.theme_load,
                   embed_error=analysis.embedding.error)


class Api:
    """Routes for the web UI. `router()` builds a fresh router bound to this instance."""

    def __init__(self, service: AnalysisService, catalog: ClipCatalog, board: JobBoard) -> None:
        self.__service = service
        self.__catalog = catalog
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
        return self.__catalog.summaries()

    def clip(self, video_id: str) -> ClipDetail:
        detail = self.__catalog.detail(self.__video(video_id))
        if detail is None:
            raise HTTPException(404, "Not analysed yet")
        return detail

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
