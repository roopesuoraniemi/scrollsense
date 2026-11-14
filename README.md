# ScrollSense

A research prototype that reads the Shorts a person scrolls as a passive mood signal. A
userscript on the phone logs each Short; Gemini watches it and scores its affect; the
laptop page shows when the recent feed drifts towards low mood, and the phone can offer a
gentle check-in card.

Scores describe the **content**, never the person, and are not a diagnosis.

```
phone (userscript) ──► POST /api/views ──► queue ──► Gemini, one call: video → short description + affect scores
laptop page ◄── feed, drift report, nudges          phone ◄── check-in card in the receipt
```

## Run

```bash
cd ~/hackathons/scrollsense
uv sync
cp .env.example .env        # then set GEMINI_API_KEY and SCROLLSENSE_TOKEN
uv run uvicorn scrollsense.server:app --reload --port 8765
```

Open `http://localhost:8765/?token=<token>` once for the phone-connected product dashboard, or `http://localhost:8765/demo/?token=<token>` for the single-device web demo (the page remembers the token).

> **Why port 8765:** this Windows machine has a port proxy on 8000 that resets `localhost:8000`.
> Don't use `--host 0.0.0.0` on shared Wi-Fi.

> **Set `SCROLLSENSE_TOKEN` before running `cloudflared tunnel --url http://127.0.0.1:8765`.** The
> tunnel makes the server public, and every queued Short spends Gemini credits.

- **Without a key:** `SCROLLSENSE_MOCK=1` gives placeholder output, stored in `data/mock_clips/`.
- **Batch-analyse:** `uv run python -m scrollsense [--force] <url> [<url> ...]` (cached in `data/clips/`).
- **Tests:** `uv run pytest`

## The demo page (`/demo/`)

`/demo/` is a single-device web demo of the whole loop on one screen (while `/` stays the phone-connected product dashboard with **Only software sees** and **Clinician sees** tabs):

### Run the demo on localhost

```bash
uv run uvicorn scrollsense.server:app --reload --port 8765
# or without API calls:
# SCROLLSENSE_MOCK=1 uv run uvicorn scrollsense.server:app --reload --port 8765
# or with live Gemini re-analysis on every viewer's first watch:
# SCROLLSENSE_LIVE_INFERENCE=1 SCROLLSENSE_WORKERS=6 uv run uvicorn scrollsense.server:app --reload --port 8765
```

Then open **`http://localhost:8765/demo/?token=<token>`** (omit `?token=...` if `SCROLLSENSE_TOKEN` is unset in `.env`).

- **User sees (left):** the phone plays a scripted Shorts feed (`web/demo/demo-feed.json`): upbeat,
  then a run of low-mood Shorts, then upbeat again. Scroll, swipe or press ↑/↓ to move; tap or
  Space to pause. Every Short shown is a real view event.
- **Check-in card:** when the drift passes the 1 SD alarm, a card slides up on the phone, as the
  patient sees it, with its three options stacked.
  "I want to take a break" closes the feed; **Continue scrolling** brings it back.
- **Want to test your own video?** Paste a YouTube Short URL and it plays next. The phone shrinks
  with the window height so this box stays on screen.
- **Only software sees (right, first tab):** a compact trend strip on top (drift per analysed
  Short, the 1 SD alarm line, a dotted mark where each check-in was sent, and a status line with
  any active check-in cooldown), then the Short's text
  description and the mood map of the recent Shorts with the low-mood zone (highlighted when a
  check-in is sent).
- **Clinician sees (second tab, `#clinician` opens it):** this session's check-ins with the drift
  that caused each and the answer, in red, then an **example history** (clearly labelled, invented
  data in `web/demo/app.js`): two weeks of check-ins per day, totals and each check-in with its answer.
  The tab shows the number of check-ins this session.
- **Live inference** (`SCROLLSENSE_LIVE_INFERENCE=1`): each viewer's first view of a Short starts
  a fresh Gemini run (about 2 to 6 s), so results arrive after the video, never ahead of it.
  Until it is done the text panel says Analyzing; older stored results stay hidden.
