"""Seams between the pipeline and the outside world."""
from abc import ABC, abstractmethod
from typing import Callable

from .domain import AnalyserLabel, ClipAnalysis, Stage, VideoId
from .schemas import ClipScores, TextPackage

Progress = Callable[[Stage], None]


class ContentAnalyser(ABC):
    """Turns a video into a text package, scores it and embeds it.

    Implementations may call remote models: every method can block for seconds and raise.
    """

    @property
    @abstractmethod
    def label(self) -> AnalyserLabel:
        """Which models this analyser uses."""

    @abstractmethod
    def describe(self, video: VideoId) -> TextPackage:
        """Watch `video` and describe its content."""

    @abstractmethod
    def score(self, package: TextPackage) -> ClipScores:
        """Score the package's mood and DSM-5 themes, already clamped to range."""

    @abstractmethod
    def embed(self, package: TextPackage) -> tuple[float, ...]:
        """A semantic embedding of the package text."""


class AnalysisStore(ABC):
    """Persistent analyses, at most one per video."""

    @abstractmethod
    def load(self, video: VideoId) -> ClipAnalysis | None:
        """The stored analysis of `video`, or None."""

    @abstractmethod
    def list_all(self) -> tuple[ClipAnalysis, ...]:
        """Every stored analysis, oldest first."""

    @abstractmethod
    def save(self, analysis: ClipAnalysis) -> None:
        """Store `analysis`, replacing any earlier one for the same video."""
