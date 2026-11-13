"""ContentAnalyser backed by the Gemini API."""
import os
from dataclasses import dataclass
from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from .domain import AnalyserLabel, VideoId
from .ports import ContentAnalyser
from .prompts import DESCRIBE_PROMPT, package_text, scoring_prompt
from .schemas import ClipScores, TextPackage

Parsed = TypeVar("Parsed", bound=BaseModel)


@dataclass(frozen=True)
class GeminiConfig:
    model: str
    embed_model: str


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
        return AnalyserLabel(name=self.__config.model, embed_name=self.__config.embed_model,
                             mock=False)

    def describe(self, video: VideoId) -> TextPackage:
        contents = types.Content(role="user", parts=[
            types.Part(file_data=types.FileData(file_uri=video.watch_url)),
            types.Part(text=DESCRIBE_PROMPT),
        ])
        return self.__generate(contents, TextPackage)

    def score(self, package: TextPackage) -> ClipScores:
        return self.__generate(scoring_prompt(package), ClipScores).clamped()

    def embed(self, package: TextPackage) -> tuple[float, ...]:
        response = self.__client.models.embed_content(
            model=self.__config.embed_model, contents=package_text(package),
            config=types.EmbedContentConfig(task_type="CLUSTERING"))
        return tuple((response.embeddings or [])[0].values or ())

    def __generate(self, contents: types.ContentListUnion, schema: type[Parsed]) -> Parsed:
        config = types.GenerateContentConfig(response_mime_type="application/json",
                                             response_schema=schema, temperature=0.2)
        response = self.__client.models.generate_content(
            model=self.__config.model, contents=contents, config=config)
        parsed = response.parsed
        return parsed if isinstance(parsed, schema) else schema.model_validate_json(response.text or "")
