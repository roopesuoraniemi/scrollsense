"""ContentAnalyser that makes no API calls, for offline demos and UI development."""
import hashlib
import math
import time
from dataclasses import dataclass

from .domain import AnalyserLabel, VideoId
from .ports import ContentAnalyser
from .schemas import CRITERIA, ClipScores, Format, Stance, TextPackage

MOCK_SAFETY_ID = "mockA9safet"
EMBED_DIM = 32


@dataclass(frozen=True)
class MockArchetype:
    """Synthetic clip template used in offline `SCROLLSENSE_MOCK=1` mode."""

    headline: str
    fmt: Format
    people: bool
    cues: str
    meaning: str
    quote: str
    stance: Stance
    neg: int
    pos: int
    arousal: int
    hopeful: bool
    themes: dict[str, int]
    cluster: int


ARCHETYPES: tuple[MockArchetype, ...] = (
    MockArchetype("Crispy garlic chili noodles", "tutorial", True,
                  "warm kitchen light, brisk chopping rhythm, upbeat lo-fi beat",
                  "Quick comfort-food recipe meant to be satisfying and easy to follow.",
                  "Two-minute garlic oil pour over fresh noodles.",
                  "unrelated", 0, 2, 3, False, {}, 0),
    MockArchetype("Golden retriever discovers first snow", "animals_nature", False,
                  "bright morning snow, playful acoustic strum, joyful pacing",
                  "Wholesome animal clip evoking warmth and amusement.",
                  "Puppy leaps nose-first into fresh powder.",
                  "unrelated", 0, 3, 4, True, {}, 1),
    MockArchetype("Group chat planning a weekend trip", "skit", True,
                  "quick comedic cuts, bright room, lighthearted banter",
                  "Relatable everyday comedy skit about disorganised friends.",
                  "Nobody booked the train tickets yet.",
                  "unrelated", 0, 2, 4, False, {}, 2),
    MockArchetype("Acoustic guitar on sunny balcony", "music_edit", True,
                  "golden afternoon light, gentle fingerstyle guitar, unhurried tempo",
                  "Calm instrumental performance creating a restorative pause.",
                  "Warm major-key fingerpicking in afternoon sun.",
                  "unrelated", 0, 2, 2, True, {}, 3),
    MockArchetype("Restoring an old brass compass", "broll_with_text", False,
                  "macro workbench lighting, steady brush sounds, calm narration",
                  "Curiosity craft video focused on patient restoration.",
                  "Polishing the oxidised dial back to a clear shine.",
                  "unrelated", 0, 1, 2, False, {}, 4),
    MockArchetype("Small routine wins in recovery", "talking_to_camera", True,
                  "morning window light, steady voice, soft acoustic backing",
                  "Peer recovery reflection validating gradual progress without dwelling.",
                  "Made the bed, stepped outside for ten minutes — small steps count.",
                  "coping_or_recovery", 1, 2, 2, True, {"a1_depressed_mood": 1, "a6_fatigue": 1}, 3),
    MockArchetype("Ceiling fan spinning at 3 AM", "broll_with_text", False,
                  "dim blue bedroom, slowed ambient piano, static camera",
                  "Late-night insomnia clip lingering in exhaustion and empty hours.",
                  "3:14 AM again, staring at the ceiling too tired to sleep.",
                  "dwelling_or_romanticising", 2, 0, 1, False,
                  {"a1_depressed_mood": 2, "a4_sleep": 3, "a6_fatigue": 2}, 5),
    MockArchetype("Too drained to enjoy anything lately", "talking_to_camera", True,
                  "muted grey tones, flat quiet delivery, slow ambient drone",
                  "Unfiltered monologue aestheticising emotional numbness and loss of interest.",
                  "Everything I used to love just feels completely grey and heavy.",
                  "dwelling_or_romanticising", 3, 0, 1, False,
                  {"a1_depressed_mood": 3, "a2_anhedonia": 3, "a6_fatigue": 2}, 5),
    MockArchetype("Replaying every mistake instead of sleeping", "meme", False,
                  "dark room overlay, slowed melancholic track, bleak caption tone",
                  "Self-deprecating 2 AM rumination meme centred on guilt and sleeplessness.",
                  "Lying awake listing every way I let people down.",
                  "dwelling_or_romanticising", 2, 0, 2, False,
                  {"a1_depressed_mood": 2, "a4_sleep": 2, "a7_worthlessness_guilt": 2}, 5),
)

