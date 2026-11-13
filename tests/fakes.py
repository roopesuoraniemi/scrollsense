"""Test doubles for the pipeline seams."""
from scrollsense.domain import AnalyserLabel, ClipAnalysis, VideoId
from scrollsense.mock import MockAnalyser
from scrollsense.ports import AnalysisStore
from scrollsense.schemas import TextPackage


class MemoryStore(AnalysisStore):
    def __init__(self) -> None:
        self.__analyses: dict[str, ClipAnalysis] = {}

    def load(self, video: VideoId) -> ClipAnalysis | None:
        return self.__analyses.get(video.value)

    def list_all(self) -> tuple[ClipAnalysis, ...]:
        return tuple(sorted(self.__analyses.values(), key=lambda a: a.created))

    def save(self, analysis: ClipAnalysis) -> None:
        self.__analyses[analysis.video_id] = analysis


class FailingEmbedAnalyser(MockAnalyser):
    def embed(self, package: TextPackage) -> tuple[float, ...]:
        raise ConnectionError("embedding service down")


def instant_mock() -> MockAnalyser:
    return MockAnalyser(delay_s=0)


def label() -> AnalyserLabel:
    return instant_mock().label


class FailingDescribeAnalyser(MockAnalyser):
    def describe(self, video: VideoId) -> TextPackage:
        raise PermissionError(f"video {video} is private")


def no_wait(seconds: float) -> None:
    """A Pacer sleep that returns at once."""
