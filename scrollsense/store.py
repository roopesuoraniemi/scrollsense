"""AnalysisStore on the local filesystem."""
from pathlib import Path

from .domain import ClipAnalysis, VideoId
from .ports import AnalysisStore


class JsonFileStore(AnalysisStore):
    """One `<video id>.json` file per analysis in `directory`, created if missing.

    Not safe for two writers saving the same video at once.
    """

    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.__directory = directory

    def load(self, video: VideoId) -> ClipAnalysis | None:
        path = self.__path(video.value)
        return ClipAnalysis.model_validate_json(path.read_text()) if path.exists() else None

    def list_all(self) -> tuple[ClipAnalysis, ...]:
        analyses = (ClipAnalysis.model_validate_json(p.read_text())
                    for p in self.__directory.glob("*.json"))
        return tuple(sorted(analyses, key=lambda a: a.created))

    def save(self, analysis: ClipAnalysis) -> None:
        self.__path(analysis.video_id).write_text(analysis.model_dump_json(indent=2))

    def __path(self, video_id: str) -> Path:
        return self.__directory / f"{video_id}.json"
