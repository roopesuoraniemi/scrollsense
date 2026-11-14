# ScrollSense: proof of concept

Paste a public YouTube Shorts URL. The app shows four things:

1. **The original video** (YouTube embed).
2. **The generated text package**: Gemini watches the video and describes what is said, written, shown and heard. *It is told not to judge the people in it.*
3. **The clip's point in embedded space**, with two views:
   - *Affect space*: valence × arousal from the stage-2 scores. Valence is derived in code from the model's negative and positive affect scores (0–3 each, as felt by a typical viewer).
   - *Semantic space*: a 2-D PCA of Gemini text embeddings of the package, across all analysed clips.
4. **DSM-5 theme scores**: A1–A9, each 0–3, plus a theme load out of 27, the clip's stance, and a quoted piece of evidence. Any A9 (death/suicide) score shows the safety-path banner.

These scores describe the **content's themes**, not any person. They are not a diagnosis.

```
YouTube URL ──► Gemini stage 1 (video in, JSON out) ──► text package
                                                         │
                     Gemini stage 2 (text in, JSON out) ◄┘──► DSM-5 themes, affect, arousal, stance
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

Add `--force` to re-analyse clips that are already stored.

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
| `scrollsense/views.py`, `feed.py` | Pure core for the phone prototype: `ViewerId`, `ViewEvent`, `dedupe`; `composition()`, `readout()` |
| `scrollsense/drift/` | Drift from a viewer's normal feed: pure core (`core.py`) and the tuning CLI (`cli.py`) |
| `scrollsense/ports.py` | Interfaces: `ContentAnalyser`, `AnalysisStore`, `ViewLog`, `BaselineStore` |
| `scrollsense/gemini.py`, `mock.py` | `ContentAnalyser` implementations |
| `scrollsense/store.py`, `viewlog.py`, `baselines.py` | `JsonFileStore`, `JsonlViewLog`, `JsonBaselineStore` |
| `scrollsense/analysis_queue.py`, `intake.py` | `AnalysisQueue` (paced workers, dedupe by video), `ViewIntake` (record a batch) |
| `scrollsense/service.py` | `AnalysisService`: describe, then score, then embed, then store |
| `scrollsense/jobs.py` | `JobBoard`: runs background threads and tracks their status |
| `scrollsense/api.py`, `views_api.py`, `drift_api.py`, `auth.py` | HTTP endpoints under `/api`; Bearer-token guard |
| `scrollsense/composition.py` | `Settings` from the environment, plus the wiring |
| `scrollsense/server.py`, `__main__.py` | Entry points: web server and CLI |
| `web/index.html`, `web/app.js` | The UI, with no build step |

To add another model provider (e.g. Claude for scoring), implement `ContentAnalyser` and select it in `composition.py`.

Tests: `uv run pytest`

## Phone prototype backend

A userscript on the phone (see `docs/phone-prototype-plan.md`) posts view events; each viewed Short is analysed once (shared across viewers) and feeds that viewer's composition readout.

**Environment** (`.env` or the shell):

| Variable | Default | Meaning |
|---|---|---|
| `SCROLLSENSE_TOKEN` | unset | Bearer token required on every `/api/*` route. Unset = open, with a startup warning. |
| `SCROLLSENSE_WORKERS` | `2` | Analysis worker threads |
| `SCROLLSENSE_RPM` | `20` | Max analyses started per minute (`0` = unpaced) |
| `SCROLLSENSE_DATA` | `data` | Data folder: `clips/` + `views/<viewer>.jsonl` (mock mode: `mock_clips/` + `mock_views/`) |

**Endpoints** (all need `Authorization: Bearer <token>` when a token is set):

| Method + path | Returns |
|---|---|
| `POST /api/views` `{viewer, events:[{event_id, video_id or url, seen_at, tz_offset_min?, dwell_s?, duration_s?, loops?, source?, surface?}]}` | 202 `{accepted, duplicates, queued, rejected:[{event_id, reason}]}`; only `surface: "shorts"` is analysed |
| `GET /api/viewers` | `[{viewer, events, last_seen}]` |
| `GET /api/viewers/{viewer}/feed?limit=50` | newest events first, each with `state` (scored / queued / failed / pending) and `clip` when scored |
| `GET /api/viewers/{viewer}/readout?from=&to=&baseline_from=&baseline_to=&control=` | `{windows, current, baseline, control, readout}`; epoch seconds; default: last 24 h vs everything before |
| `DELETE /api/viewers/{viewer}` | 204; erases that viewer's view log (GDPR) |
| `GET /api/queue` | `{depth, in_flight, done, failed, recent_failures}` |

Viewer ids are pseudonyms matching `[a-z0-9-]{3,32}`. The web UI takes the token once from `http://localhost:8765/?token=<token>` and remembers it.

```bash
TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(24))')
echo "SCROLLSENSE_TOKEN=$TOKEN" >> .env
uv run uvicorn scrollsense.server:app --port 8765

curl -s -X POST http://127.0.0.1:8765/api/views \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"viewer":"patient-01","events":[
        {"event_id":"e1","url":"https://m.youtube.com/shorts/dQw4w9WgXcQ","seen_at":1763100000,"tz_offset_min":60,"dwell_s":7.5},
        {"event_id":"e2","video_id":"jNQXAC9IVRw","seen_at":1763100012,"tz_offset_min":60,"dwell_s":3.1}]}'
```

> **Set `SCROLLSENSE_TOKEN` before running `cloudflared tunnel --url http://127.0.0.1:8765`.** The tunnel makes the server public, and every queued Short spends Gemini credits.

## Drift detection

For each viewer, ScrollSense learns where their scrolled Shorts usually sit (their *normal feed*) and flags a drift away from it. **It describes the content shown, not a diagnosis.**

- **Space:** per analysed Short (first view only, in seen order): valence (1–5), arousal (1–5), negative affect (0–3), theme load (0–27), and dwelling stance (0/1). The risky direction is down for valence (weight 1) and arousal (0.5), and up for the rest (1 each).
- **Baseline:** by default the viewer's first `SCROLLSENSE_BASELINE_N` analysed Shorts. *Set baseline now* freezes the most recent N analysed Shorts instead. They are stored by video id in `views/<viewer>.baseline.json`, so analyses that finish later can't shift the baseline. *Reset baseline* goes back to the default.
- **Score:** take the last `SCROLLSENSE_DRIFT_WINDOW` analysed Shorts after the baseline. For each feature, compute (recent mean − baseline mean) / max(baseline SD, floor), counting only moves in the risky direction, then take the weighted mean. Levels: `learning` until the baseline is full and the window is half full, then `normal`, `watch`, or `warning`. Any A9 Short in the last window is always reported, whatever the level.
- **Code:** pure core in `scrollsense/drift/core.py` (`DriftDetector.report` returns the `DriftReport` that the UI, and later the nudge and clinician views, consume). Adapters: `baselines.py` and `drift_api.py`.

| Variable | Default | Meaning |
|---|---|---|
| `SCROLLSENSE_BASELINE_N` | `20` | Default baseline size, and the default size for "Set baseline now" |
| `SCROLLSENSE_MIN_BASELINE` | `8` | Fewest baseline Shorts needed to judge |
| `SCROLLSENSE_DRIFT_WINDOW` | `10` | Recent window (judged once it holds half of this) |
| `SCROLLSENSE_DRIFT_WATCH` | `1.2` | Score for `watch` (tuned, see `docs/drift-tuning.md`) |
| `SCROLLSENSE_DRIFT_WARN` | `1.5` | Score for `warning` (placeholder, to be tuned) |

| Method + path | Returns |
|---|---|
| `GET /api/viewers/{viewer}/drift` | `{viewer, level, score, note, config, baseline, recent, pending, features, reasons, evidence, safety, timeline}` |
| `POST /api/viewers/{viewer}/baseline` `{size?}` | 204; freezes the last `size` (default `SCROLLSENSE_BASELINE_N`) analysed Shorts; 409 if fewer than the minimum are analysed |
| `DELETE /api/viewers/{viewer}/baseline` | 204; back to the default baseline |

To tune thresholds without the UI (read-only; flags override the environment):

```bash
uv run python -m scrollsense.drift patient-01 --window 8 --baseline-n 15 --watch 1.0 --warn 2.0
```

It prints the level, score, reasons, a feature table (baseline mean and SD, recent mean, effect, risk), evidence, A9 safety hits, and a text timeline. Other flags: `--min-baseline N`, `--data DIR`.

## Notes and limits

- **YouTube only:** Gemini reads public YouTube URLs directly. This is a preview feature, free for now, limited to 8 hours of video per day. Private and unlisted videos fail. TikTok videos can't be fetched.
- **Model names:** the default model is `gemini-4-hydrogen` (fastest: ~5 s to describe a clip), and the embedding model is `gemini-embedding-2`. `gemini-4-argon` (~9 s) and `gemini-4-carbon` (~21 s, likely most capable) gave near-identical output on a test clip. Override with `GEMINI_MODEL` and `GEMINI_EMBED_MODEL`. `-latest` aliases don't exist for this API version.
- **Use a paid-tier key:** paid-tier prompts aren't used to improve Google's products. Only public video URLs and their text packages go to Gemini; no patient data does.
- **Semantic map axes:** they are relative and shift as you add clips. Analyse at least three clips for a meaningful picture.
