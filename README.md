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
uv run python -m scrollsense https://www.youtube.com/shorts/<id> https://youtu.be/<id>
```

**Useful URLs:**
- `?view=sem` opens the semantic map.
- `#<videoId>` selects a clip.
- Tick "Re-run (ignore cache)" to re-analyse a clip.

## Structure

A pure core inside a shell of swappable parts (see `rules/`).

| File | Role |
|---|---|
| `scrollsense/schemas.py` | Structured-output models (`TextPackage`, `ClipScores`) and the DSM-5 `CRITERIA` |
| `scrollsense/domain.py` | Pure values: `VideoId`, `ClipAnalysis`, `Stage`, `semantic_points()` (PCA) |
| `scrollsense/prompts.py` | Prompt text for both stages |
| `scrollsense/ports.py` | Interfaces: `ContentAnalyser`, `AnalysisStore` |
| `scrollsense/gemini.py`, `mock.py` | `ContentAnalyser` implementations |
| `scrollsense/store.py` | `JsonFileStore` |
| `scrollsense/service.py` | `AnalysisService`: describe, then score, then embed, then store |
| `scrollsense/jobs.py` | `JobBoard`: runs background threads and tracks their status |
| `scrollsense/api.py` | HTTP endpoints under `/api` |
| `scrollsense/composition.py` | `Settings` from the environment, plus the wiring |
| `scrollsense/server.py`, `__main__.py` | Entry points: web server and CLI |
| `web/index.html`, `web/app.js` | The UI, with no build step |

To add another model provider (e.g. Claude for scoring), implement `ContentAnalyser` and select it in `composition.py`.

Tests: `uv run pytest`

## Notes and limits

- **YouTube only:** Gemini reads public YouTube URLs directly. This is a preview feature, free for now, limited to 8 hours of video per day. Private and unlisted videos fail. TikTok videos can't be fetched.
- **Model names:** the default model is `gemini-4-hydrogen` (fastest: ~5 s to describe a clip), and the embedding model is `gemini-embedding-2`. `gemini-4-argon` (~9 s) and `gemini-4-carbon` (~21 s, likely most capable) gave near-identical output on a test clip. Override with `GEMINI_MODEL` and `GEMINI_EMBED_MODEL`. `-latest` aliases don't exist for this API version.
- **Use a paid-tier key:** paid-tier prompts aren't used to improve Google's products. Only public video URLs and their text packages go to Gemini; no patient data does.
- **Semantic map axes:** they are relative and shift as you add clips. Analyse at least three clips for a meaningful picture.