- **Reset demo** (top right) erases the demo viewer and starts over.

Each browser gets its own viewer (`demo-xxxxxxxx`, kept in localStorage; `?viewer=demo-name` pins
one). Share `https://<tunnel>/demo/?token=<token>`. With the scripted feed and window 5 the warning
and the check-in card show around Short 9, a few seconds after that Short starts.

The only limit on Gemini is the queue's pace: at most `SCROLLSENSE_RPM` analyses start per minute
(default 20), for all visitors together. When many people scroll at once, Shorts wait their turn
and the text panel keeps saying Analyzing.

| Variable | Default | Meaning |
|---|---|---|
| `SCROLLSENSE_LIVE_INFERENCE` | `0` | `1`: a fresh run on each viewer's first view of a Short |
| `SCROLLSENSE_RPM` | `20` | Analyses started per minute, at most |

Set `SCROLLSENSE_WORKERS=6` with live inference so the queue keeps up with scrolling.

Rebuild the feed from the analysed clips with `PYTHONPATH=. uv run python scripts/build_demo_feed.py`
(keeps only embeddable Shorts and leaves out ones about death or self-harm).

## Deploy the demo on Modal

`modal_app.py` runs the same FastAPI app in **one always-warm container** (the queue, its pacer
and the demo sessions live in memory, and the analysis threads must keep running). Data lives in
`/tmp`, so a restart starts every session fresh.

```bash
uv run --with modal modal token new      # once: log in to Modal in the browser
scripts/deploy_modal.sh serve            # optional: temporary dev URL, Ctrl-C stops it
scripts/deploy_modal.sh                  # deploy: prints the public URL
```

The script sends only `GEMINI_API_KEY` from `.env` to a Modal secret named `scrollsense`, pins the
dependencies from `uv.lock` into `requirements.lock.txt`, and deploys. Demo settings (live
inference, 6 workers, 20 analyses per minute, window 5) are in `modal_app.py`. The deployed demo
needs **no token**: share the URL as it is. Anyone can use it, so the only limit on Gemini is the
20 analyses per minute (and anyone could list or erase demo sessions through the API). The warm container uses Modal credits around
the clock: stop it after the event with `uv run --with modal modal app stop scrollsense-demo`.

## Drift detection

The last `SCROLLSENSE_DRIFT_WINDOW` analysed Shorts (first view only) are compared with a global
affect norm. There is no personal baseline, so a feed that is heavy from the first Short is
flagged too. Levels stay `learning` until the window is half full. Details and evaluation:
`docs/clinical-calibration.md`.

- **Norm:** Warriner, Kuperman & Brysbaert (2013) word ratings mapped from 1-9 onto 1-5:
  valence 3.03 ± 0.64, arousal 2.61 ± 0.45 (NRC VAD 2018 as a cross-check).
- **Rule:** effect per axis = (window mean − norm centre) / norm SD. Within 1 SD is the normal
  range. A **warning** is a drift that points into the bottom-left quadrant (valence and arousal
  both at or below the norm) and is longer than 1 SD. The score is that length, 0 in any other
  direction.
- **No crisis or suicide alerts:** the feed signal is not reliable enough for that.

| Variable | Default | Meaning |
|---|---|---|
| `SCROLLSENSE_DRIFT_WINDOW` | `5` | Window in analysed Shorts |
| `SCROLLSENSE_DRIFT_WATCH` | `1.0` | `watch` above this many SD into the bottom left (≥ 1) |
| `SCROLLSENSE_DRIFT_WARN` | `1.0` | `warning` above this many SD (≥ 1); above watch brings back a watch band |

```bash
uv run python -m scrollsense.drift test-patient            # read-only text report
PYTHONPATH=. uv run python scripts/tune_drift.py           # simulated-feed evaluation
python -I scripts/build_affect_norms.py --lexicons DIR     # rebuild the norms (lexicons not shipped)
```

## Patient nudge

