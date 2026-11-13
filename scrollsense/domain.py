"""Pure domain values: video identity, analyses, pipeline stages and the semantic map."""
import re
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

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


def semantic_points(analyses: Sequence[ClipAnalysis]) -> dict[str, Point]:
    """2-D PCA of the analyses' embeddings, keyed by video ID, each axis scaled to [-1, 1].

    Analyses without an embedding are left out; fewer than two embeddings all map to the
    origin. Axes are relative: adding a clip can rotate or flip them.
    """
    embedded = [a for a in analyses if a.embedding.vector]
    if len(embedded) < 2:
        return {a.video_id: Point(x=0.0, y=0.0) for a in embedded}
    coords = __project(__centred([a.embedding.vector or () for a in embedded]))
    return {a.video_id: Point(x=round(float(x), 4), y=round(float(y), 4))
            for a, (x, y) in zip(embedded, coords)}


def __centred(vectors: list[tuple[float, ...]]) -> np.ndarray:
    dim = min(len(v) for v in vectors)
    matrix = np.array([v[:dim] for v in vectors], dtype=float)
    return matrix - matrix.mean(axis=0)


def __project(centred: np.ndarray) -> np.ndarray:
    _, _, vt = np.linalg.svd(centred, full_matrices=False)
    projected = centred @ vt[:2].T
    if projected.shape[1] < 2:  # two clips give one component; pad the second axis
        projected = np.hstack([projected, np.zeros((projected.shape[0], 1))])
    return projected / (np.abs(projected).max(axis=0) + 1e-9)
