"""NudgeLog on the local filesystem."""
from pathlib import Path
from threading import Lock

from .nudge import Nudge, NudgeHistory, NudgeResponse
from .ports import NudgeLog
from .schemas import Frozen
from .views import ViewerId


class NudgeLine(Frozen):
    """One line of the log: an issued nudge or a response, never both."""

    nudge: Nudge | None = None
    response: NudgeResponse | None = None


class JsonlNudgeLog(NudgeLog):
    """One append-only `<viewer>.nudges.jsonl` file per viewer in `directory` (the view-log
    folder), created if missing. Thread-safe within one process."""

    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.__directory = directory
        self.__lock = Lock()

    def record(self, nudge: Nudge) -> None:
        self.__append(ViewerId(nudge.viewer), NudgeLine(nudge=nudge))

    def respond(self, viewer: ViewerId, response: NudgeResponse) -> None:
        self.__append(viewer, NudgeLine(response=response))

    def history(self, viewer: ViewerId) -> NudgeHistory:
        path = self.__path(viewer)
        with self.__lock:
            text = path.read_text(encoding="utf-8") if path.exists() else ""
        lines = [NudgeLine.model_validate_json(line) for line in text.splitlines() if line.strip()]
        return NudgeHistory.fold([n.nudge for n in lines if n.nudge is not None],
                                 [n.response for n in lines if n.response is not None])

    def erase(self, viewer: ViewerId) -> None:
        with self.__lock:
            self.__path(viewer).unlink(missing_ok=True)

    def __append(self, viewer: ViewerId, line: NudgeLine) -> None:
        with self.__lock, self.__path(viewer).open("a", encoding="utf-8") as file:
            file.write(line.model_dump_json() + "\n")

    def __path(self, viewer: ViewerId) -> Path:
        return self.__directory / f"{viewer.value}.nudges.jsonl"
