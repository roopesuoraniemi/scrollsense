"""ASGI entry point.

Run:  uv run uvicorn scrollsense.server:app --reload --port 8765
"""
import logging
import time

from fastapi import APIRouter, Depends, FastAPI
from fastapi.params import Depends as Dependency
from fastapi.staticfiles import StaticFiles

from .api import Api, ClipCatalog
from .affect_norms import load_affect_norms
from .auth import BearerToken
from .composition import ROOT, Settings, Wiring, wire
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
    app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
    return app


def __routers(wiring: Wiring, settings: Settings) -> list[APIRouter]:
    observer = FeedObserver(wiring.views, wiring.store)
    drift = ViewerDrift(observer, DriftDetector(settings.drift, load_affect_norms().baseline))
    desk = NudgeDesk(wiring.nudges, NudgeJudge(drift, NudgePolicy(settings.nudge)), time.time)
    views = ViewsApi(ViewIntake(wiring.views, wiring.queue, ViewerExtras(desk)),
                     ViewerReports(wiring.views, wiring.store, wiring.queue))
    return [Api(wiring.service, ClipCatalog(wiring.store)).router(), views.router(),
            DriftApi(drift).router(), NudgeApi(desk).router()]


def __guard(token: str | None) -> list[Dependency]:
    if token:
        return [Depends(BearerToken(token))]
    logging.getLogger("scrollsense").warning(
        "SCROLLSENSE_TOKEN is not set: /api is open. Do not tunnel this server without a token.")
    return []


app = create_app(Settings.from_env(ROOT))
