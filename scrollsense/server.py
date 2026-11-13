"""ASGI entry point.

Run:  uv run uvicorn scrollsense.server:app --reload --port 8765
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import Api
from .composition import ROOT, Settings, wire
from .jobs import JobBoard


def create_app(settings: Settings) -> FastAPI:
    """The web app: JSON API under /api, the static UI at /."""
    wiring = wire(settings)
    app = FastAPI(title="ScrollSense POC")
    app.include_router(Api(wiring.service, wiring.store, JobBoard(wiring.service)).router())
    app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
    return app


app = create_app(Settings.from_env(ROOT))
