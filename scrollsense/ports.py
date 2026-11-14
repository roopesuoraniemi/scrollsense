"""Seams between the pipeline and the outside world."""
from abc import ABC, abstractmethod
from typing import Callable, Sequence

from .domain import AnalyserLabel, ClipAnalysis, Stage, VideoId
from .nudge import Nudge, NudgeCard, NudgeHistory, NudgeResponse
from .schemas import Analysed
from .views import ViewerId, ViewEvent, Window

Progress = Callable[[Stage], None]


class ContentAnalyser(ABC):
    """Turns a video into a text package and affect scores.

    Implementations may call remote models: `analyse` can block for seconds and raise.
    """

    @property
    @abstractmethod
    def label(self) -> AnalyserLabel:
        """Which models this analyser uses."""

    @abstractmethod
    def analyse(self, video: VideoId, progress: Progress) -> Analysed:
        """Watch `video`, describe it and score its affect (clamped to range), reporting each
        Stage it enters to `progress`."""


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


class ViewLog(ABC):
    """Append-only record of view events, per viewer. Deduplication is the caller's job."""

    @abstractmethod
    def append(self, events: Sequence[ViewEvent]) -> None:
        """Record `events` after any already logged, for whichever viewers they name."""

    @abstractmethod
    def between(self, viewer: ViewerId, window: Window) -> tuple[ViewEvent, ...]:
        """`viewer`'s events with `seen_at` in `window`, in the order they were appended."""

    @abstractmethod
    def viewers(self) -> tuple[ViewerId, ...]:
        """Every viewer with at least one logged event, sorted."""

    @abstractmethod
    def erase(self, viewer: ViewerId) -> None:
        """Delete everything logged for `viewer` (GDPR erasure). Unknown viewers are a no-op."""


class NudgeLog(ABC):
    """Append-only record of the nudges issued to each viewer and their responses.
    Validating a response (known id, not yet answered) is the caller's job."""

    @abstractmethod
    def record(self, nudge: Nudge) -> None:
        """Record `nudge` as issued to `nudge.viewer`."""

    @abstractmethod
    def respond(self, viewer: ViewerId, response: NudgeResponse) -> None:
        """Record `viewer`'s `response` to one of their nudges."""

    @abstractmethod
    def history(self, viewer: ViewerId) -> NudgeHistory:
        """`viewer`'s nudges in issue order, each joined with its first response."""

    @abstractmethod
    def erase(self, viewer: ViewerId) -> None:
        """Delete everything recorded for `viewer` (GDPR erasure). Unknown viewers are a no-op."""


class Nudger(ABC):
    """Offers nudges to viewers as their batches arrive."""

    @abstractmethod
    def issue_if_due(self, viewer: ViewerId) -> NudgeCard | None:
        """Atomically issue and record a nudge if the policy says one is due now, then return
        `viewer`'s open (unanswered, unexpired) card, new or pending, or None."""

    @abstractmethod
    def erase(self, viewer: ViewerId) -> None:
        """Delete `viewer`'s nudges and responses (GDPR erasure). Idempotent."""
