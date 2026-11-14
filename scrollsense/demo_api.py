"""The web demo's "add a Short" route: validate a pasted Short and let the scheduler start its
analysis within the run budget, so a public demo link cannot spend unbounded Gemini credits."""
from typing import Literal

from fastapi import APIRouter, HTTPException

from .analysis_queue import AnalysisQueue
from .domain import VideoId
from .ports import AnalysisStore
from .scheduling import AnalysisScheduler, QuotaExceeded
from .schemas import Frozen
from .views import ViewerId

ClipState = Literal["scored", "queued", "failed", "pending"]


class AddShort(Frozen):
    viewer: str
    url: str


class Added(Frozen):
    """The Short's id and where its analysis stands: `scored` (stored), `queued`, `failed`, or
    `pending` (it starts when the Short is viewed)."""

    video_id: str
    state: ClipState


class ShortAdder:
    def __init__(self, scheduler: AnalysisScheduler, queue: AnalysisQueue,
                 store: AnalysisStore) -> None:
        self.__scheduler = scheduler
        self.__queue = queue
        self.__store = store

    def add(self, viewer: ViewerId, video: VideoId) -> Added:
        """Raises QuotaExceeded if the viewer may not start another run."""
        self.__scheduler.added(viewer, video)
        return Added(video_id=video.value, state=self.__state_of(video))

    def __state_of(self, video: VideoId) -> ClipState:
        state = self.__queue.state_of(video)
        if state == "pending" and self.__store.load(video) is not None:
            return "scored"
        return state


class DemoApi:
    """Routes under /api/demo."""

    def __init__(self, adder: ShortAdder) -> None:
        self.__adder = adder

    def router(self) -> APIRouter:
        router = APIRouter(prefix="/api/demo")
        router.add_api_route("/shorts", self.add, methods=["POST"], status_code=201)
        return router

    def add(self, body: AddShort) -> Added:
        try:
            return self.__adder.add(ViewerId(body.viewer), VideoId.parse(body.url))
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except QuotaExceeded as error:
            raise HTTPException(429, str(error)) from error
