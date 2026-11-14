# ScrollSense: proof of concept

Paste a public YouTube Shorts URL. The app shows four things:

1. **The original video** (YouTube embed).
2. **The generated text package**: Gemini watches the video and describes what is said, written, shown and heard. *It is told not to judge the people in it.*
3. **The clip's point in embedded space**, with two views:
   - *Affect space*: valence × arousal from the stage-2 scores. Valence is derived in code from the model's negative and positive affect scores (0–3 each, as felt by a typical viewer).
   - *Semantic space*: a 2-D PCA of Gemini text embeddings of the package, across all analysed clips.
4. **DSM-5 theme scores**: A1–A9, each 0–3, plus a theme load out of 27, the clip's stance, and a quoted piece of evidence.

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
| `scrollsense/drift/` | Drift against research norms: pure core (`core.py`, `affect.py`, `clinical.py`, `observe.py`, `levels.py`) and the tuning CLI (`cli.py`) |
| `scrollsense/affect_norms.py`, `reference/affect_norms.json` | Loads the global affect baseline (word norms, built by `scripts/build_affect_norms.py`) |
| `scrollsense/nudge.py`, `nudgelog.py`, `nudge_api.py` | Patient nudge: pure policy and cards; JSONL log; desk and routes |
| `scrollsense/ports.py` | Interfaces: `ContentAnalyser`, `AnalysisStore`, `ViewLog`, `NudgeLog`, `Nudger` |
| `scrollsense/gemini.py`, `mock.py` | `ContentAnalyser` implementations |
| `scrollsense/store.py`, `viewlog.py` | `JsonFileStore`, `JsonlViewLog` |
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

For each viewer, ScrollSense compares their most recent analysed Shorts with two global, research-based yardsticks. There is no personal baseline and no learning phase beyond a half-full window, so a feed that is heavy from the very first Short is flagged too. **It describes the content shown, not the person, and is not a diagnosis.** Sources, numbers, deviations and evaluation: `docs/clinical-calibration.md`.

- **Window:** the last `SCROLLSENSE_DRIFT_WINDOW` (default 10 for a quick demo; 14 would match one Short per PHQ-9 day) analysed Shorts, first view only, in seen order. Levels stay `learning` until it holds half of that.
- **Affect vs word norms:** the window's mean valence and arousal (1–5) against a global centre from Warriner, Kuperman & Brysbaert (2013) word norms mapped 1–9 → 1–5 (valence 3.03 ± 0.64, arousal 2.61 ± 0.45; NRC VAD 2018 as a cross-check). Effect per axis = (recent mean − norm centre) / research SD. The drift is the vector of both effects: within 1 SD is the normal range by definition, and a **deviation (`warning`)** is a drift pointing into the bottom-left quadrant (valence and arousal both at or below the norm) that is longer than 1 SD. Affect score = that length, 0 in any other direction. On the Affect map the dashed ellipse is that 1 SD edge.
- **Clinical, PHQ-9 style (content exposure):** a DSM-5 criterion is *present* in a Short when its theme score is ≥ 2 (central). Its share of the window maps onto the PHQ-9 answers: < 2/14 "not at all" (0), up to half "several days" (1), more than half "more than half the days" (2), ≥ 12/14 "nearly every day" (3). The nine item scores sum to 0–27 and are banded by Kroenke et al. (2001): minimal < 5, mild 5–9, moderate 10–14, moderately severe 15–19, severe ≥ 20. Pattern by the PHQ-9 algorithm: "major" (≥ 5 items at "more than half the days", one of them depressed mood or anhedonia), "other" (2–4 such items), else "none". Level: `warning` at ≥ 10 (the validated cutoff) or "major"; `watch` at ≥ 5 or "other". These cutoffs come from the research and are not tuned.
- **Overall level:** the more severe of the two. `timeline` holds the level (plus affect score and PHQ-9-style total) of the window ending at every analysed Short; the nudge policy reads it.
- **No crisis/suicide alerts:** the feed signal is not reliable enough for that kind of alert; A9 counts in the PHQ-9-style total like every other item and triggers nothing on its own.
- **Personal baseline removed:** the old per-viewer baseline (first N Shorts or *Set baseline now*), its store and its endpoints are gone. Legacy `views/<viewer>.baseline.json` files are no longer read, written or erased; delete them by hand if any exist.
- **Code:** pure core in `scrollsense/drift/` (`DriftDetector.report` returns the `DriftReport` consumed by the UI and the nudge policy). The norms are loaded at the edge (`affect_norms.py`) and injected. Adapter: `drift_api.py`.

| Variable | Default | Meaning |
|---|---|---|
| `SCROLLSENSE_DRIFT_WINDOW` | `10` | Recent window in analysed Shorts (judged once it holds half of this) |
| `SCROLLSENSE_DRIFT_WATCH` | `1.0` | Affect `watch` above this many SDs into the bottom left (≥ 1; equal to warn means no affect watch band) |
| `SCROLLSENSE_DRIFT_WARN` | `1.0` | Affect `warning` above this many SDs into the bottom left (≥ 1) |

`SCROLLSENSE_BASELINE_N` and `SCROLLSENSE_MIN_BASELINE` are no longer read.

