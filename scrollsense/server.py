"""ASGI entry point.

Run:  uv run uvicorn scrollsense.server:app --reload --port 8765
"""
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, FastAPI
from fastapi.params import Depends as Dependency
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

from .api import Api, ClipCatalog
from .affect_norms import load_affect_norms
from .auth import BearerToken
from .composition import ROOT, Settings, Wiring, wire
from .demo_api import DemoApi, ShortAdder
from .scheduling import AnalysisScheduler, CachedScheduler, LiveScheduler, RunBudget
from .drift.core import DriftDetector
from .drift_api import DriftApi, FeedObserver, ViewerDrift
from .intake import ViewerExtras, ViewIntake
from .nudge import NudgePolicy
from .nudge_api import NudgeApi, NudgeDesk, NudgeJudge
from .views_api import ViewerReports, ViewsApi


def create_app(settings: Settings) -> FastAPI:
    """The web app: JSON API under /api (Bearer-guarded when a token is set), the static UI
    at /. Starts the analysis queue's worker threads."""
    wiring = wire(settings)
    wiring.queue.start(settings.queue.workers)
    guard = __guard(settings.token)
    app = FastAPI(title="ScrollSense")
    for router in __routers(wiring, settings):
        app.include_router(router, dependencies=guard)
    app.mount("/", FreshStaticFiles(directory=ROOT / "web", html=True), name="web")
    return app


class FreshStaticFiles(StaticFiles):
    """Static files the browser revalidates on every load, so a reload never runs a stale app.js."""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def __routers(wiring: Wiring, settings: Settings) -> list[APIRouter]:
    observer = FeedObserver(wiring.views, wiring.store, wiring.queue)
    scheduler = __scheduler(wiring, settings)
    drift = ViewerDrift(observer, DriftDetector(settings.drift, load_affect_norms().baseline))
    desk = NudgeDesk(wiring.nudges, NudgeJudge(drift, NudgePolicy(settings.nudge)), time.time)
    views = ViewsApi(ViewIntake(wiring.views, scheduler, ViewerExtras(desk)),
                     ViewerReports(wiring.views, wiring.store, wiring.queue))
    return [Api(wiring.service, ClipCatalog(wiring.store), settings.live).router(), views.router(),
            DriftApi(drift).router(), NudgeApi(desk).router(),
            DemoApi(ShortAdder(scheduler, wiring.queue, wiring.store)).router()]


def __scheduler(wiring: Wiring, settings: Settings) -> AnalysisScheduler:
    kind = LiveScheduler if settings.live else CachedScheduler
    return kind(wiring.queue, RunBudget(settings.runs))


def __guard(token: str | None) -> list[Dependency]:
    if token:
        return [Depends(BearerToken(token))]
    logging.getLogger("scrollsense").warning(
        "SCROLLSENSE_TOKEN is not set: /api is open. Do not tunnel this server without a token.")
    return []


app = create_app(Settings.from_env(ROOT))
