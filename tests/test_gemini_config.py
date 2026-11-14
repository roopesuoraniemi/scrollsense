import pytest

from scrollsense.gemini import GeminiConfig
from scrollsense.prompts import quick_prompt
from scrollsense.schemas import QuickAnalysis


def test_one_call_is_the_default_with_flash_lite_thinking() -> None:
    assert GeminiConfig.from_env({}) == GeminiConfig(model="gemini-3.5-flash-lite", pipeline="one_call",
                                                     thinking_off=False)


def test_thinking_can_be_turned_off() -> None:
    env = {"GEMINI_MODEL": "gemini-3.1-flash-lite", "GEMINI_THINKING_OFF": "1"}
    assert GeminiConfig.from_env(env).thinking_off is True


def test_two_stage_defaults_to_hydrogen_and_model_overrides() -> None:
    assert GeminiConfig.from_env({"GEMINI_PIPELINE": "two_stage"}).model == "gemini-4-hydrogen"
    assert GeminiConfig.from_env({"GEMINI_MODEL": "gemini-3.8-flash"}).model == "gemini-3.8-flash"


def test_unknown_pipeline_is_rejected() -> None:
    with pytest.raises(ValueError):
        GeminiConfig.from_env({"GEMINI_PIPELINE": "three_stage"})


def test_quick_analysis_splits_into_package_and_clamped_scores() -> None:
    quick = QuickAnalysis(title="t", format="meme", main_message="m", intended_meaning="i",
                          emotional_cues="c", people_present=False, language="en", rationale="r",
                          evidence="e", negative_affect=5, positive_affect=0, arousal=9,
                          stance="unrelated", hopeful=False)
    analysed = quick.analysed()
    assert analysed.package.title == "t" and analysed.package.transcript == ""
    assert (analysed.scores.negative_affect, analysed.scores.arousal) == (3, 5)


def test_quick_prompt_has_the_people_rules_and_scales() -> None:
    prompt = quick_prompt()
    assert "Never infer or describe the emotions" in prompt and "Arousal 1-5" in prompt
    assert "{" not in prompt
