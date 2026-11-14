# ScrollSense

**Your short-form feed knows when you're spiralling before you do.**  
*Built at Junction 2026 — a passive mood-drift detector and gentle check-in prototype for YouTube Shorts.*

![ScrollSense Dashboard](docs/assets/scrollsense_dashboard.jpg)

*Note: ScrollSense is a research prototype, not a medical device. Scores describe the **content**, never the person, and are not a diagnosis.*

---

## The problem

Short-form video algorithms are built to maximize watch time, not wellbeing. When a viewer lingers on a few heavy or melancholic clips, the feed quietly adapts — pulling them into a low-mood loop ("doomscrolling" or sadness spirals) that's hard to notice from the inside.

Current approaches to digital wellbeing don't catch this well:
- **Screen-time limits** only measure *how long* you scrolled, not *what* the feed was feeding you (30 minutes of comedy is very different from 30 minutes of despair).
- **Manual mood trackers** add friction and get abandoned.
- **Account scraping** is invasive and unnecessary.

## Why ScrollSense?

ScrollSense turns the Shorts you already watch into a **zero-friction, privacy-first affect signal** — and makes the invisible drift visible in real time:

- **Zero extra effort:** Just scroll YouTube Shorts normally. A lightweight userscript logs only the public video ID and dwell time.
- **Multimodal AI that gets internet culture:** Naive keyword filters miss irony, meme formats, and upbeat music over bleak captions. ScrollSense uses a two-stage Gemini pipeline where the model *watches* the Short first (visuals, audio, text overlays, subtext) and then scores its emotional tone.
- **Privacy by design:** Only public YouTube URLs are sent to Gemini — never your account, comments, or personal data.
- **Fun to watch in real time:** The live dashboard plots each Short on a 2D **valence × arousal affect map**, showing your feed's trajectory drifting relative to a global emotional norm.
- **Respectful nudges, not preachy blockers:** If the feed drifts into low-valence, low-arousal territory for consecutive Shorts, the phone can show a calm check-in card (*"How do these videos feel right now?"*) with three equal choices: *I'm OK*, *I want to take a break*, or *Not now*.

<!-- Media slot: add a side-by-side GIF of scrolling Shorts + the Affect Map moving in real time -->
<!-- ![Affect Map](docs/assets/affect-map.gif) -->

---

## How it works

```text
Phone (YouTube Shorts + Violentmonkey)
  │
  ├──► POST /api/views (video ID, timestamp, dwell time)
  │         │
  │         ▼
  │    Paced Queue ──► Gemini Stage 1: Video URL ──► TextPackage (speech, visuals, audio, irony)
  │                └─► Gemini Stage 2: TextPackage ──► ClipScores (valence, arousal, stance)
  │                                                         │
  │                                                         ▼
  │                                                Rolling Drift Engine (vs. global affect norm)
  │                                                         │
  ◄── Check-in card in receipt (if streak + cooldown) ◄─────┤
                                                            ▼
                                              Laptop Dashboard (feed, drift chart, affect map)
```

1. **Two-stage Gemini analysis (`scrollsense/service.py`):** Stage 1 watches the Short and extracts a structured `TextPackage` (transcript, on-screen text, visuals, audio mood, emotional cues, intended meaning). Stage 2 reads only that package, writes a rationale *before* any numbers, and outputs `ClipScores` (`valence` 1–5, `arousal` 1–5, `stance`, `hopeful`).
2. **Global-norm drift (`scrollsense/drift/`):** Compares the rolling window of analysed Shorts (default `10`, first views only) against a global affect norm (Warriner et al., 2013 mapped to 1–5: `valence 3.03 ± 0.64`, `arousal 2.61 ± 0.45`). Drifting `> 1 SD` into the bottom-left quadrant (low valence + low arousal) triggers a `warning`. See [docs/clinical-calibration.md](docs/clinical-calibration.md).
3. **Gentle check-in (`scrollsense/nudge.py`):** After consecutive warnings (default `2`), with cooldown and quiet hours, the next `/api/views` receipt delivers a check-in card. Choosing *"I want to take a break"* pauses the video and closes/blanks the tab. See [docs/patient-nudge-plan.md](docs/patient-nudge-plan.md).

<!-- Media slot: add a screenshot or GIF of the phone check-in card -->
<!-- ![Phone Nudge Card](docs/assets/nudge-card.png) -->

---

## Quick start

