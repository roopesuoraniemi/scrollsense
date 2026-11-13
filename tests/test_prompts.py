from scrollsense.domain import VideoId
from scrollsense.prompts import DESCRIBE_PROMPT, package_text, scoring_prompt
from scrollsense.schemas import SAFETY_CRITERION, ClipScores, TextPackage

from .fakes import instant_mock


def package() -> TextPackage:
    return instant_mock().describe(VideoId("dQw4w9WgXcQ")).model_copy(
        update={"intended_meaning": "IRONY-MARKER", "emotional_cues": "CUES-MARKER"})


def test_package_text_carries_meaning_and_cues() -> None:
    text = package_text(package())
    assert "Intended meaning: IRONY-MARKER" in text and "Emotional cues: CUES-MARKER" in text


def test_scoring_prompt_has_package_examples_and_euphemisms() -> None:
    prompt = scoring_prompt(package())
    assert "IRONY-MARKER" in prompt and "Calibration examples" in prompt
    assert all(word in prompt for word in ("unalive", "sewerslide", "kms", "not wanting to be here"))


def test_a9_theme_lists_euphemisms() -> None:
    assert "unalive" in SAFETY_CRITERION.theme and "disappear forever" in SAFETY_CRITERION.theme


def test_describe_prompt_allows_names_but_not_inferred_feelings() -> None:
    assert "public figure" in DESCRIBE_PROMPT and "Never infer" in DESCRIBE_PROMPT


def test_new_formats_accepted() -> None:
    for fmt in ("animation", "animals_nature"):
        assert TextPackage.model_validate(package().model_dump() | {"format": fmt}).format == fmt


def test_mock_scores_validate_against_schema() -> None:
    scores = instant_mock().score(package())
    assert ClipScores.model_validate(scores.model_dump()) == scores
    assert 0 <= scores.negative_affect <= 3 and 0 <= scores.positive_affect <= 3
    assert 1 <= scores.valence <= 5
