"""ScrollSense web demo on Modal: the same FastAPI app, in one always-warm container.

Deploy:  scripts/deploy_modal.sh          (creates the secret from .env, then deploys)
Try out: uv run --with modal modal serve modal_app.py

One container only (min and max 1): the analysis queue, its pacer and the demo viewers live in
that process's memory, and its worker threads must keep running between requests. Data is kept
in /tmp, so a restart starts every demo session fresh; analyses are re-run live anyway.
"""
from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent
REQUIREMENTS = HERE / "requirements.lock.txt"   # written by scripts/deploy_modal.sh from uv.lock

image = (
    modal.Image.debian_slim(python_version="3.13")
    .uv_pip_install(requirements=[str(REQUIREMENTS)])
    .add_local_dir(HERE / "scrollsense", "/root/scrollsense", ignore=["**/__pycache__/**"])
    .add_local_dir(HERE / "web", "/root/web", ignore=["_*"])
)

# Demo settings. GEMINI_API_KEY comes from the "scrollsense" secret. No SCROLLSENSE_TOKEN: the public
# demo is open, and the analysis queue's pace (SCROLLSENSE_RPM) is the only limit on Gemini.
DEMO_ENV = {
    "PYTHONPATH": "/root",
    "SCROLLSENSE_DATA": "/tmp/scrollsense-data",
    "SCROLLSENSE_LIVE_INFERENCE": "1",
    "SCROLLSENSE_WORKERS": "6",
    "SCROLLSENSE_RPM": "20",
    "SCROLLSENSE_DRIFT_WINDOW": "5",
}

app = modal.App("scrollsense-demo")


@app.function(image=image, secrets=[modal.Secret.from_name("scrollsense")], env=DEMO_ENV,
              min_containers=1, max_containers=1, cpu=1.0, memory=1024, timeout=600)
@modal.concurrent(max_inputs=200)
@modal.asgi_app()
def web():  # noqa: ANN201 - Modal serves whatever ASGI app this returns
    from scrollsense.server import app as scrollsense_app   # starts the analysis workers

    return scrollsense_app
