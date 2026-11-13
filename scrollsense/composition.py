"""Composition root: settings from the environment, and the wiring of concrete parts."""
import os
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .analysis_queue import AnalysisQueue, Pacer
from .gemini import GeminiAnalyser, GeminiConfig
from .mock import MockAnalyser
from .ports import AnalysisStore, ContentAnalyser, ViewLog
from .service import AnalysisService
from .store import JsonFileStore
from .viewlog import JsonlViewLog

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class QueueConfig:
    """`workers` analysis threads, starting at most `rpm` analyses per minute between them."""

    workers: int
    rpm: float

    @classmethod
    def from_env(cls) -> "QueueConfig":
        return cls(workers=int(os.getenv("SCROLLSENSE_WORKERS", "2")),
                   rpm=float(os.getenv("SCROLLSENSE_RPM", "20")))


@dataclass(frozen=True)
class Settings:
    """`mock` swaps Gemini for placeholder output, stored in its own folders so it can
    never be served as a real analysis or mixed into a real viewer's log.

    `token`, when set, is required as a Bearer token on every /api route.
    """

    mock: bool
    gemini: GeminiConfig
    data_dir: Path
    views_dir: Path
    token: str | None
    queue: QueueConfig

    @classmethod
    def from_env(cls, root: Path) -> "Settings":
        """Read `root/.env`, then the process environment. `SCROLLSENSE_DATA` moves the data
        folder (default `root/data`)."""
        load_dotenv(root / ".env")
        mock = os.getenv("SCROLLSENSE_MOCK") == "1"
        gemini = GeminiConfig(model=os.getenv("GEMINI_MODEL", "gemini-4-hydrogen"),
                              embed_model=os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-2"))
        data = Path(os.getenv("SCROLLSENSE_DATA") or root / "data")
        prefix = "mock_" if mock else ""
        return cls(mock=mock, gemini=gemini, data_dir=data / f"{prefix}clips",
                   views_dir=data / f"{prefix}views", token=os.getenv("SCROLLSENSE_TOKEN") or None,
                   queue=QueueConfig.from_env())


@dataclass(frozen=True)
class Wiring:
    service: AnalysisService
    store: AnalysisStore
    views: ViewLog
    queue: AnalysisQueue


def wire(settings: Settings) -> Wiring:
    """Build the parts; the queue's workers are not started. Raises RuntimeError if Gemini
    is chosen without a key."""
    store = JsonFileStore(settings.data_dir)
    service = AnalysisService(__analyser(settings), store, time.time)
    queue = AnalysisQueue(service, store, Pacer.per_minute(settings.queue.rpm))
    return Wiring(service=service, store=store, views=JsonlViewLog(settings.views_dir), queue=queue)


def __analyser(settings: Settings) -> ContentAnalyser:
    return MockAnalyser() if settings.mock else GeminiAnalyser(settings.gemini)
