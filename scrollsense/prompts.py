"""Prompt text for the describing and scoring stages. Pure: no model calls here."""
from .schemas import CRITERIA, TextPackage

# Telling the model not to assess people keeps this out of emotion recognition of
# creators, who can't be informed or consent (EU AI Act Art. 50(3)).
DESCRIBE_PROMPT = """You are building a content-analysis record for a short video.
Describe ONLY what is said, written and shown in the video, plus its music and pacing.
Do NOT guess the identity, emotions, health or mental state of any person in the video;
describe the content and its themes, not the people.
Return the fields of the schema. Keep transcript and on-screen text verbatim where possible."""

__SCORE_TEMPLATE = """You score the THEMES of a short video from its text description.
You are not assessing any person, only what the content communicates to a viewer.

DSM-5 criteria for a major depressive episode, used here as content themes:
{criteria}

Scoring for each theme: 0 absent, 1 mentioned in passing, 2 a central theme, 3 intense or glorified.
Stance:
- dwelling_or_romanticising: lingers in, validates or aestheticises the feeling without a way forward
- neutral_or_informational: describes or explains (e.g. psychoeducation) without dwelling
- coping_or_recovery: offers coping, help-seeking, recovery or hope
- unrelated: no depressive themes at all
Valence (1 very negative .. 5 very positive) and arousal (1 very calm .. 5 very energetic)
describe the content's emotional tone and energy.
Suicide-prevention or help-line content mentioning suicide still gets an A9 score, with stance coping_or_recovery.

TEXT PACKAGE:
{package}"""


def package_text(package: TextPackage) -> str:
    """The package as plain text, the form both scoring and embedding read."""
    return (f"Title: {package.title}\nFormat: {package.format}\n"
            f"Main message: {package.main_message}\nTranscript: {package.transcript}\n"
            f"On-screen text: {package.on_screen_text}\n"
            f"Visuals: {package.visual_description}\nAudio: {package.audio_description}")


def scoring_prompt(package: TextPackage) -> str:
    """The stage-2 prompt for `package`."""
    criteria = "\n".join(f"- {c.code} {c.label}: {c.theme}" for c in CRITERIA)
    return __SCORE_TEMPLATE.format(criteria=criteria, package=package_text(package))
