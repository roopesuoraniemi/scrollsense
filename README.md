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

Open `http://localhost:8765/?token=<token>` once; the page remembers the token.

> **Why port 8765:** this Windows machine has a port proxy on 8000 that resets `localhost:8000`.
> Don't use `--host 0.0.0.0` on shared Wi-Fi.

> **Set `SCROLLSENSE_TOKEN` before running `cloudflared tunnel --url http://127.0.0.1:8765`.** The
> tunnel makes the server public, and every queued Short spends Gemini credits.

- **Without a key:** `SCROLLSENSE_MOCK=1` gives placeholder output, stored in `data/mock_clips/`.
- **Batch-analyse:** `uv run python -m scrollsense [--force] <url> [<url> ...]` (cached in `data/clips/`).
- **Tests:** `uv run pytest`

## The page

- **Warning panel:** the drift level, its size in SD and the number of Shorts judged, with a
  chart of the drift per Short and the 1 SD line.
- **Nudge panel** (green): the last three check-in cards sent to the phone and the answer.
- **Carousel:** thumbnails of the scrolled Shorts; flip with the arrows or the arrow keys.
  Flipping back pauses **Live**; press Live to follow the newest Short again.
- **Video and text package:** title, format, main message, meaning and cues; the transcript,
  on-screen text, visuals and audio are under **Details**.
- **Affect map:** valence by arousal for the Shorts in the drift window, the 1 SD normal
  range (dashed ellipse), the low-mood zone and an arrow from typical to their average that
  glides to its new position when a Short is analysed.

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
| `SCROLLSENSE_DRIFT_WINDOW` | `10` | Window in analysed Shorts |
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
seconds after the warning forms (analysis about 2 s, plus up to 2 s): "How do these videos feel right now?" with three equal options: I'm OK, I want
to take a break, Not now. "I want to take a break" pauses the video and closes the tab (or
switches to a blank page). There is no "refresh my feed" option, because steering the feed
would erase the signal. The card never names a diagnosis, a mood or a video. Design:
`docs/patient-nudge-plan.md`.

| Variable | Default | Meaning |
|---|---|---|
| `SCROLLSENSE_NUDGE_ENABLED` | `1` | `0` turns nudges off |
| `SCROLLSENSE_NUDGE_STREAK` | `1` | Consecutive judged points at `warning` |
| `SCROLLSENSE_NUDGE_COOLDOWN_S` | `600` | Seconds between cards (doubled after "I'm OK") |
| `SCROLLSENSE_NUDGE_OK_FACTOR` | `2` | Cooldown multiplier after "I'm OK" |
| `SCROLLSENSE_NUDGE_EXPIRE_S` | `900` | An unanswered card stops showing after this |
| `SCROLLSENSE_NUDGE_QUIET_FROM` / `_QUIET_TO` | unset | Quiet hours (local hour 0-23) |
| `SCROLLSENSE_NUDGE_TZ_OFFSET_MIN` | `120` | Local time for quiet hours, minutes east of UTC |

## API

All routes need `Authorization: Bearer <token>` when `SCROLLSENSE_TOKEN` is set.

| Method and path | Returns |
|---|---|
| `GET /api/meta` | `{analyser: {name, mock}}` |
| `GET /api/clips`, `GET /api/clips/{id}` | clip summaries `{id, title, valence, arousal, stance}`; one full analysis |
| `POST /api/views` `{viewer, events: [{event_id, video_id or url, seen_at, dwell_s?, surface?, ...}]}` | 202 `{accepted, duplicates, queued, rejected, nudge}`; only `surface: "shorts"` is analysed |
| `GET /api/viewers` | `[{viewer, events, last_seen}]` |
| `GET /api/viewers/{v}/feed?limit=50` | newest events first, each with `state` and `clip` once scored |
| `GET /api/viewers/{v}/drift` | `{viewer, level, note, config, affect_baseline, recent, pending, score, features, reasons, evidence, timeline}` |
| `GET /api/viewers/{v}/nudges` | nudge history, newest first, with each answer and `state` |
| `POST /api/viewers/{v}/nudges/{id}/response` `{choice}` | 204; 404 unknown, 409 already answered, 422 not an option |
| `DELETE /api/viewers/{v}` | 204; erases the viewer's views and nudges (GDPR) |
| `GET /api/queue` | `{depth, in_flight, done, failed, recent_failures}` |

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
| `scrollsense/api.py`, `views_api.py`, `drift_api.py`, `auth.py` | HTTP routes and the Bearer guard |
| `scrollsense/composition.py`, `server.py`, `__main__.py` | Settings and wiring, entry points |
| `web/index.html`, `app.js`, `scrollsense.user.js` | The laptop page and the phone userscript (no build step) |

## Notes and limits

- **YouTube only:** Gemini reads public YouTube URLs directly (preview feature, up to 8 hours of
  video per day). Private videos fail; TikTok can't be fetched.
- **Use a paid-tier key:** only public video URLs and their text packages go to Gemini; no
  patient data does.
- **Not validated:** the norm is for words, not videos, and the thresholds are checked on
  simulated feeds only.
