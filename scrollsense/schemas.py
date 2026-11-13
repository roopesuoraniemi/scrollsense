"""Structured-output schemas for the two Gemini stages, plus DSM-5 criterion metadata."""
from typing import Literal

from pydantic import BaseModel, Field

# The nine DSM-5 criteria for a major depressive episode (same items as the PHQ-9).
# We score *themes in the content*, never the people in it.
CRITERIA = [
    {"key": "a1_depressed_mood", "code": "A1", "label": "Depressed mood",
     "theme": "sadness, emptiness, hopelessness, crying, feeling down"},
    {"key": "a2_anhedonia", "code": "A2", "label": "Anhedonia",
     "theme": "numbness, nothing matters, loss of interest or pleasure"},
    {"key": "a3_appetite_weight", "code": "A3", "label": "Appetite / weight",
     "theme": "not eating, overeating, body weight change"},
    {"key": "a4_sleep", "code": "A4", "label": "Sleep",
     "theme": "insomnia, can't sleep, being up all night, oversleeping"},
    {"key": "a5_psychomotor", "code": "A5", "label": "Psychomotor",
     "theme": "feeling slowed down, unable to move, or restless and agitated"},
    {"key": "a6_fatigue", "code": "A6", "label": "Fatigue",
     "theme": "exhaustion, no energy, everything takes effort"},
    {"key": "a7_worthlessness_guilt", "code": "A7", "label": "Worthlessness / guilt",
     "theme": "self-blame, being a burden, failure, excessive guilt"},
    {"key": "a8_concentration", "code": "A8", "label": "Concentration",
     "theme": "brain fog, can't focus, can't make decisions"},
    {"key": "a9_death_suicide", "code": "A9", "label": "Death / suicide",
     "theme": "death wishes, suicide, self-harm"},
]
CRITERION_KEYS = [c["key"] for c in CRITERIA]


class TextPackage(BaseModel):
    title: str = Field(description="Short neutral title for the clip, at most 8 words")
    transcript: str = Field(description="Spoken words, verbatim where audible. Empty string if none.")
    on_screen_text: str = Field(description="Captions and text overlays, verbatim. Empty string if none.")
    visual_description: str = Field(description="Setting, lighting, colours, actions, editing pace")
    audio_description: str = Field(description="Music genre, tempo and energy; tone of delivery")
    main_message: str = Field(description="One sentence: what the clip communicates")
    format: Literal["talking_to_camera", "broll_with_text", "meme", "music_edit",
                    "skit", "tutorial", "other"]
    people_present: bool
    language: str = Field(description="Main language of speech or text, e.g. 'en'")


Stance = Literal["dwelling_or_romanticising", "neutral_or_informational",
                 "coping_or_recovery", "unrelated"]

_THEME = "0 = absent, 1 = mentioned, 2 = central theme, 3 = intense or glorified. Theme: "


class ClipScores(BaseModel):
    valence: int = Field(description="Emotional tone of the content, 1 very negative .. 5 very positive")
    arousal: int = Field(description="Energy of the content, 1 very calm .. 5 very energetic")
    stance: Stance = Field(description="How the clip relates to depressive themes")
    a1_depressed_mood: int = Field(description=_THEME + CRITERIA[0]["theme"])
    a2_anhedonia: int = Field(description=_THEME + CRITERIA[1]["theme"])
    a3_appetite_weight: int = Field(description=_THEME + CRITERIA[2]["theme"])
    a4_sleep: int = Field(description=_THEME + CRITERIA[3]["theme"])
    a5_psychomotor: int = Field(description=_THEME + CRITERIA[4]["theme"])
    a6_fatigue: int = Field(description=_THEME + CRITERIA[5]["theme"])
    a7_worthlessness_guilt: int = Field(description=_THEME + CRITERIA[6]["theme"])
    a8_concentration: int = Field(description=_THEME + CRITERIA[7]["theme"])
    a9_death_suicide: int = Field(description=_THEME + CRITERIA[8]["theme"])
    hopeful: bool = Field(description="Shows recovery, progress, kindness or possibility")
    evidence: str = Field(description="One short quote or paraphrase from the package that justifies the highest theme score")

    def clamped(self) -> "ClipScores":
        d = self.model_dump()
        for k in ("valence", "arousal"):
            d[k] = min(5, max(1, int(d[k])))
        for k in CRITERION_KEYS:
            d[k] = min(3, max(0, int(d[k])))
        return ClipScores(**d)