**Research prototype, not a medical device.** When the last `SCROLLSENSE_NUDGE_STREAK` judged
points are all `warning` (by default the first warning is enough), no card is open and the
cooldown has passed, the next view receipt carries a card. The userscript sends each view the
moment a Short opens and, while one is open, an empty batch every 2 s, so the card shows a few
<<<<<<< HEAD
seconds after the warning forms (analysis about 2 s, plus up to 2 s): "How do these videos feel right now?" with three equal options: I am okay, I want
to take a break, Not now. "I want to take a break" pauses the video and closes the tab (or
switches to a blank page). There is no "refresh my feed" option, because steering the feed
would erase the signal. The card never names a diagnosis, a mood or a video. Design:
`docs/patient-nudge-plan.md`.

| Variable | Default | Meaning |
|---|---|---|
| `SCROLLSENSE_NUDGE_ENABLED` | `1` | `0` turns nudges off |
| `SCROLLSENSE_NUDGE_STREAK` | `1` | Consecutive judged points at `warning` |
| `SCROLLSENSE_NUDGE_COOLDOWN_S` | `900` | Seconds of cooldown after answering a card (15 min) |
| `SCROLLSENSE_NUDGE_OK_FACTOR` | `1` | Cooldown multiplier after "I am okay" |
| `SCROLLSENSE_NUDGE_EXPIRE_S` | `900` | An unanswered card stops showing after this |
| `SCROLLSENSE_NUDGE_QUIET_FROM` / `_QUIET_TO` | unset | Quiet hours (local hour 0-23) |
| `SCROLLSENSE_NUDGE_TZ_OFFSET_MIN` | `120` | Local time for quiet hours, minutes east of UTC |

## API

All routes need `Authorization: Bearer <token>` when `SCROLLSENSE_TOKEN` is set.

| Method and path | Returns |
|---|---|
| `GET /api/meta` | `{analyser: {name, mock}, live}` |
| `GET /api/clips`, `GET /api/clips/{id}` | clip summaries `{id, title, valence, arousal, stance}`; one full analysis |
| `POST /api/views` `{viewer, events: [{event_id, video_id or url, seen_at, dwell_s?, surface?, ...}]}` | 202 `{accepted, duplicates, queued, rejected, nudge}`; only `surface: "shorts"` is analysed |
| `GET /api/viewers` | `[{viewer, events, last_seen}]` |
| `GET /api/viewers/{v}/feed?limit=50` | newest events first, each with `state` and `clip` once scored |
| `GET /api/viewers/{v}/drift` | `{viewer, level, note, config, affect_baseline, recent, pending, score, features, reasons, evidence, timeline}` |
| `GET /api/viewers/{v}/nudges` | nudge history, newest first, with each answer and `state` |
| `POST /api/viewers/{v}/nudges/{id}/response` `{choice}` | 204; 404 unknown, 409 already answered, 422 not an option |
| `DELETE /api/viewers/{v}` | 204; erases the viewer's views and nudges (GDPR) |
| `GET /api/queue` | `{depth, in_flight, done, failed, recent_failures}` |
| `POST /api/demo/shorts` `{viewer, url}` | 201 `{video_id, state}`; in cache mode queues the Short (live mode analyses it when viewed); 400 bad input |

Other settings: `SCROLLSENSE_WORKERS` (2), `SCROLLSENSE_RPM` (20 analyses per minute, 0 = unpaced),
`SCROLLSENSE_DATA` (`data`).

### Analysis speed

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_PIPELINE` | `one_call` | `one_call`: Gemini watches the Short at low resolution and returns a short description and the scores in one call. `two_stage`: a full text package (transcript, visuals, audio), then scoring from the text |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` (one_call), `gemini-4-hydrogen` (two_stage) | Overrides the pipeline's model |
| `GEMINI_THINKING_OFF` | `0` | `1` turns thinking off (one_call); `gemini-3.5-flash-lite` rejects it, `gemini-3.1-flash-lite` accepts it |
| `GEMINI_MAX_WATCH_S` | `30` | Gemini watches at most the first this many seconds of a video (`0`: all of it), so a long video never stalls the demo |

