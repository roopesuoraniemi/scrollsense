"""Gemini pipeline: YouTube video -> text package -> DSM-5 theme scores (+ text embedding).

Usage (batch):  uv run python -m scrollsense.pipeline <youtube-url> [<url> ...]
"""
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

from .schemas import CRITERIA, CRITERION_KEYS, ClipScores, TextPackage

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
MOCK = os.getenv("SCROLLSENSE_MOCK") == "1"

# Mock output lives in its own folder so it can never be served as a real analysis.
DATA = ROOT / "data" / ("mock_clips" if MOCK else "clips")
DATA.mkdir(parents=True, exist_ok=True)
RECORDINGS = DATA / "recordings"
RECORDINGS.mkdir(parents=True, exist_ok=True)

_EXT_BY_MIME = {
    "video/webm": ".webm",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
}

_ID = re.compile(r"(?:v=|/shorts/|youtu\.be/|/embed/|/live/)([A-Za-z0-9_-]{11})")


def video_id(url_or_id: str) -> str:
    s = url_or_id.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", s):
        return s
    m = _ID.search(s)
    if not m:
        raise ValueError("Not a YouTube URL or video ID")
    return m.group(1)


def watch_url(vid: str) -> str:
    return f"https://www.youtube.com/watch?v={vid}"


# ---------------------------------------------------------------- prompts

PROMPT_1 = """You are building a content-analysis record for a short video.
Describe ONLY what is said, written and shown in the video, plus its music and pacing.
Do NOT guess the identity, emotions, health or mental state of any person in the video;
describe the content and its themes, not the people.
Return the fields of the schema. Keep transcript and on-screen text verbatim where possible."""

PROMPT_2 = """You score the THEMES of a short video from its text description.
You are not assessing any person, only what the content communicates to a viewer.

DSM-5 criteria for a major depressive episode, used here as content themes:
{criteria}

Scoring for each theme: 0 absent, 1 mentioned in passing, 2 a central theme, 3 intense or glorified.
Stance:
- dwelling_or_romanticising: lingers in, validates or aestheticises the feeling without a way forward
- neutral_or_informational: describes or explains (e.g. psychoeducation) without dwelling
- coping_or_recovery: offers coping, help-seeking, recovery or hope
- unrelated: no depressive themes at all
Valence (1 very negative .. 5 very positive) and arousal (1 very calm .. 5 very energetic)
describe the content's emotional tone and energy.
Suicide-prevention or help-line content mentioning suicide still gets an A9 score, with stance coping_or_recovery.

TEXT PACKAGE:
{package}"""


def _criteria_text() -> str:
    return "\n".join(f"- {c['code']} {c['label']}: {c['theme']}" for c in CRITERIA)


def package_text(pkg: TextPackage) -> str:
    return (f"Title: {pkg.title}\nFormat: {pkg.format}\nMain message: {pkg.main_message}\n"
            f"Transcript: {pkg.transcript}\nOn-screen text: {pkg.on_screen_text}\n"
            f"Visuals: {pkg.visual_description}\nAudio: {pkg.audio_description}")


# ---------------------------------------------------------------- gemini

_client = None


def _gemini():
    global _client
    if _client is None:
        from google import genai
        if not os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
            raise RuntimeError("GEMINI_API_KEY is not set (copy .env.example to .env), "
                               "or run with SCROLLSENSE_MOCK=1")
        _client = genai.Client()
    return _client


def _json_config(schema):
    from google.genai import types
    return types.GenerateContentConfig(response_mime_type="application/json",
                                       response_schema=schema, temperature=0.2)


def _normalize_mime(mime_type: str) -> str:
    base = (mime_type or "video/webm").split(";")[0].strip().lower()
    return base if base.startswith("video/") else "video/webm"


def stage1(vid: str) -> TextPackage:
    from google.genai import types
    r = _gemini().models.generate_content(
        model=MODEL,
        contents=types.Content(role="user", parts=[
            types.Part(file_data=types.FileData(file_uri=watch_url(vid))),
            types.Part(text=PROMPT_1),
        ]),
        config=_json_config(TextPackage),
    )
    return r.parsed if isinstance(r.parsed, TextPackage) else TextPackage.model_validate_json(r.text)


def stage1_bytes(video_bytes: bytes, mime_type: str, fps: int = 3) -> TextPackage:
    """Run Gemini stage 1 directly on inline screen-capture bytes (up to 100 MB)."""
    from google.genai import types
    base_mime = _normalize_mime(mime_type)
    part = types.Part.from_bytes(data=video_bytes, mime_type=base_mime)
    if hasattr(types, "VideoMetadata") and fps > 0:
        part.video_metadata = types.VideoMetadata(fps=fps)
    r = _gemini().models.generate_content(
        model=MODEL,
        contents=[part, PROMPT_1],
        config=_json_config(TextPackage),
    )
    return r.parsed if isinstance(r.parsed, TextPackage) else TextPackage.model_validate_json(r.text)


def stage2(pkg: TextPackage) -> ClipScores:
    prompt = PROMPT_2.format(criteria=_criteria_text(), package=package_text(pkg))
    r = _gemini().models.generate_content(model=MODEL, contents=prompt,
                                          config=_json_config(ClipScores))
    s = r.parsed if isinstance(r.parsed, ClipScores) else ClipScores.model_validate_json(r.text)
    return s.clamped()


def embed(pkg: TextPackage) -> list[float]:
    from google.genai import types
    r = _gemini().models.embed_content(
        model=EMBED_MODEL, contents=package_text(pkg),
        config=types.EmbedContentConfig(task_type="CLUSTERING"))
    return list(r.embeddings[0].values)


