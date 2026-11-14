"""ContentAnalysers backed by the Gemini API: one call that watches and scores (fast), or two
stages, describe then score from the text (slower, with a full transcript)."""
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from .domain import AnalyserLabel, Stage, VideoId
from .ports import ContentAnalyser, Progress
from .prompts import DESCRIBE_PROMPT, PARAPHRASE_PROMPT, quick_prompt, scoring_prompt
from .schemas import Analysed, ClipScores, QuickAnalysis, TextPackage

Parsed = TypeVar("Parsed", bound=BaseModel)
Pipeline = Literal["one_call", "two_stage"]
DEFAULT_MODELS: dict[str, str] = {"one_call": "gemini-3.5-flash-lite", "two_stage": "gemini-4-hydrogen"}


class GenerationBlocked(RuntimeError):
    """Gemini returned no usable structured output (e.g. blocked for recitation, or invalid JSON)."""


@dataclass(frozen=True)
class GeminiConfig:
    """`pipeline` one_call: low video resolution, about 2 s per Short with gemini-3.5-flash-lite
    (as fast with gemini-3.1-flash-lite and `thinking_off`, but less perceptive). two_stage:
    full resolution, about 20-30 s with gemini-4-hydrogen. `thinking_off` applies to one_call
    only; some models reject it (gemini-3.5-flash-lite does)."""

    model: str
    pipeline: Pipeline = "one_call"
    thinking_off: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "GeminiConfig":
        """`GEMINI_PIPELINE` one_call (default) or two_stage; `GEMINI_MODEL` overrides the
        pipeline's default model; `GEMINI_THINKING_OFF=1` turns thinking off (one_call).
        Raises ValueError on an unknown pipeline."""
        pipeline = env.get("GEMINI_PIPELINE", "one_call")
        if pipeline not in DEFAULT_MODELS:
            raise ValueError(f"GEMINI_PIPELINE must be one_call or two_stage, not {pipeline!r}")
        chosen: Pipeline = "one_call" if pipeline == "one_call" else "two_stage"
        return cls(model=env.get("GEMINI_MODEL") or DEFAULT_MODELS[pipeline], pipeline=chosen,
                   thinking_off=env.get("GEMINI_THINKING_OFF") == "1")


class GeminiCaller:
    """Structured-output calls to one model. Reads public YouTube URLs directly, so no video
    is downloaded. Needs GEMINI_API_KEY (or GOOGLE_API_KEY); raises RuntimeError without one."""

    def __init__(self, model: str, fast: bool, thinking_off: bool = False) -> None:
        if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
            raise RuntimeError("GEMINI_API_KEY is not set: copy .env.example to .env, "
                               "or run with SCROLLSENSE_MOCK=1")
        self.model = model
        self.__fast = fast
        self.__thinking_off = thinking_off
        self.__client = genai.Client()

    @staticmethod
    def watching(video: VideoId, prompt: str) -> types.Content:
        return types.Content(role="user", parts=[
            types.Part(file_data=types.FileData(file_uri=video.watch_url)),
            types.Part(text=prompt),
        ])

    def generate(self, contents: types.ContentListUnion, schema: type[Parsed]) -> Parsed:
        """Raises GenerationBlocked if the answer does not parse as `schema`."""
        response = self.__client.models.generate_content(
            model=self.model, contents=contents, config=self.__config(schema))
        if isinstance(response.parsed, schema):
            return response.parsed
        try:
            return schema.model_validate_json(response.text or "")
        except ValidationError as error:
            raise GenerationBlocked(f"{_finish_reason(response)}: {error.error_count()} errors") from error

    def __config(self, schema: type[BaseModel]) -> types.GenerateContentConfig:
        fast = {"media_resolution": types.MediaResolution.MEDIA_RESOLUTION_LOW} if self.__fast else {}
        if self.__thinking_off:
            fast["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        return types.GenerateContentConfig(response_mime_type="application/json",
                                           response_schema=schema, temperature=0.2, **fast)


class OneCallAnalyser(ContentAnalyser):
    """Watches the video and returns a short description plus the scores in one call."""

    def __init__(self, caller: GeminiCaller) -> None:
        self.__caller = caller

    @property
    def label(self) -> AnalyserLabel:
        return AnalyserLabel(name=self.__caller.model, mock=False)

    def analyse(self, video: VideoId, progress: Progress) -> Analysed:
        progress(Stage.SCORING)
        contents = self.__caller.watching(video, quick_prompt())
        try:
            return self.__caller.generate(contents, QuickAnalysis).analysed()
        except GenerationBlocked:  # rare (recitation or malformed JSON) and usually transient
            return self.__caller.generate(contents, QuickAnalysis).analysed()


class TwoStageAnalyser(ContentAnalyser):
    """Describes the video as a full text package, then scores the text in a second call."""

    def __init__(self, caller: GeminiCaller) -> None:
        self.__caller = caller

    @property
    def label(self) -> AnalyserLabel:
        return AnalyserLabel(name=self.__caller.model, mock=False)

    def analyse(self, video: VideoId, progress: Progress) -> Analysed:
        progress(Stage.DESCRIBING)
        package = self.__describe(video)
        progress(Stage.SCORING)
        return Analysed(package=package, scores=self.__score(package))

    def __describe(self, video: VideoId) -> TextPackage:
        try:
            return self.__caller.generate(self.__caller.watching(video, DESCRIBE_PROMPT), TextPackage)
        except GenerationBlocked:  # usually recitation of lyrics or speech: retry without quoting
            return self.__caller.generate(self.__caller.watching(video, PARAPHRASE_PROMPT), TextPackage)

    def __score(self, package: TextPackage) -> ClipScores:
        prompt = scoring_prompt(package)
        try:
            return self.__caller.generate(prompt, ClipScores).clamped()
        except GenerationBlocked:  # a malformed answer is rare and usually transient
            return self.__caller.generate(prompt, ClipScores).clamped()


def gemini_analyser(config: GeminiConfig) -> ContentAnalyser:
    """The analyser for `config.pipeline`. Raises RuntimeError without an API key."""
    if config.pipeline == "one_call":
        return OneCallAnalyser(GeminiCaller(config.model, fast=True, thinking_off=config.thinking_off))
    return TwoStageAnalyser(GeminiCaller(config.model, fast=False))


def _finish_reason(response: types.GenerateContentResponse) -> str:
    candidates = response.candidates or []
    return str(candidates[0].finish_reason) if candidates else "no candidates"