Measured on 10 Shorts: `one_call` with `gemini-3.5-flash-lite` takes about 2 s (median; 2.3 s at
most, up to about 8 s under load) and matched the stored two-stage valence on all 10;
`gemini-3.1-flash-lite` without thinking is as fast but less perceptive; `two_stage` takes 20-30 s.
People watch a Short for about 14-16 s on average, so `one_call` results arrive before the swipe.
With `one_call` the page's **Details** (transcript, on-screen text, visuals, audio) stay empty.

**Slower models do not score better.** On 41 Shorts covering every valence and arousal level
(plus the 6 longest), compared with the stored two-stage `gemini-4-hydrogen` analyses:

| One call, low resolution | Median | Slowest | Valence exact (MAE) | Arousal exact (MAE) | Low-mood agrees |
|---|---|---|---|---|---|
| `gemini-3.5-flash-lite`, 30 s cap (default) | 3.4 s | 5.7 s | 28/41 (0.39) | 18/41 (0.59) | 39/41 |
| `gemini-3.5-flash-lite`, no cap | 2.7 s | 6.5 s | 30/41 (0.37) | 22/41 (0.46) | 37/41 |
| `gemini-3.5-flash` | 7.7 s | 11.5 s | 28/41 (0.39) | 18/41 (0.56) | 37/41 |
| `gemini-3.8-flash` | 8.6 s | 11.7 s | 26/41 (0.41) | 17/41 (0.59) | 36/41 |
| `gemini-4-hydrogen` | 11.8 s | 20.5 s | 29/41 (0.29) | 21/41 (0.49) | 38/41 |

Differences of a few Shorts are within run-to-run noise; hydrogen's slightly lower valence error
is the same model as the reference. Arousal is the noisy axis for every model.

## Structure

A pure core inside a shell of swappable parts (see `rules/`).

| File | Role |
|---|---|
| `scrollsense/schemas.py`, `prompts.py` | Structured-output models (`TextPackage`, `ClipScores`, `QuickAnalysis`) and the prompts |
| `scrollsense/domain.py`, `views.py` | Pure values: `VideoId`, `ClipAnalysis`, `ViewerId`, `ViewEvent` |
| `scrollsense/drift/` | Drift against the affect norm: pure core and the text CLI |
| `scrollsense/affect_norms.py`, `reference/affect_norms.json` | The global affect norm |
| `scrollsense/nudge.py`, `nudgelog.py`, `nudge_api.py` | Nudge policy and cards, JSONL log, routes |
| `scrollsense/ports.py` | Interfaces: `ContentAnalyser`, `AnalysisStore`, `ViewLog`, `NudgeLog`, `Nudger` |
| `scrollsense/gemini.py`, `mock.py` | `ContentAnalyser` implementations (one-call and two-stage Gemini, mock) |
| `scrollsense/store.py`, `viewlog.py` | JSON and JSONL storage |
| `scrollsense/service.py`, `analysis_queue.py`, `intake.py` | Describe-then-score pipeline, paced queue, view intake |
| `scrollsense/scheduling.py` | Cached or live analysis scheduling |
| `scrollsense/api.py`, `views_api.py`, `drift_api.py`, `demo_api.py`, `auth.py` | HTTP routes and the Bearer guard |
| `scrollsense/composition.py`, `server.py`, `__main__.py` | Settings and wiring, entry points |
| `modal_app.py`, `scripts/deploy_modal.sh` | The web demo on Modal |
| `web/index.html`, `app.js`, `demo-feed.json` | The demo page and its scripted feed (no build step) |
| `web/scrollsense.user.js` | The phone userscript |

## Notes and limits

- **YouTube only:** Gemini reads public YouTube URLs directly (preview feature, up to 8 hours of
  video per day). Private videos fail; TikTok can't be fetched.
- **Use a paid-tier key:** only public video URLs and their text packages go to Gemini; no
  patient data does.
- **Not validated:** the norm is for words, not videos, and the thresholds are checked on
  simulated feeds only.
