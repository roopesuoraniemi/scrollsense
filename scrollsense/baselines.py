"""BaselineStore on the local filesystem."""
from pathlib import Path
from threading import Lock

from .drift.core import BaselineMark
from .ports import BaselineStore
from .views import ViewerId


class JsonBaselineStore(BaselineStore):
    """One `<viewer>.baseline.json` file per viewer in `directory` (the view-log folder),
    created if missing. Writes replace the file atomically; thread-safe within one process."""

    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.__directory = directory
        self.__lock = Lock()

    def mark(self, viewer: ViewerId, mark: BaselineMark) -> None:
        path = self.__path(viewer)
        staging = path.with_suffix(".tmp")
        with self.__lock:
            staging.write_text(mark.model_dump_json(indent=2), encoding="utf-8")
            staging.replace(path)

    def mark_of(self, viewer: ViewerId) -> BaselineMark | None:
        path = self.__path(viewer)
        with self.__lock:
            text = path.read_text(encoding="utf-8") if path.exists() else None
        return BaselineMark.model_validate_json(text) if text is not None else None

    def clear(self, viewer: ViewerId) -> None:
        with self.__lock:
            self.__path(viewer).unlink(missing_ok=True)

    def __path(self, viewer: ViewerId) -> Path:
        return self.__directory / f"{viewer.value}.baseline.json"
