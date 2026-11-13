# ScrollSense: proof of concept

Paste a public YouTube Shorts URL. The app shows four things:

1. **The original video** (YouTube embed).
2. **The generated text package**: Gemini watches the video and describes what is said, written, shown and heard. *It is told not to judge the people in it.*
3. **The clip's point in embedded space**, with two views:
   - *Affect space*: valence × arousal from the stage-2 scores.
   - *Semantic space*: a 2-D PCA of Gemini text embeddings of the package, across all analysed clips.
4. **DSM-5 theme scores**: A1–A9, each 0–3, plus a theme load out of 27, the clip's stance, and a quoted piece of evidence. Any A9 (death/suicide) score shows the safety-path banner.

These scores describe the **content's themes**, not any person. They are not a diagnosis.

```
YouTube URL ──► Gemini stage 1 (video in, JSON out) ──► text package
                                                         │
                     Gemini stage 2 (text in, JSON out) ◄┘──► DSM-5 themes, valence, arousal, stance
                     Gemini embedding of the package    ──► semantic map
```

## Run

```bash
cd ~/hackathons/scrollsense
uv sync
cp .env.example .env        # then put your GEMINI_API_KEY in .env
uv run uvicorn scrollsense.server:app --reload --port 8765
```

Open http://localhost:8765.

> **Why port 8765:** this Windows machine has a port proxy on 8000 (`netsh interface portproxy`: `0.0.0.0:8000 → <WSL IP>:8000`). That proxy steals `localhost:8000` from the browser and resets the connection, because uvicorn listens only on 127.0.0.1. Avoid 8000, and don't use `--host 0.0.0.0` on hackathon Wi-Fi: the proxy would expose the app, and your Gemini credits, to the network.

**Try the UI without a key** (placeholder output, stored separately in `data/mock_clips/`):

```bash
SCROLLSENSE_MOCK=1 uv run uvicorn scrollsense.server:app --port 8765
```

**Batch-analyse from the command line** (results are cached in `data/clips/<videoId>.json`):

```bash
uv run python -m scrollsense.pipeline https://www.youtube.com/shorts/<id> https://youtu.be/<id>
```

**Useful URLs:**
- `?view=sem` opens the semantic map.
- `#<videoId>` selects a clip.
- Tick "Re-run (ignore cache)" to re-analyse a clip.

## Files

| File | What it does |
|---|---|
| `scrollsense/schemas.py` | Structured-output schemas (`TextPackage`, `ClipScores`) and the DSM-5 criterion list |
| `scrollsense/pipeline.py` | Gemini calls (stage 1, stage 2, embedding), caching, mock mode, CLI |
| `scrollsense/server.py` | FastAPI: `/api/analyze` (background job), `/api/jobs/{id}`, `/api/clips`, `/api/clips/{id}`, `/api/meta` |
| `web/index.html` | Single-page UI, no build step |

## Notes and limits

- **YouTube only:** Gemini reads public YouTube URLs directly. This is a preview feature, free for now, limited to 8 hours of video per day. Private and unlisted videos fail. TikTok videos can't be fetched.
- **Model names:** the default model is `gemini-flash-latest`, and the embedding model is `gemini-embedding-001`. Override them with `GEMINI_MODEL` and `GEMINI_EMBED_MODEL` in `.env` if your project uses different names.
- **Use a paid-tier key:** paid-tier prompts aren't used to improve Google's products. Only public video URLs and their text packages go to Gemini; no patient data does.
- **Semantic map axes:** they are relative and shift as you add clips. Analyse at least three clips for a meaningful picture.
