"""Structured-output schemas for the two model stages, and the DSM-5 criteria they score.

The criteria describe *themes in content*, never the people in it.
"""
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field


class Frozen(BaseModel):
    """Base for immutable values: assignment after construction raises."""

    model_config = ConfigDict(frozen=True)


class Criterion(Frozen):
    """One DSM-5 criterion for a major depressive episode, read as a content theme."""

    key: str
    code: str
    label: str
    theme: str


# Same nine items as the PHQ-9.
CRITERIA: tuple[Criterion, ...] = (
    Criterion(key="a1_depressed_mood", code="A1", label="Depressed mood",
              theme="sadness, emptiness, hopelessness, crying, feeling down"),
    Criterion(key="a2_anhedonia", code="A2", label="Anhedonia",
              theme="numbness, nothing matters, loss of interest or pleasure"),
    Criterion(key="a3_appetite_weight", code="A3", label="Appetite / weight",
              theme="not eating, overeating, body weight change"),
    Criterion(key="a4_sleep", code="A4", label="Sleep",
              theme="insomnia, can't sleep, being up all night, oversleeping"),
    Criterion(key="a5_psychomotor", code="A5", label="Psychomotor",
              theme="feeling slowed down, unable to move, or restless and agitated"),
    Criterion(key="a6_fatigue", code="A6", label="Fatigue",
              theme="exhaustion, no energy, everything takes effort"),
    Criterion(key="a7_worthlessness_guilt", code="A7", label="Worthlessness / guilt",
              theme="self-blame, being a burden, failure, excessive guilt"),
    Criterion(key="a8_concentration", code="A8", label="Concentration",
              theme="brain fog, can't focus, can't make decisions"),
    Criterion(key="a9_death_suicide", code="A9", label="Death / suicide",
              theme="death wishes, suicide, self-harm"),
)
SAFETY_CRITERION = CRITERIA[8]

Format = Literal["talking_to_camera", "broll_with_text", "meme", "music_edit",
                 "skit", "tutorial", "other"]
Stance = Literal["dwelling_or_romanticising", "neutral_or_informational",
                 "coping_or_recovery", "unrelated"]
STANCES: tuple[str, ...] = get_args(Stance)


class TextPackage(Frozen):
    """What a video says, shows and sounds like, as written by the describing model."""

    title: str = Field(description="Short neutral title for the clip, at most 8 words")
    transcript: str = Field(description="Spoken words, verbatim where audible. Empty string if none.")
    on_screen_text: str = Field(description="Captions and text overlays, verbatim. Empty string if none.")
    visual_description: str = Field(description="Setting, lighting, colours, actions, editing pace")
    audio_description: str = Field(description="Music genre, tempo and energy; tone of delivery")
    main_message: str = Field(description="One sentence: what the clip communicates")
    format: Format
    people_present: bool
    language: str = Field(description="Main language of speech or text, e.g. 'en'")


THEME_SCALE = "0 = absent, 1 = mentioned, 2 = central theme, 3 = intense or glorified. Theme: "


class ClipScores(Frozen):
    """Mood and DSM-5 theme scores for one text package.

    Theme scores are 0-3 and valence/arousal 1-5 once `clamped` has been applied.
    """

    valence: int = Field(description="Emotional tone of the content, 1 very negative .. 5 very positive")
    arousal: int = Field(description="Energy of the content, 1 very calm .. 5 very energetic")
    stance: Stance = Field(description="How the clip relates to depressive themes")
    a1_depressed_mood: int = Field(description=THEME_SCALE + CRITERIA[0].theme)
    a2_anhedonia: int = Field(description=THEME_SCALE + CRITERIA[1].theme)
    a3_appetite_weight: int = Field(description=THEME_SCALE + CRITERIA[2].theme)
    a4_sleep: int = Field(description=THEME_SCALE + CRITERIA[3].theme)
    a5_psychomotor: int = Field(description=THEME_SCALE + CRITERIA[4].theme)
    a6_fatigue: int = Field(description=THEME_SCALE + CRITERIA[5].theme)
    a7_worthlessness_guilt: int = Field(description=THEME_SCALE + CRITERIA[6].theme)
    a8_concentration: int = Field(description=THEME_SCALE + CRITERIA[7].theme)
    a9_death_suicide: int = Field(description=THEME_SCALE + CRITERIA[8].theme)
    hopeful: bool = Field(description="Shows recovery, progress, kindness or possibility")
    evidence: str = Field(description="One short quote or paraphrase from the package that justifies the highest theme score")

    def score_of(self, criterion: Criterion) -> int:
        """The 0-3 score for `criterion`."""
        return int(getattr(self, criterion.key))

    @property
    def theme_load(self) -> int:
        """Sum of the nine theme scores, 0-27. Not a diagnostic score."""
        return sum(self.score_of(c) for c in CRITERIA)

    def clamped(self) -> "ClipScores":
        """A copy with every score forced into its documented range (models occasionally overshoot)."""
        themes = {c.key: min(3, max(0, self.score_of(c))) for c in CRITERIA}
        mood = {k: min(5, max(1, getattr(self, k))) for k in ("valence", "arousal")}
        return self.model_copy(update=themes | mood)
