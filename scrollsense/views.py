"""Pure values for viewing activity: who saw which video, when, and for how long."""
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal, Sequence

from pydantic import field_validator, model_validator

from .domain import VideoId
from .schemas import Frozen

Source = Literal["shorts_web", "takeout", "portability", "manual"]
Surface = Literal["shorts", "watch", "other"]

# A swipe back to the same Short, or a client retrying a flush, is not a second exposure.
REPEAT_WINDOW_S = 30.0
SECONDS_PER_DAY = 86_400


@dataclass(frozen=True)
class ViewerId:
    """A pseudonymous viewer such as `patient-01`: 3-32 of `a-z`, `0-9` and `-`.

    Raises ValueError on construction otherwise. Never a real name or account handle.
    """

    value: str

    __PATTERN = re.compile(r"[a-z0-9-]{3,32}")

    def __post_init__(self) -> None:
        if not self.__PATTERN.fullmatch(self.value):
            raise ValueError(f"Not a viewer pseudonym ([a-z0-9-]{{3,32}}): {self.value!r}")

    def __str__(self) -> str:
        return self.value


class Window(Frozen):
    """The half-open time span [start, end) in epoch seconds. Raises ValueError if end < start."""

    start: float
    end: float

    @model_validator(mode="after")
    def __ordered(self) -> "Window":
        if self.end < self.start:
            raise ValueError(f"Window ends before it starts: {self.start} > {self.end}")
        return self

    def contains(self, moment: float) -> bool:
        return self.start <= moment < self.end


EVER = Window(start=-math.inf, end=math.inf)


class ViewEvent(Frozen):
    """One video shown to one viewer. `seen_at` is epoch seconds (UTC); `tz_offset_min` is the
    viewer's offset east of UTC, so local time is `seen_at + 60 * tz_offset_min`."""

    event_id: str
    viewer: str
    video_id: str
    seen_at: float
    tz_offset_min: int = 0
    dwell_s: float | None = None
    duration_s: float | None = None
    loops: int | None = None
    source: Source = "shorts_web"
    surface: Surface = "shorts"

    @field_validator("viewer")
    @classmethod
    def __pseudonym(cls, value: str) -> str:
        return ViewerId(value).value

    @field_validator("video_id")
    @classmethod
    def __video_id(cls, value: str) -> str:
        return VideoId(value).value

    @property
    def video(self) -> VideoId:
        return VideoId(self.video_id)

    @property
    def local_hour(self) -> float:
        """Hour of the viewer's local day, 0 <= h < 24."""
        return ((self.seen_at + 60 * self.tz_offset_min) % SECONDS_PER_DAY) / 3600

    def repeats(self, earlier: "ViewEvent") -> bool:
        """Whether this event duplicates `earlier`: same event id, or the same viewer and
        video within REPEAT_WINDOW_S either way."""
        same_view = (self.viewer, self.video_id) == (earlier.viewer, earlier.video_id)
        return self.event_id == earlier.event_id or (
            same_view and abs(self.seen_at - earlier.seen_at) < REPEAT_WINDOW_S)



class ViewInput(Frozen):
    """One event as a client sends it: the viewer comes from the batch, and the video from
    either `video_id` or a `url` (any form `VideoId.parse` accepts)."""

    event_id: str
    video_id: str | None = None
    url: str | None = None
    seen_at: float
    tz_offset_min: int = 0
    dwell_s: float | None = None
    duration_s: float | None = None
    loops: int | None = None
    source: Source = "shorts_web"
    surface: Surface = "shorts"

    def event(self, viewer: ViewerId) -> ViewEvent:
        """The validated event. Raises ValueError if neither field names a YouTube video."""
        if not (self.video_id or self.url):
            raise ValueError("needs video_id or url")
        video = VideoId.parse(self.video_id or self.url or "")
        return ViewEvent(viewer=viewer.value, video_id=video.value,
                         **self.model_dump(exclude={"video_id", "url"}))


class ViewBatch(Frozen):
    """A client's flush: events for one viewer."""

    viewer: str
    events: tuple[ViewInput, ...]


class Rejection(Frozen):
    event_id: str
    reason: str


class Parsed(Frozen):
    """A batch split into valid events (in input order) and rejections."""

    events: tuple[ViewEvent, ...]
    rejected: tuple[Rejection, ...]


def parse_events(viewer: ViewerId, inputs: Sequence[ViewInput]) -> Parsed:
    """Validate each input on its own, so one bad event never sinks the batch."""
    events: list[ViewEvent] = []
    rejected: list[Rejection] = []
    for item in inputs:
        try:
            events.append(item.event(viewer))
        except ValueError as error:
            rejected.append(Rejection(event_id=item.event_id, reason=str(error)))
    return Parsed(events=tuple(events), rejected=tuple(rejected))


class __Seen:
    """Index of kept events, so dedupe stays linear in the number of events."""

    def __init__(self) -> None:
        self.__ids: set[str] = set()
        self.__by_view: defaultdict[tuple[str, str], list[ViewEvent]] = defaultdict(list)

    def admits(self, event: ViewEvent) -> bool:
        same_view = self.__by_view[(event.viewer, event.video_id)]
        return event.event_id not in self.__ids and not any(event.repeats(e) for e in same_view)

    def add(self, event: ViewEvent) -> None:
        self.__ids.add(event.event_id)
        self.__by_view[(event.viewer, event.video_id)].append(event)


def dedupe(events: Sequence[ViewEvent]) -> tuple[ViewEvent, ...]:
    """`events` in input order without repeats (see `ViewEvent.repeats`); the first one wins."""
    seen = __Seen()
    kept: list[ViewEvent] = []
    for event in events:
        if seen.admits(event):
            seen.add(event)
            kept.append(event)
    return tuple(kept)


def fresh(logged: Sequence[ViewEvent], incoming: Sequence[ViewEvent]) -> tuple[ViewEvent, ...]:
    """The incoming events that repeat neither a logged event nor an earlier incoming one."""
    logged_ids = {e.event_id for e in logged}
    return tuple(e for e in dedupe([*logged, *incoming]) if e.event_id not in logged_ids)
