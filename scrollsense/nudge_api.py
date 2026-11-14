"""Nudges at the edge: issuing them as batches arrive, recording answers, and the HTTP routes."""
from threading import Lock
from typing import Callable

from fastapi import APIRouter, HTTPException, Response
from pydantic import Field

from .drift_api import ViewerDrift
from .nudge import (AlreadyAnswered, BadChoice, Nudge, NudgeCard, NudgeEntry, NudgeHistory,
                    NudgePolicy, NudgeResponse, NudgeState, UnknownNudge)
from .ports import NudgeLog, Nudger
from .schemas import Frozen
from .views import ViewerId


class NudgeJudge:
    """Applies the policy to a viewer's current drift report."""

    def __init__(self, drift: ViewerDrift, policy: NudgePolicy) -> None:
        self.__drift = drift
        self.__policy = policy

    def due(self, viewer: ViewerId, history: NudgeHistory, now: float) -> Nudge | None:
        return self.__policy.decide(self.__drift.report(viewer), history, now)

    def cooldown_remaining(self, entry: NudgeEntry, now: float) -> float:
        if entry.response is None or entry.nudge.card.kind != "support":
            return 0.0
        return max(0.0, self.__policy.cooldown_until(entry) - now)


class NudgeHistoryItem(Frozen):
    """One issued nudge for the clinician view: the full nudge, the answer if any,
    whether it is still `open`, `answered` or `expired`, and remaining cooldown seconds."""

    nudge: Nudge
    response: NudgeResponse | None
    state: NudgeState
    cooldown_remaining_s: float = 0.0

    @classmethod
    def of(cls, entry: NudgeEntry, now: float,
           cooldown_remaining_s: float = 0.0) -> "NudgeHistoryItem":
        return cls(nudge=entry.nudge, response=entry.response, state=entry.state(now),
                   cooldown_remaining_s=cooldown_remaining_s)


class NudgeDesk(Nudger):
    """Issues, answers and lists nudges. One lock makes decide-and-record and
    check-and-answer atomic."""

    def __init__(self, log: NudgeLog, judge: NudgeJudge, clock: Callable[[], float]) -> None:
        self.__log = log
        self.__judge = judge
        self.__clock = clock
        self.__lock = Lock()

    def issue_if_due(self, viewer: ViewerId) -> NudgeCard | None:
        now = self.__clock()
        with self.__lock:
            history = self.__log.history(viewer)
            issued = self.__judge.due(viewer, history, now)
            if issued is not None:
                self.__log.record(issued)
        shown = issued or history.newest_open(now)
        return shown.card if shown else None

    def respond(self, viewer: ViewerId, nudge_id: str, choice: str) -> None:
        """Record `viewer`'s `choice` on nudge `nudge_id`. Raises UnknownNudge, AlreadyAnswered,
        or BadChoice (not one of the card's options)."""
        with self.__lock:
            entry = self.__log.history(viewer).entry(nudge_id)
            if entry is None:
                raise UnknownNudge(f"No nudge {nudge_id!r} for {viewer}")
            self.__log.respond(viewer, entry.answer(choice, self.__clock()))

    def history(self, viewer: ViewerId) -> tuple[NudgeHistoryItem, ...]:
        """`viewer`'s nudges, newest first."""
        now = self.__clock()
        entries = self.__log.history(viewer).entries
        return tuple(NudgeHistoryItem.of(e, now, self.__judge.cooldown_remaining(e, now))
                     for e in reversed(entries))

    def erase(self, viewer: ViewerId) -> None:
        with self.__lock:
            self.__log.erase(viewer)


class ChoiceBody(Frozen):
    choice: str = Field(min_length=1, max_length=64)


class NudgeApi:
    """Routes under /api for the phone's taps and the clinician's nudge history."""

    def __init__(self, desk: NudgeDesk) -> None:
        self.__desk = desk

    def router(self) -> APIRouter:
        router = APIRouter(prefix="/api")
        router.add_api_route("/viewers/{viewer}/nudges", self.history, methods=["GET"])
        router.add_api_route("/viewers/{viewer}/nudges/{nudge_id}/response", self.respond,
                             methods=["POST"], status_code=204, response_class=Response)
        return router

    def history(self, viewer: str) -> tuple[NudgeHistoryItem, ...]:
        return self.__desk.history(self.__viewer(viewer))

    def respond(self, viewer: str, nudge_id: str, body: ChoiceBody) -> Response:
        """204; 404 unknown nudge, 409 already answered, 422 not one of the card's options."""
        try:
            self.__desk.respond(self.__viewer(viewer), nudge_id, body.choice)
        except UnknownNudge as error:
            raise HTTPException(404, str(error)) from error
        except AlreadyAnswered as error:
            raise HTTPException(409, str(error)) from error
        except BadChoice as error:
            raise HTTPException(422, str(error)) from error
        return Response(status_code=204)

    @staticmethod
    def __viewer(text: str) -> ViewerId:
        try:
            return ViewerId(text)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
