"""ContentAnalyser that makes no API calls, for working on the UI without a key."""
import hashlib
import time

from .domain import AnalyserLabel, VideoId
from .ports import ContentAnalyser
from .schemas import CRITERIA, SAFETY_CRITERION, STANCES, ClipScores, TextPackage


class MockAnalyser(ContentAnalyser):
    """Deterministic placeholder output: text is marked [MOCK], scores are pseudo-random
    per video and never include the A9 safety theme. Each call sleeps `delay_s` so the
    UI's progress stages are visible.
    """

    def __init__(self, delay_s: float = 0.6) -> None:
        self.__delay_s = delay_s

    @property
    def label(self) -> AnalyserLabel:
        return AnalyserLabel(name="mock", embed_name="mock", mock=True)

    def describe(self, video: VideoId) -> TextPackage:
        time.sleep(self.__delay_s)
        placeholder = "[MOCK] placeholder"
        return TextPackage(
            title=f"[MOCK] Placeholder clip {video}",
            transcript="[MOCK] No video was analysed. Set GEMINI_API_KEY for real output.",
            on_screen_text=placeholder, visual_description=placeholder,
            audio_description=placeholder, format="other", people_present=False, language="en",
            main_message="[MOCK] Placeholder text package used to test the interface.")

    def score(self, package: TextPackage) -> ClipScores:
        time.sleep(self.__delay_s)
        seed = package.title
        themes = {c.key: self.__digit(seed, c.key) % 4 for c in CRITERIA if c != SAFETY_CRITERION}
        return ClipScores(
            valence=1 + self.__digit(seed, "v") % 5, arousal=1 + self.__digit(seed, "a") % 5,
            stance=STANCES[self.__digit(seed, "s") % len(STANCES)],  # type: ignore[arg-type]
            hopeful=bool(self.__digit(seed, "h") % 2), a9_death_suicide=0,
            evidence="[MOCK] random scores, not an analysis", **themes)

    def embed(self, package: TextPackage) -> tuple[float, ...]:
        return tuple(((self.__digit(package.title, f"e{i}") % 2000) - 1000) / 1000 for i in range(32))

    @staticmethod
    def __digit(seed: str, salt: str) -> int:
        return int(hashlib.sha256((seed + salt).encode()).hexdigest(), 16)
