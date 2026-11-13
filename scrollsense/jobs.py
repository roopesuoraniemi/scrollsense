"""Background analysis jobs with pollable status."""
from threading import Lock, Thread

from .domain import AnalysisRequest, Stage
from .schemas import Frozen
from .service import AnalysisService


class JobStatus(Frozen):
    id: str
    stage: Stage
    error: str | None = None


class JobBoard:
    """Runs each analysis on its own daemon thread and tracks its latest status.

    Statuses live in memory only and are lost on restart.
    """

    def __init__(self, service: AnalysisService) -> None:
        self.__service = service
        self.__statuses: dict[str, JobStatus] = {}
        self.__lock = Lock()

    def start(self, job_id: str, request: AnalysisRequest) -> None:
        """Queue `request` under `job_id` and return immediately."""
        self.__set(job_id, JobStatus(id=request.video.value, stage=Stage.QUEUED))
        Thread(target=self.__run, args=(job_id, request), daemon=True).start()

    def status(self, job_id: str) -> JobStatus | None:
        """The latest status of `job_id`, or None if unknown."""
        with self.__lock:
            return self.__statuses.get(job_id)

    def __run(self, job_id: str, request: AnalysisRequest) -> None:
        video_id = request.video.value
        try:
            self.__service.run(request, lambda stage: self.__set(job_id, JobStatus(id=video_id, stage=stage)))
            self.__set(job_id, JobStatus(id=video_id, stage=Stage.DONE))
        except Exception as error:  # a worker thread must report, never die silently
            self.__set(job_id, JobStatus(id=video_id, stage=Stage.ERROR,
                                         error=f"{type(error).__name__}: {error}"))

    def __set(self, job_id: str, status: JobStatus) -> None:
        with self.__lock:
            self.__statuses[job_id] = status
