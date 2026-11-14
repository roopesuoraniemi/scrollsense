"""Pure domain values: video identity, analyses and pipeline stages."""
import re
from dataclasses import dataclass
from enum import Enum

from .schemas import ClipScores, Frozen, TextPackage


@dataclass(frozen=True)
class VideoId:
    """An 11-character YouTube video ID.

    Raises ValueError on construction if `value` is not a valid ID.
    """

    value: str

    __ID = re.compile(r"[A-Za-z0-9_-]{11}")
    __IN_URL = re.compile(r"(?:v=|/shorts/|youtu\.be/|/embed/|/live/)([A-Za-z0-9_-]{11})")

    def __post_init__(self) -> None:
        if not self.__ID.fullmatch(self.value):
            raise ValueError(f"Not a YouTube video ID: {self.value!r}")

    @classmethod
    def parse(cls, text: str) -> "VideoId":
        """Extract the ID from a bare ID or any common YouTube/Shorts URL. Raises ValueError."""
        stripped = text.strip()
        found = cls.__IN_URL.search(stripped)
        return cls(found.group(1) if found else stripped)

    @property
    def watch_url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.value}"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class AnalysisRequest:
    """Analyse `video`; with `force`, ignore any stored analysis."""

    video: VideoId
    force: bool = False


class Stage(str, Enum):
    """Progress of one analysis job, in the order a fresh run reports them."""

    QUEUED = "queued"
    CACHED = "cached"
    DESCRIBING = "describing"
    SCORING = "scoring"
    DONE = "done"
    ERROR = "error"


class AnalyserLabel(Frozen):
    """Which models produced an analysis; `mock` marks placeholder output."""

    name: str
    mock: bool


class ClipAnalysis(Frozen):
    """Everything known about one analysed video."""

    video_id: str
    analyser: AnalyserLabel
    created: float
    package: TextPackage
    scores: ClipScores

    @property
    def video(self) -> VideoId:
        return VideoId(self.video_id)

