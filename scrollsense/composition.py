"""Composition root: settings from the environment, and the wiring of concrete parts."""
import os
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .gemini import GeminiAnalyser, GeminiConfig
from .mock import MockAnalyser
from .ports import AnalysisStore, ContentAnalyser
from .service import AnalysisService
from .store import JsonFileStore

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    """`mock` swaps Gemini for placeholder output, stored in its own folder so it can
    never be served as a real analysis."""

    mock: bool
    gemini: GeminiConfig
    data_dir: Path

    @classmethod
    def from_env(cls, root: Path) -> "Settings":
        """Read `root/.env`, then the process environment."""
        load_dotenv(root / ".env")
        mock = os.getenv("SCROLLSENSE_MOCK") == "1"
        gemini = GeminiConfig(model=os.getenv("GEMINI_MODEL", "gemini-4-hydrogen"),
                              embed_model=os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-2"))
        return cls(mock=mock, gemini=gemini, data_dir=root / "data" / ("mock_clips" if mock else "clips"))


@dataclass(frozen=True)
class Wiring:
    service: AnalysisService
    store: AnalysisStore


def wire(settings: Settings) -> Wiring:
    """Build the service and store. Raises RuntimeError if Gemini is chosen without a key."""
    store = JsonFileStore(settings.data_dir)
    return Wiring(service=AnalysisService(__analyser(settings), store, time.time), store=store)


def __analyser(settings: Settings) -> ContentAnalyser:
    return MockAnalyser() if settings.mock else GeminiAnalyser(settings.gemini)
