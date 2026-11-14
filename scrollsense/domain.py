"""Pure domain values: video identity, analyses, pipeline stages and the semantic map."""
import re
from dataclasses import dataclass
from enum import Enum

import numpy as np

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
    EMBEDDING = "embedding"
    DONE = "done"
    ERROR = "error"


class AnalyserLabel(Frozen):
    """Which models produced an analysis; `mock` marks placeholder output."""

    name: str
    embed_name: str
    mock: bool


class Embedding(Frozen):
    """A text-package embedding, or why there is none (the map is optional, so failure is data)."""

    vector: tuple[float, ...] | None = None
    error: str | None = None


class ClipAnalysis(Frozen):
    """Everything known about one analysed video."""

    video_id: str
    analyser: AnalyserLabel
    created: float
    package: TextPackage
    scores: ClipScores
    embedding: Embedding

    @property
    def video(self) -> VideoId:
        return VideoId(self.video_id)


class Point(Frozen):
    x: float
    y: float


class ContentAxis(Frozen):
    """Fixed content-similarity axes, built by `scripts/build_content_axis.py` from labelled
    test Shorts. x is 0 at the light centroid and 1 at the depression-themed one; y is the main
    remaining topic direction in SD units. It describes content, never a person."""

    embed_model: str
    x: tuple[float, ...]
    x_light: float
    x_heavy: float
    y: tuple[float, ...]
    y_mean: float
    y_sd: float

    def project(self, analysis: ClipAnalysis) -> Point | None:
        """Where `analysis` sits on the axes; None without an embedding from the same model."""
        vector = analysis.embedding.vector
        if analysis.analyser.embed_name != self.embed_model or not vector or len(vector) != len(self.x):
            return None
        unit = np.asarray(vector) / (np.linalg.norm(vector) or 1.0)
        across = (float(unit @ np.asarray(self.x)) - self.x_light) / (self.x_heavy - self.x_light)
        topic = (float(unit @ np.asarray(self.y)) - self.y_mean) / self.y_sd
        return Point(x=round(across, 4), y=round(topic, 4))