SAFETY_ARCHETYPE = MockArchetype(
    "Crisis support and staying safe tonight", "broll_with_text", False,
    "dim evening light, quiet piano, serious overlay caption",
    "Clip explicitly referencing suicidal thoughts (triggers deterministic A9 safety path).",
    "Explicit mention of not wanting to wake up tomorrow [MOCK safety test].",
    "dwelling_or_romanticising", 3, 0, 1, False,
    {"a1_depressed_mood": 2, "a9_death_suicide": 2}, 5,
)

PINNED_ARCHETYPES: dict[str, int] = {
    "Qo4PLQXRmUw": 0, "RWD9TXXf1_A": 1, "KOiWuuzGzOw": 2, "jNQXAC9IVRw": 3,
    "cRftRest001": 4, "recovWin001": 5,
    "lMQJ2bHeP4c": 6, "wZF2PLGsksI": 7, "bPnRMwahAMA": 8,
}


class MockAnalyser(ContentAnalyser):
    """Deterministic `[MOCK]` output with coherent formats, stances and topic embeddings.

    Arbitrary video IDs never score A9; `MOCK_SAFETY_ID` (`mockA9safet`) is reserved
    for testing the deterministic safety banner offline.
    """

    def __init__(self, delay_s: float = 0.6) -> None:
        self.__delay_s = delay_s

    @property
    def label(self) -> AnalyserLabel:
        """Marks analyses as offline mock data."""
        return AnalyserLabel(name="mock", embed_name="mock", mock=True)

    def describe(self, video: VideoId) -> TextPackage:
        """Build a `[MOCK]` TextPackage deterministically from `video`."""
        time.sleep(self.__delay_s)
        arch = self.__for_video(video.value)
        return TextPackage(
            title=f"[MOCK] {arch.headline} ({video})",
            transcript=f"[MOCK] {arch.quote} (No video was sent to Gemini.)",
            on_screen_text=f"[MOCK] {arch.headline}",
            visual_description=f"[MOCK] {arch.cues}",
            audio_description=f"[MOCK] {arch.cues}",
            emotional_cues=f"[MOCK] {arch.cues}",
            intended_meaning=f"[MOCK] {arch.meaning}",
            main_message=f"[MOCK] {arch.meaning}",
            format=arch.fmt, people_present=arch.people, language="en")

    def score(self, package: TextPackage) -> ClipScores:
        """Score `package` coherently with its mock archetype."""
        time.sleep(self.__delay_s)
        arch = self.__for_title(package.title)
        themes = {c.key: arch.themes.get(c.key, 0) for c in CRITERIA}
        return ClipScores(
            rationale=f"[MOCK] Synthetic rationale for {arch.headline.lower()} ({arch.stance}).",
            evidence=f"[MOCK] {arch.quote}",
            negative_affect=arch.neg, positive_affect=arch.pos, arousal=arch.arousal,
            stance=arch.stance, hopeful=arch.hopeful, **themes)

    def embed(self, package: TextPackage) -> tuple[float, ...]:
        """Topic-clustered 32-D vector so diverse feeds spread and drift feeds contract."""
        arch = self.__for_title(package.title)
        base = arch.cluster * 5
        values = [self.__component(package.title, base, i) for i in range(EMBED_DIM)]
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return tuple(round(v / norm, 5) for v in values)

    @classmethod
    def __for_video(cls, video_id: str) -> MockArchetype:
        if video_id == MOCK_SAFETY_ID:
            return SAFETY_ARCHETYPE
        if video_id in PINNED_ARCHETYPES:
            return ARCHETYPES[PINNED_ARCHETYPES[video_id]]
        return ARCHETYPES[cls.__digit(video_id, "arch") % len(ARCHETYPES)]

    @classmethod
    def __for_title(cls, title: str) -> MockArchetype:
        if SAFETY_ARCHETYPE.headline in title:
            return SAFETY_ARCHETYPE
        for arch in ARCHETYPES:
            if arch.headline in title:
                return arch
        return ARCHETYPES[cls.__digit(title, "arch") % len(ARCHETYPES)]

    @classmethod
    def __component(cls, seed: str, base: int, index: int) -> float:
        signal = 1.0 if base <= index < base + 4 else 0.0
        jitter = ((cls.__digit(seed, f"e{index}") % 200) - 100) / 1000.0
        return signal + jitter

    @staticmethod
    def __digit(seed: str, salt: str) -> int:
        return int(hashlib.sha256((seed + salt).encode()).hexdigest(), 16)
