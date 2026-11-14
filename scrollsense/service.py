"""The analysis pipeline: describe, score, store."""
from typing import Callable

from .domain import AnalyserLabel, AnalysisRequest, ClipAnalysis, Stage, VideoId
from .ports import AnalysisStore, ContentAnalyser, Progress


class AnalysisService:
    """Runs the pipeline for one video at a time and stores the result. Describe and score
    failures propagate."""

    def __init__(self, analyser: ContentAnalyser, store: AnalysisStore,
                 clock: Callable[[], float]) -> None:
        self.__analyser = analyser
        self.__store = store
        self.__clock = clock

    @property
    def label(self) -> AnalyserLabel:
        return self.__analyser.label

    def run(self, request: AnalysisRequest, progress: Progress) -> None:
        """Analyse and store `request.video`, unless it is already stored and not forced.

        Blocks until done, reporting each Stage to `progress` (CACHED when skipped).
        """
        if not request.force and self.__store.load(request.video) is not None:
            progress(Stage.CACHED)
            return
        self.__store.save(self.__analyse(request.video, progress))

    def __analyse(self, video: VideoId, progress: Progress) -> ClipAnalysis:
        progress(Stage.DESCRIBING)
        package = self.__analyser.describe(video)
        progress(Stage.SCORING)
        scores = self.__analyser.score(package)
        return ClipAnalysis(video_id=video.value, analyser=self.__analyser.label,
                            created=self.__clock(), package=package, scores=scores)
