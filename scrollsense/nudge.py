"""Patient nudges as pure values and a pure policy.

A *support* nudge asks "How do these videos feel right now?" and offers a break when a viewer's
feed has stayed at drift level `warning` (affect drift, see `drift`).
It is the only patient-facing card: there are no crisis or suicide alerts, because the feed
signal is not reliable enough for that kind of alert.
Patient-facing text never names a diagnosis, a mood or any video's content; the clinician-facing `reason`
stays off the phone (`NudgeCard`).

Research prototype, not a medical device. Every number comes from `NudgeSettings`.
"""
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import Field, model_validator

from .drift.core import DriftReport, TimelinePoint
from .schemas import Frozen

# Only "support" is issued; kept as a field for API stability (clients read `card.kind`).
NudgeKind = Literal["support"]
# close: just close the card; leave: pause the video and close the feed (the tab if allowed,
# else a blank page).
Action = Literal["close", "leave"]
NudgeState = Literal["open", "answered", "expired"]
OK_CHOICE = "ok"
HOUR_S = 3_600
DAY_H = 24

SUPPORT_TITLE = "How do these videos feel right now?"
SUPPORT_MESSAGE = ""
# No "refresh my feed" option on purpose: steering the feed would erase the very signal
# the drift detector reads.

ENV_VARS: dict[str, str] = {
    "enabled": "SCROLLSENSE_NUDGE_ENABLED",
    "streak": "SCROLLSENSE_NUDGE_STREAK",
    "cooldown_s": "SCROLLSENSE_NUDGE_COOLDOWN_S",
    "ok_factor": "SCROLLSENSE_NUDGE_OK_FACTOR",
    "expire_s": "SCROLLSENSE_NUDGE_EXPIRE_S",
    "quiet_from": "SCROLLSENSE_NUDGE_QUIET_FROM",
    "quiet_to": "SCROLLSENSE_NUDGE_QUIET_TO",
    "tz_offset_min": "SCROLLSENSE_NUDGE_TZ_OFFSET_MIN",
}