# ---------------------------------------------------------------- mock (no API)

def _rng(vid: str, salt: str) -> int:
    return int(hashlib.sha256((vid + salt).encode()).hexdigest(), 16)


def mock_stage1(vid: str) -> TextPackage:
    time.sleep(1.0)
    return TextPackage(
        title=f"[MOCK] Placeholder clip {vid}",
        transcript="[MOCK] No video was analysed. Set GEMINI_API_KEY for real output.",
        on_screen_text="[MOCK]", visual_description="[MOCK] placeholder",
        audio_description="[MOCK] placeholder",
        main_message="[MOCK] Placeholder text package used to test the interface.",
        format="other", people_present=False, language="en")


def mock_stage1_bytes(cid: str, label: str, bytes_len: int, mime_type: str) -> TextPackage:
    time.sleep(0.8)
    kb = max(1, round(bytes_len / 1024))
    title = label.strip() or f"[MOCK] Screen clip {cid[-6:]}"
    return TextPackage(
        title=title[:60],
        transcript="[MOCK] Screen-captured audio would be transcribed verbatim here.",
        on_screen_text="[MOCK] Captured overlay/captions from screen recording.",
        visual_description=f"[MOCK] Captured {kb} KB ({mime_type}) screen segment.",
        audio_description="[MOCK] Captured tab/system audio stream.",
        main_message="[MOCK] Screen-recording pipeline test (set GEMINI_API_KEY for live Gemini analysis).",
        format="other", people_present=False, language="en")


def mock_stage2(vid: str) -> ClipScores:
    time.sleep(0.7)
    d = {k: _rng(vid, k) % 4 for k in CRITERION_KEYS}
    d["a9_death_suicide"] = 0
    return ClipScores(valence=1 + _rng(vid, "v") % 5, arousal=1 + _rng(vid, "a") % 5,
                      stance=["dwelling_or_romanticising", "neutral_or_informational",
                              "coping_or_recovery", "unrelated"][_rng(vid, "s") % 4],
                      hopeful=bool(_rng(vid, "h") % 2),
                      evidence="[MOCK] random scores, not an analysis", **d)


def mock_embed(vid: str) -> list[float]:
    return [((_rng(vid, f"e{i}") % 2000) - 1000) / 1000 for i in range(32)]


# ---------------------------------------------------------------- orchestration

def cache_path(vid: str) -> Path:
    return DATA / f"{vid}.json"


def load(vid: str) -> dict | None:
    p = cache_path(vid)
    return json.loads(p.read_text()) if p.exists() else None


def load_all() -> list[dict]:
    out = [json.loads(p.read_text()) for p in sorted(DATA.glob("*.json"))]
    return sorted(out, key=lambda r: r.get("created", 0))


def _finish_record(cid: str, pkg: TextPackage, extra: dict,
                   on_stage: Callable[[str], None]) -> dict:
    mock = MOCK
    on_stage("stage2")  # text package -> scores
    scores = mock_stage2(cid) if mock else stage2(pkg)
    on_stage("embedding")
    try:
        vec = mock_embed(cid) if mock else embed(pkg)
        embed_error = None
    except Exception as e:  # embedding is optional for the POC
        vec, embed_error = None, str(e)

    rec = {
        "id": cid,
        **extra,
        "mock": mock,
        "model": "mock" if mock else MODEL,
        "embed_model": None if vec is None else ("mock" if mock else EMBED_MODEL),
        "embed_error": embed_error,
        "created": time.time(),
        "package": pkg.model_dump(),
        "scores": scores.model_dump(),
        "embedding": vec,
    }
    cache_path(cid).write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    on_stage("done")
    return rec


def analyze(url_or_id: str, on_stage: Callable[[str], None] = lambda s: None,
            force: bool = False) -> dict:
    vid = video_id(url_or_id)
    if not force and (cached := load(vid)):
        on_stage("cached")
        return cached

    on_stage("stage1")  # video -> text package
    pkg = mock_stage1(vid) if MOCK else stage1(vid)
    return _finish_record(vid, pkg, {"url": watch_url(vid), "source": "youtube"}, on_stage)


def new_clip_id(video_bytes: bytes) -> str:
    digest = hashlib.sha256(video_bytes).hexdigest()[:6]
    return f"rec_{int(time.time() * 1000)}_{digest}"


def analyze_bytes(video_bytes: bytes, mime_type: str, label: str = "",
                  source: str = "screen_capture", fps: int = 3,
                  cid: str | None = None,
                  on_stage: Callable[[str], None] = lambda s: None) -> dict:
    if not video_bytes:
        raise ValueError("Empty video payload")
    base_mime = _normalize_mime(mime_type)
    ext = _EXT_BY_MIME.get(base_mime, ".webm")
    cid = cid or new_clip_id(video_bytes)
    filename = f"{cid}{ext}"
    (RECORDINGS / filename).write_bytes(video_bytes)

    on_stage("stage1")
    pkg = (mock_stage1_bytes(cid, label, len(video_bytes), base_mime)
           if MOCK else stage1_bytes(video_bytes, base_mime, fps=fps))
    return _finish_record(cid, pkg, {
        "source": source,
        "video_file": filename,
        "mime_type": base_mime,
        "bytes_len": len(video_bytes),
    }, on_stage)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for u in sys.argv[1:]:
        r = analyze(u, on_stage=lambda s, u=u: print(f"{u}: {s}"))
        s = r["scores"]
        load_sum = sum(s[k] for k in CRITERION_KEYS)
        print(f"  -> {r['package']['title']} | valence {s['valence']} arousal {s['arousal']} "
              f"| theme load {load_sum}/27 | {s['stance']}")
