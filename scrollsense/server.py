"""FastAPI server for the ScrollSense POC.

Run:  uv run uvicorn scrollsense.server:app --reload --port 8000
"""
import threading
import uuid
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import pipeline
from .schemas import CRITERIA, CRITERION_KEYS

app = FastAPI(title="ScrollSense POC")
JOBS: dict[str, dict] = {}
_lock = threading.Lock()


class AnalyzeRequest(BaseModel):
    url: str
    force: bool = False


def theme_load(scores: dict) -> int:
    return sum(int(scores[k]) for k in CRITERION_KEYS)


def semantic_coords(records: list[dict]) -> dict[str, list[float]]:
    """2-D PCA of the text-package embeddings, scaled to [-1, 1]. Axes are relative."""
    recs = [r for r in records if r.get("embedding")]
    if len(recs) < 2:
        return {r["id"]: [0.0, 0.0] for r in recs}
    dim = min(len(r["embedding"]) for r in recs)
    X = np.array([r["embedding"][:dim] for r in recs], dtype=float)
    X = X - X.mean(axis=0)
    _, _, vt = np.linalg.svd(X, full_matrices=False)
    P = X @ vt[:2].T
    if P.shape[1] < 2:
        P = np.hstack([P, np.zeros((P.shape[0], 1))])
    P = P / (np.abs(P).max(axis=0) + 1e-9)
    return {r["id"]: [round(float(x), 4), round(float(y), 4)] for r, (x, y) in zip(recs, P)}


def summary(r: dict, sem: dict) -> dict:
    s = r["scores"]
    return {"id": r["id"], "title": r["package"]["title"], "mock": r.get("mock", False),
            "source": r.get("source", "youtube"),
            "valence": s["valence"], "arousal": s["arousal"], "stance": s["stance"],
            "load": theme_load(s), "a9": s["a9_death_suicide"], "semantic": sem.get(r["id"])}


@app.get("/api/meta")
def meta():
    return {"criteria": CRITERIA, "mock": pipeline.MOCK, "model": pipeline.MODEL,
            "embed_model": pipeline.EMBED_MODEL}


@app.get("/api/clips")
def clips():
    recs = pipeline.load_all()
    sem = semantic_coords(recs)
    return [summary(r, sem) for r in recs]


@app.get("/api/clips/{vid}")
def clip(vid: str):
    r = pipeline.load(vid)
    if not r:
        raise HTTPException(404, "Not analysed yet")
    r = dict(r)
    r.pop("embedding", None)
    r["load"] = theme_load(r["scores"])
    return r


def _run(jid: str, url: str, force: bool):
    def stage(s):
        with _lock:
            JOBS[jid]["stage"] = s
    try:
        rec = pipeline.analyze(url, on_stage=stage, force=force)
        with _lock:
            JOBS[jid].update(stage="done", id=rec["id"])
    except Exception as e:
        with _lock:
            JOBS[jid].update(stage="error", error=f"{type(e).__name__}: {e}")


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    try:
        vid = pipeline.video_id(req.url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    jid = uuid.uuid4().hex[:8]
    JOBS[jid] = {"stage": "queued", "id": vid}
    threading.Thread(target=_run, args=(jid, req.url, req.force), daemon=True).start()
    return {"job": jid, "id": vid}


@app.get("/api/jobs/{jid}")
def job(jid: str):
    if jid not in JOBS:
        raise HTTPException(404, "Unknown job")
    return JOBS[jid]


MAX_CLIP_BYTES = 100 * 1024 * 1024  # Gemini inline video limit


def _run_clip(jid: str, cid: str, video_bytes: bytes, mime_type: str,
              label: str, source: str, fps: int):
    def stage(s):
        with _lock:
            JOBS[jid]["stage"] = s
    try:
        rec = pipeline.analyze_bytes(video_bytes, mime_type, label=label,
                                     source=source, fps=fps, cid=cid, on_stage=stage)
        with _lock:
            JOBS[jid].update(stage="done", id=rec["id"])
    except Exception as e:
        with _lock:
            JOBS[jid].update(stage="error", error=f"{type(e).__name__}: {e}")


@app.post("/api/analyze-clip")
async def analyze_clip(request: Request, label: str = "", source: str = "screen_capture", fps: int = 3):
    video_bytes = await request.body()
    if not video_bytes:
        raise HTTPException(400, "Empty video clip")
    if len(video_bytes) > MAX_CLIP_BYTES:
        raise HTTPException(413, "Clip exceeds 100 MB inline limit")
    mime_type = request.headers.get("content-type", "video/webm")
    cid = pipeline.new_clip_id(video_bytes)
    jid = uuid.uuid4().hex[:8]
    JOBS[jid] = {"stage": "queued", "id": cid}
    threading.Thread(
        target=_run_clip,
        args=(jid, cid, video_bytes, mime_type, label, source, max(1, min(fps, 10))),
        daemon=True,
    ).start()
    return {"job": jid, "id": cid}


@app.get("/api/recordings/{filename}")
def recording(filename: str):
    safe_name = Path(filename).name
    path = pipeline.RECORDINGS / safe_name
    if not path.is_file():
        raise HTTPException(404, "Recording not found")
    return FileResponse(path)


app.mount("/", StaticFiles(directory=Path(__file__).resolve().parent.parent / "web", html=True),
          name="web")