class NudgeSettings(Frozen):
    """When nudges fire and what the cards offer. Demo defaults; product values are longer.

    A support nudge needs the last `streak` judged timeline points at `warning` and at least
    `cooldown_s` since the last support nudge (times `ok_factor` if that one was answered
    "I'm OK"). Quiet hours, local time at `tz_offset_min` east of UTC, run from `quiet_from`
    to `quiet_to` (hours, may wrap midnight); off unless both are set. Unanswered nudges
    expire after `expire_s`.
    Raises ValueError if only one quiet bound is set.
    """

    enabled: bool = True
    streak: int = Field(default=1, ge=1)
    cooldown_s: float = Field(default=600.0, ge=0)
    ok_factor: float = Field(default=2.0, ge=1)
    expire_s: float = Field(default=900.0, gt=0)
    quiet_from: int | None = Field(default=None, ge=0, lt=DAY_H)
    quiet_to: int | None = Field(default=None, ge=0, lt=DAY_H)
    tz_offset_min: int = 120

    @model_validator(mode="after")
    def __quiet_bounds_paired(self) -> "NudgeSettings":
        if (self.quiet_from is None) != (self.quiet_to is None):
            raise ValueError("Set both SCROLLSENSE_NUDGE_QUIET_FROM and _QUIET_TO, or neither")
        return self

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "NudgeSettings":
        """The defaults, overridden by each of `ENV_VARS` that is set and non-empty in `env`.
        Raises ValueError on a malformed value."""
        return cls.model_validate({field: env[name] for field, name in ENV_VARS.items()
                                   if env.get(name)})

    def quiet_at(self, now: float) -> bool:
        if self.quiet_from is None or self.quiet_to is None:
            return False
        hour = int((now + 60 * self.tz_offset_min) // HOUR_S) % DAY_H
        if self.quiet_from <= self.quiet_to:
            return self.quiet_from <= hour < self.quiet_to
        return hour >= self.quiet_from or hour < self.quiet_to

    def support_template(self) -> "CardTemplate":
        return CardTemplate(kind="support", title=SUPPORT_TITLE, message=SUPPORT_MESSAGE,
                            options=self.__support_options())

    def __support_options(self) -> tuple["NudgeOption", ...]:
        return (
            NudgeOption(choice=OK_CHOICE, label="I'm OK", action="close"),
            NudgeOption(choice="take_break", label="I want to take a break", action="leave"),
            NudgeOption(choice="not_now", label="Not now", action="close"))


class NudgeOption(Frozen):
    """One button. `choice` is what a tap records; `action` is what the phone does."""

    choice: str
    label: str
    action: Action


class NudgeCard(Frozen):
    """What the phone shows. Holds nothing clinical: no reason, score or video.

    `kind` is read back from the log, which may hold cards of kinds no longer issued, so it is
    a plain string here; new cards are always "support" (`NudgeKind`)."""

    id: str
    kind: str
    title: str
    message: str
    options: tuple[NudgeOption, ...]
    expires_at: float


class CardTemplate(Frozen):
    """A card's fixed content, before it gets an id and an expiry."""

    kind: NudgeKind
    title: str
    message: str
    options: tuple[NudgeOption, ...]

    def issue(self, now: float, ttl_s: float) -> NudgeCard:
        """The card issued at `now`; ids are unique per kind to the millisecond."""
        return NudgeCard(id=f"{self.kind}-{int(now * 1000)}", kind=self.kind, title=self.title,
                         message=self.message, options=self.options, expires_at=now + ttl_s)


class Nudge(Frozen):
    """An issued card, with what triggered it (`reason`; `video_id` is None for support cards)."""

    viewer: str
    created_at: float
    reason: str
    video_id: str | None
    card: NudgeCard

    @property
    def id(self) -> str:
        return self.card.id


class NudgeResponse(Frozen):
    """The patient's tap on `nudge_id` at `at` (epoch seconds)."""

    nudge_id: str
    choice: str
    at: float


class NudgeError(Exception):
    """A response that cannot be recorded."""


class UnknownNudge(NudgeError, LookupError):
    pass


class AlreadyAnswered(NudgeError):
    pass


class BadChoice(NudgeError, ValueError):
    pass


class NudgeEntry(Frozen):
    nudge: Nudge
    response: NudgeResponse | None

    def state(self, now: float) -> NudgeState:
        if self.response is not None:
            return "answered"
        return "open" if now < self.nudge.card.expires_at else "expired"

    def answer(self, choice: str, at: float) -> NudgeResponse:
        """Raises AlreadyAnswered if answered before, BadChoice unless `choice` is one of the
        card's options. A late answer to an expired card is still accepted."""
        if self.response is not None:
            raise AlreadyAnswered(f"Nudge {self.nudge.id} was already answered")
        if choice not in {o.choice for o in self.nudge.card.options}:
            raise BadChoice(f"{choice!r} is not an option of nudge {self.nudge.id}")
        return NudgeResponse(nudge_id=self.nudge.id, choice=choice, at=at)


class NudgeHistory(Frozen):
    """One viewer's nudges in issue order, each with its response if any."""

    entries: tuple[NudgeEntry, ...] = ()

    @classmethod
    def fold(cls, nudges: Sequence[Nudge], responses: Sequence[NudgeResponse]) -> "NudgeHistory":
        """Joins each nudge with its first response; responses to unknown ids are dropped."""
        first: dict[str, NudgeResponse] = {}
        for response in responses:
            first.setdefault(response.nudge_id, response)
        return cls(entries=tuple(NudgeEntry(nudge=n, response=first.get(n.id)) for n in nudges))

    def entry(self, nudge_id: str) -> NudgeEntry | None:
        return next((e for e in self.entries if e.nudge.id == nudge_id), None)

    def newest_open(self, now: float) -> Nudge | None:
        return next((e.nudge for e in reversed(self.entries) if e.state(now) == "open"), None)

    def last_support(self) -> NudgeEntry | None:
        return next((e for e in reversed(self.entries) if e.nudge.card.kind == "support"), None)


def warning_streak(timeline: Sequence[TimelinePoint], n: int) -> bool:
    """Whether the last `n` judged (not `learning`) points are all at `warning`."""
    judged = [p.level for p in timeline if p.level != "learning"]
    return len(judged) >= n and all(level == "warning" for level in judged[-n:])


class NudgePolicy:
    """Decides whether a nudge is due. Holds only settings: every method is pure."""

    def __init__(self, settings: NudgeSettings) -> None:
        self.__settings = settings

    def decide(self, report: DriftReport, history: NudgeHistory, now: float) -> Nudge | None:
        """A new support nudge for `report.viewer` at `now`, or None. It waits while any card
        is open."""
        if self.__settings.enabled and self.__support_due(report, history, now):
            return self.__support(report, now)
        return None

    def __support_due(self, report: DriftReport, history: NudgeHistory, now: float) -> bool:
        settings = self.__settings
        return (warning_streak(report.timeline, settings.streak) and not settings.quiet_at(now)
                and history.newest_open(now) is None and self.__cooled(history, now))

    def __cooled(self, history: NudgeHistory, now: float) -> bool:
        last = history.last_support()
        if last is None:
            return True
        declined = last.response is not None and last.response.choice == OK_CHOICE
        factor = self.__settings.ok_factor if declined else 1.0
        return now - last.nudge.created_at >= self.__settings.cooldown_s * factor

    def __support(self, report: DriftReport, now: float) -> Nudge:
        reason = (f"Drift warning on the last {self.__settings.streak} judged points "
                  f"({report.score or 0.0:.1f} SD into the bottom left)")
        return Nudge(viewer=report.viewer, created_at=now, reason=reason, video_id=None,
                     card=self.__settings.support_template().issue(now, self.__settings.expire_s))
