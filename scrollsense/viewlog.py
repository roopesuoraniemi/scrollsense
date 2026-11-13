"""ViewLog on the local filesystem."""
from itertools import groupby
from operator import attrgetter
from pathlib import Path
from threading import Lock
from typing import Sequence

from .ports import ViewLog
from .views import ViewerId, ViewEvent, Window


class JsonlViewLog(ViewLog):
    """One append-only `<viewer>.jsonl` file per viewer in `directory`, created if missing.

    Thread-safe within one process; not safe for two processes sharing the directory.
    Reads scan the whole file, which is fine at prototype scale (thousands of events).
    """

    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.__directory = directory
        self.__lock = Lock()

    def append(self, events: Sequence[ViewEvent]) -> None:
        by_viewer = attrgetter("viewer")
        with self.__lock:
            for viewer, group in groupby(sorted(events, key=by_viewer), key=by_viewer):
                with self.__path(viewer).open("a", encoding="utf-8") as file:
                    file.writelines(e.model_dump_json() + "\n" for e in group)

    def between(self, viewer: ViewerId, window: Window) -> tuple[ViewEvent, ...]:
        with self.__lock:
            lines = self.__lines(viewer.value)
        events = (ViewEvent.model_validate_json(line) for line in lines if line.strip())
        return tuple(e for e in events if window.contains(e.seen_at))

    def viewers(self) -> tuple[ViewerId, ...]:
        with self.__lock:
            return tuple(ViewerId(p.stem) for p in sorted(self.__directory.glob("*.jsonl")))

    def erase(self, viewer: ViewerId) -> None:
        with self.__lock:
            self.__path(viewer.value).unlink(missing_ok=True)

    def __lines(self, viewer: str) -> list[str]:
        path = self.__path(viewer)
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def __path(self, viewer: str) -> Path:
        return self.__directory / f"{viewer}.jsonl"