| Method + path | Returns |
|---|---|
| `GET /api/viewers/{viewer}/drift` | `{viewer, level, note, config, affect_baseline, recent, pending, score, affect_level, features, clinical, clinical_level, reasons, evidence, timeline}` |

`affect_baseline` is `{source, cite, centre:{valence, arousal}, sd:{valence, arousal}}`; `clinical` is `{window_n, items:[{code, label, present, share, score, frequency_label}], total, band, pattern, reference}` (null before the first analysed Short).

To inspect a viewer without the UI (read-only; flags override the environment):

```bash
uv run python -m scrollsense.drift patient-01 --window 10 --watch 0.3 --warn 0.5
```

It prints both levels, reasons, the affect table (norm centre and floored SD, recent mean, effect, risk), the nine PHQ-9-style items, evidence and a text timeline. Other flag: `--data DIR`.

To rebuild the norms (lexicons are not shipped; NRC VAD is non-commercial only): `python -I scripts/build_affect_norms.py --lexicons DIR`. To re-run the evaluation: `PYTHONPATH=. uv run python scripts/tune_drift.py`.

## Patient nudge

**Research prototype, not a medical device.** When a viewer's feed stays at drift level `warning`, the phone shows a small optional check-in card over YouTube. Design: `docs/patient-nudge-plan.md`.

- **Support card:** "How do these videos feel right now?" with three equal options side by side: I'm OK · I want to take a break · Not now. "I want to take a break" pauses the video and closes the tab, or switches to a blank page when the browser won't let a page close its tab (pages can't open the browser's home page). No "refresh my feed" option: steering the feed would erase the signal. It fires when the last `SCROLLSENSE_NUDGE_STREAK` judged timeline points are all `warning`, no card is open, and the cooldown since the last support card has passed (doubled after "I'm OK"). Never names a diagnosis, a mood or the video.
- **No crisis/suicide alerts:** the feed signal is not reliable enough for that kind of alert; A9 remains a content theme score only. The support card is the only patient-facing card.
- **Delivery:** no polling. The `POST /api/views` receipt carries `nudge`: the viewer's open (unanswered, unexpired) card, newly issued or still pending, else `null`. The userscript (v0.7) renders it and posts the tap. Decide-and-record is one atomic command (`NudgeDesk.issue_if_due`); the policy (`NudgePolicy.decide`) is pure.
- **Storage:** `views/<viewer>.nudges.jsonl` (nudges and answers). `DELETE /api/viewers/{viewer}` erases it too.
- **Code:** pure core `scrollsense/nudge.py`; port `NudgeLog` (adapter `nudgelog.py`); `nudge_api.py` (desk and routes).

| Variable | Default | Meaning |
|---|---|---|
| `SCROLLSENSE_NUDGE_ENABLED` | `1` | `0` turns nudges off (e.g. no nudge consent) |
| `SCROLLSENSE_NUDGE_STREAK` | `2` | Consecutive judged timeline points at `warning` needed |
| `SCROLLSENSE_NUDGE_COOLDOWN_S` | `600` | Seconds after a support card before the next one |
| `SCROLLSENSE_NUDGE_OK_FACTOR` | `2` | Cooldown multiplier after "I'm OK" |
| `SCROLLSENSE_NUDGE_EXPIRE_S` | `900` | An unanswered card stops being shown after this |
| `SCROLLSENSE_NUDGE_QUIET_FROM` / `_QUIET_TO` | unset | Quiet hours (local hour 0–23, may wrap midnight); off unless both are set |
| `SCROLLSENSE_NUDGE_TZ_OFFSET_MIN` | `120` | Local time for quiet hours, minutes east of UTC |

| Method + path | Returns |
|---|---|
| `POST /api/views` | the receipt now has `nudge`: `{id, kind: support, title, message, options: [{choice, label, action: open\|call\|message\|close, href, text}], expires_at}` or `null` |
| `GET /api/viewers/{viewer}/nudges` | history, newest first: `[{nudge: {viewer, created_at, reason, video_id, card}, response: {nudge_id, choice, at} \| null, state: open\|answered\|expired}]` |
| `POST /api/viewers/{viewer}/nudges/{id}/response` `{choice}` | 204; 404 unknown id, 409 already answered, 422 not one of the card's options |


## Notes and limits

- **YouTube only:** Gemini reads public YouTube URLs directly. This is a preview feature, free for now, limited to 8 hours of video per day. Private and unlisted videos fail. TikTok videos can't be fetched.
- **Model names:** the default model is `gemini-4-hydrogen` (fastest: ~5 s to describe a clip), and the embedding model is `gemini-embedding-2`. `gemini-4-argon` (~9 s) and `gemini-4-carbon` (~21 s, likely most capable) gave near-identical output on a test clip. Override with `GEMINI_MODEL` and `GEMINI_EMBED_MODEL`. `-latest` aliases don't exist for this API version.
- **Use a paid-tier key:** paid-tier prompts aren't used to improve Google's products. Only public video URLs and their text packages go to Gemini; no patient data does.
- **Semantic map axes:** they are relative and shift as you add clips. Analyse at least three clips for a meaningful picture.
