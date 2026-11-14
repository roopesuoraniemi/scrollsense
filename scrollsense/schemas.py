"""Structured-output schemas for the two model stages.

Scores describe the *content* as a typical viewer experiences it, never the people in it.
"""
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field


class Frozen(BaseModel):
    """Base for immutable values: assignment after construction raises."""

    model_config = ConfigDict(frozen=True)


Format = Literal["talking_to_camera", "broll_with_text", "meme", "music_edit",
                 "skit", "tutorial", "animation", "animals_nature", "other"]
Stance = Literal["dwelling_or_romanticising", "neutral_or_informational",
                 "coping_or_recovery", "unrelated"]
STANCES: tuple[str, ...] = get_args(Stance)


class TextPackage(Frozen):
    """What a video says, shows and sounds like, as written by the describing model."""

    title: str = Field(description="Short neutral title for the clip, at most 8 words")
    transcript: str = Field(description="Spoken words, verbatim where audible. Do not transcribe "
                            "song lyrics. Empty string if none.")
    on_screen_text: str = Field(description="Captions, text overlays and emoji, verbatim. "
                                "Empty string if none.")
    visual_description: str = Field(description="Setting, lighting, colours, actions, editing pace. "
                                    "Who is shown, by role and appearance, or by name when allowed.")
    audio_description: str = Field(description="Music genre, tempo and energy; tone of delivery")
    emotional_cues: str = Field(description="The concrete affect signals in the content itself, as a "
                                "short list: music mood and tempo, the lyrics' theme in a few words "
                                "(never quote lyrics), pacing, colour and lighting, emoji, caption "
                                "tone. Not the feelings of any real person shown.")
    intended_meaning: str = Field(description="1-3 sentences: how a typical viewer reads the clip, "
                                  "including irony, sarcasm, subtext, the meme format or template, "
                                  "in-jokes and the cultural reference it relies on")
    main_message: str = Field(description="One sentence: what the clip communicates")
    format: Format
    people_present: bool
    language: str = Field(description="Main language of speech or text, e.g. 'en'")


AFFECT_SCALE = ("felt by a typical viewer while watching, not the speaker's delivery tone. "
                "0 none, 1 slight, 2 clear, 3 strong. ")


class ClipScores(Frozen):
    """Affect scores for one text package.

    Affect scores are 0-3 and arousal 1-5 once `clamped` has been applied.
    Field order matters: structured output fills fields in schema order, so the
    rationale is written before any number.
    """

    rationale: str = Field(description="2-4 sentences, written first: what a typical viewer feels "
                           "while watching and why, and the stance")
    evidence: str = Field(description="One short quote or paraphrase from the package that justifies "
                          "the affect scores")
    negative_affect: int = Field(description="Sadness, heaviness, despair, fear, anger or disgust "
                                 + AFFECT_SCALE + "Content about sadness or depression scores higher "
                                 "than positive_affect unless purely clinical or about recovery.")
    positive_affect: int = Field(description="Joy, warmth, amusement, awe, hope or relief "
                                 + AFFECT_SCALE)
    arousal: int = Field(description="Energy of the content: 1 still or sleepy, 2 calm, 3 moderate, "
                         "4 lively, 5 frantic or intense")
    stance: Stance = Field(description="How the clip relates to depressive themes")
    hopeful: bool = Field(description="Shows recovery, progress, kindness or possibility")

    @property
    def valence(self) -> int:
        """1 very negative .. 5 very positive, derived from the two affect scores.

        Net affect (-3..3) maps linearly onto 1..5: equal affect is 3, one point more
        negative than positive is 2, and only 3-vs-0 reaches 1 or 5.
        """
        net = self.positive_affect - self.negative_affect
        return min(5, max(1, round(3 + net * 2 / 3)))

    def clamped(self) -> "ClipScores":
        """A copy with every score forced into its documented range (models occasionally overshoot)."""
        bounded = {k: min(3, max(0, getattr(self, k))) for k in ("negative_affect", "positive_affect")}
        return self.model_copy(update=bounded | {"arousal": min(5, max(1, self.arousal))})
