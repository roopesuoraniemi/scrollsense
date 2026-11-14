"""ASGI entry point.

Run:  uv run uvicorn scrollsense.server:app --reload --port 8765
"""
import logging
import time

from fastapi import APIRouter, Depends, FastAPI
from fastapi.params import Depends as Dependency
from fastapi.staticfiles import StaticFiles

from .api import Api
from .auth import BearerToken
from .composition import ROOT, Settings, Wiring, wire
from .drift.core import DriftDetector
from .drift_api import DriftApi, FeedObserver, ViewerDrift
from .intake import ViewIntake
from .jobs import JobBoard
from .views_api import ViewerReports, ViewsApi


def create_app(settings: Settings) -> FastAPI:
    """The web app: JSON API under /api (Bearer-guarded when a token is set), the static UI
    at /. Starts the analysis queue's worker threads."""
    wiring = wire(settings)
    wiring.queue.start(settings.queue.workers)
    guard = __guard(settings.token)
    app = FastAPI(title="ScrollSense POC")
    for router in __routers(wiring, settings):
        app.include_router(router, dependencies=guard)
    app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
    return app


def __routers(wiring: Wiring, settings: Settings) -> list[APIRouter]:
    views = ViewsApi(ViewIntake(wiring.views, wiring.queue, wiring.baselines),
                     ViewerReports(wiring.views, wiring.store, wiring.queue), time.time)
    observer = FeedObserver(wiring.views, wiring.store)
    drift = ViewerDrift(observer, wiring.baselines, DriftDetector(settings.drift))
    return [Api(wiring.service, wiring.store, JobBoard(wiring.service)).router(),
            views.router(), DriftApi(drift, time.time).router()]


def __guard(token: str | None) -> list[Dependency]:
    if token:
        return [Depends(BearerToken(token))]
    logging.getLogger("scrollsense").warning(
        "SCROLLSENSE_TOKEN is not set: /api is open. Do not tunnel this server without a token.")
    return []


app = create_app(Settings.from_env(ROOT))
