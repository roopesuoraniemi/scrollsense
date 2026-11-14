"""ContentAnalyser backed by the Gemini API."""
import os
from dataclasses import dataclass
from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from .domain import AnalyserLabel, VideoId
from .ports import ContentAnalyser
from .prompts import DESCRIBE_PROMPT, PARAPHRASE_PROMPT, scoring_prompt
from .schemas import ClipScores, TextPackage

Parsed = TypeVar("Parsed", bound=BaseModel)


class GenerationBlocked(RuntimeError):
    """Gemini returned no usable structured output (e.g. blocked for recitation, or invalid JSON)."""


@dataclass(frozen=True)
class GeminiConfig:
    model: str


class GeminiAnalyser(ContentAnalyser):
    """Reads public YouTube URLs directly, so no video is downloaded.

    Needs GEMINI_API_KEY (or GOOGLE_API_KEY) in the environment; raises RuntimeError
    on construction without one. Calls raise google.genai errors on API failure.
    """

    def __init__(self, config: GeminiConfig) -> None:
        if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
            raise RuntimeError("GEMINI_API_KEY is not set: copy .env.example to .env, "
                               "or run with SCROLLSENSE_MOCK=1")
        self.__config = config
        self.__client = genai.Client()

    @property
    def label(self) -> AnalyserLabel:
        return AnalyserLabel(name=self.__config.model, mock=False)

    def describe(self, video: VideoId) -> TextPackage:
        try:
            return self.__generate(self.__watch(video, DESCRIBE_PROMPT), TextPackage)
        except GenerationBlocked:  # usually recitation of lyrics or speech: retry without quoting
            return self.__generate(self.__watch(video, PARAPHRASE_PROMPT), TextPackage)

    def score(self, package: TextPackage) -> ClipScores:
        prompt = scoring_prompt(package)
        try:
            return self.__generate(prompt, ClipScores).clamped()
        except GenerationBlocked:  # a malformed answer is rare and usually transient
            return self.__generate(prompt, ClipScores).clamped()

    @staticmethod
    def __watch(video: VideoId, prompt: str) -> types.Content:
        return types.Content(role="user", parts=[
            types.Part(file_data=types.FileData(file_uri=video.watch_url)),
            types.Part(text=prompt),
        ])

    def __generate(self, contents: types.ContentListUnion, schema: type[Parsed]) -> Parsed:
        config = types.GenerateContentConfig(response_mime_type="application/json",
                                             response_schema=schema, temperature=0.2)
        response = self.__client.models.generate_content(
            model=self.__config.model, contents=contents, config=config)
        if isinstance(response.parsed, schema):
            return response.parsed
        try:
            return schema.model_validate_json(response.text or "")
        except ValidationError as error:
            raise GenerationBlocked(f"{self.__finish_reason(response)}: {error.error_count()} errors") from error

    @staticmethod
    def __finish_reason(response: types.GenerateContentResponse) -> str:
        candidates = response.candidates or []
        return str(candidates[0].finish_reason) if candidates else "no candidates"