Requires Python **3.10+**, [`uv`](https://docs.astral.sh/uv/), and a paid-tier `GEMINI_API_KEY` (paid-tier prompts are not used to train Google's models).

```bash
uv sync
cp .env.example .env        # set GEMINI_API_KEY and SCROLLSENSE_TOKEN
uv run uvicorn scrollsense.server:app --reload --port 8765
```

Open `http://localhost:8765/?token=<your-token>` for the dashboard (the page remembers your token).

- **No API key? Run in mock mode:**
  ```bash
  SCROLLSENSE_MOCK=1 uv run uvicorn scrollsense.server:app --reload --port 8765
  ```
- **Connect your phone:** Set `SCROLLSENSE_TOKEN` first, expose port `8765` over HTTPS with `cloudflared tunnel --url http://127.0.0.1:8765`, install [web/scrollsense.user.js](web/scrollsense.user.js) in Violentmonkey (e.g. Firefox Android), and enter your tunnel URL + token when prompted on YouTube Shorts.

### Useful commands

```bash
uv run python -m scrollsense [--force] <url> [...]   # batch-analyse Shorts (cached in data/clips/)
uv run python -m scrollsense.drift test-patient      # print a text drift report
PYTHONPATH=. uv run python scripts/tune_drift.py     # evaluate drift rules on simulated feeds
uv run pytest                                        # run the test suite (99 tests)
```

---

## Technical reference

<details>
<summary><strong>Environment variables</strong> (<code>.env</code>)</summary>

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | — | Gemini API key (required unless `SCROLLSENSE_MOCK=1`) |
| `GEMINI_MODEL` | `gemini-4-hydrogen` | Model (`gemini-4-argon`, `gemini-4-carbon` also supported) |
| `SCROLLSENSE_TOKEN` | unset | Bearer token for all `/api/*` routes |
| `SCROLLSENSE_MOCK` | `0` | `1` uses placeholder analyses in `data/mock_clips/` |
| `SCROLLSENSE_WORKERS` / `_RPM` | `2` / `20` | Worker concurrency and rate limit (`0` = unpaced) |
| `SCROLLSENSE_DRIFT_WINDOW` | `10` | Rolling window in analysed Shorts |
| `SCROLLSENSE_DRIFT_WATCH` / `_WARN` | `1.0` / `1.0` | Bottom-left SD thresholds (`≥ 1.0`) |
| `SCROLLSENSE_NUDGE_ENABLED` | `1` | `0` disables phone check-in cards |
| `SCROLLSENSE_NUDGE_STREAK` | `2` | Consecutive `warning` points before nudging |
| `SCROLLSENSE_NUDGE_COOLDOWN_S` | `600` | Seconds between cards (multiplied by `OK_FACTOR=2` after *"I'm OK"*) |
| `SCROLLSENSE_NUDGE_EXPIRE_S` | `900` | Unanswered card expiry in seconds |
| `SCROLLSENSE_NUDGE_QUIET_FROM` / `_TO` | unset | Quiet hours (`0–23`, using `TZ_OFFSET_MIN=120`) |

</details>

<details>
<summary><strong>HTTP API</strong> (<code>Authorization: Bearer &lt;token&gt;</code> when token is set)</summary>

| Method & Path | Returns |
|---|---|
| `GET /api/meta` | `{analyser: {name, mock}}` |
| `GET /api/clips`, `GET /api/clips/{id}` | Clip summaries or one full analysis |
| `POST /api/views` | `202` `{accepted, duplicates, queued, rejected, nudge}` (only `surface: "shorts"` analysed) |
| `GET /api/viewers` | `[{viewer, events, last_seen}]` |
| `GET /api/viewers/{v}/feed?limit=50` | Newest events with `state` and `clip` |
| `GET /api/viewers/{v}/drift` | Full drift report (`level`, `score`, `affect_baseline`, `timeline`, etc.) |
| `GET /api/viewers/{v}/nudges` | Nudge history with answer and `state` |
| `POST /api/viewers/{v}/nudges/{id}/response` | Records `{choice}` (`204`; `404`/`409`/`422` on errors) |
| `DELETE /api/viewers/{v}` | `204`; erases viewer views and nudges |
| `GET /api/queue` | `{depth, in_flight, done, failed, recent_failures}` |

</details>

<details>
<summary><strong>Project structure</strong></summary>

```text
scrollsense/
├── domain.py, views.py          # Pure values: VideoId, ClipAnalysis, ViewerId, ViewEvent
├── schemas.py, prompts.py       # Structured-output schemas (TextPackage, ClipScores) & prompts
├── ports.py                     # Swappable interfaces (ContentAnalyser, AnalysisStore, Logs, Nudger)
├── gemini.py, mock.py           # Gemini and mock ContentAnalyser implementations
├── store.py, viewlog.py         # JSON and JSONL storage
├── service.py, analysis_queue.py, intake.py  # Describe-then-score pipeline, queue, intake
├── affect_norms.py              # Global affect norm loader (reference/affect_norms.json)
├── drift/                       # Pure drift math, levels, and text CLI
├── nudge.py, nudgelog.py, nudge_api.py       # Nudge policy, log, and routes
├── api.py, views_api.py, drift_api.py, auth.py  # FastAPI routes and Bearer auth
└── composition.py, server.py, __main__.py    # Wiring and entry points

web/                             # Zero-build dashboard (index.html, app.js) & phone userscript
docs/                            # Calibration notes and design plans
scripts/                         # Drift tuning and norm-building scripts
tests/                           # Unit and API test suite
```

</details>

---

## Limitations

- **YouTube Shorts only:** Gemini reads public YouTube URLs directly (preview feature, up to 8 hours/day); private videos fail and platforms like TikTok are not supported.
- **Not clinically validated:** The affect norm is derived from English word ratings (Warriner et al., 2013), and thresholds are tuned on simulated feeds rather than clinical trials.

---

## License

[MIT](LICENSE) — © 2026 Roope Suoraniemi, Milko Roine, Onni Seppänen
