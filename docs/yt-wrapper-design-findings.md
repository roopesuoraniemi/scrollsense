# YT-Wrapper Design Iteration — Audit Findings, Solutions & Trade-Offs

> **Branch:** `feat/YT-wrapper-v2` (branched from `feat/YT-wrapper` @ `93a8afb`, cross-referenced against clinical and algorithmic evidence from `feat/docs`).

---

## 1. Executive Summary

`feat/YT-wrapper` established a clean hexagonal backend (`views.py`, `feed.py`, `intake.py`, `analysis_queue.py`, `views_api.py`) and an initial Violentmonkey userscript (`web/scrollsense.user.js`) to stream watched YouTube Shorts from a phone browser to ScrollSense.

Auditing `feat/YT-wrapper` end-to-end against [`docs/phone-prototype-plan.md`](phone-prototype-plan.md) and the scientific/pitch architecture on `feat/docs` (`pitch/narrative.md` and `research/evidence-and-sources.md`) surfaced **seven structural gaps and bugs** spanning sensing accuracy, concurrency safety, statistical bias, queue latency, offline mock fidelity, and a complete disconnect between the longitudinal readout API and the web UI.

This iteration resolves all seven while keeping the repository's **pure core / swappable shell** architecture intact (every `scrollsense/*.py` function $\le 9$ statements, $\le 3$ parameters, zero modified existing tests, 88 automated tests passing including a Node VM behavioural harness for the userscript).

---

## 2. Detailed Findings & Root-Cause Analysis

### Finding 1 — Longitudinal Readout & Closed-Loop Architecture Were Invisible in the UI
* **What was on `feat/YT-wrapper`:** `views_api.py` implemented `GET /api/viewers/{viewer}/readout`, `DELETE /api/viewers/{viewer}`, and `GET /api/queue`, but `web/app.js` never called any of them. Meanwhile, commit `93a8afb` removed `spike/POC`'s URL submission input (`POST /api/analyze`), leaving no way to test individual Shorts from the laptop, inspect baseline-vs-current drift, compare against a control viewer, drill down from flags into verbatim evidence quotes, or erase viewer logs.
* **Solution shipped:** Redesigned the zero-build web workbench (`web/index.html`, `web/styles.css`, `web/app.js`) around two coupled views sharing a persistent live Shorts filmstrip and deterministic A9 safety banner:
  1. **Clip inspector:** 4-stage multimodal inspection (`Watched Short → Creator-neutral TextPackage → Affect circumplex & viewer-scoped Semantic 2-D PCA with baseline-to-current centroid drift arrow → DSM-5 A1–A9 content themes`), plus inline manual Short logging and single-click retry/re-analysis.
  2. **Drift & home loop:** Cluster triage cards (`Sleep & circadian`, `Anhedonia & narrowing`, `Worthlessness & self-blame`), quantitative **Baseline vs Current vs Control** table (explicitly badging platform-wide shifts suppressed by the control feed), chronological rolling exposure trajectory SVG, clickable flag-to-evidence quote drill-down, state-matched JITAI resets + **2-minute Comfort-Anchor recommender re-seed** links, and GDPR Art. 17 viewer erasure.

---

### Finding 2 — Five Concrete Sensing & Concurrency Bugs in `web/scrollsense.user.js`

| # | Bug in `scrollsense.user.js` v0.2 | Impact in Live Demo / Real Use | Fix in `scrollsense.user.js` v0.3 + Backend |
| :- | :--- | :--- | :--- |
| **2a** | **Swipe-out-only emission + 5 s timer** | Opening Short #1 sent nothing until the viewer swiped *away* and waited up to 5 s. On stage, watching a 30 s Short meant **30–35 s of blank dashboard** before Gemini even started, and the final Short watched before closing was lost. | Added optional `watching: ActiveWatch` + `paused` on `ViewBatch` (`views.py`, `intake.py`, `views_api.py`) and immediate swipe flush. Landing on `/shorts/{id}` immediately notifies the server (`< 1 s`), shows a pulsing live pill in `/feed` & `/viewers`, and starts Gemini *while the user is still watching*. |
| **2b** | **Wall-clock dwell (`now - started`)** | Locking the phone or switching apps for 2 hours on `/shorts/{id}` recorded `dwell_s = 7200` seconds, contradicting `docs/phone-prototype-plan.md` (*"counts time only while the page is visible"*). | Replaced wall-clock subtraction with 250 ms visible-only delta integration (`document.visibilityState === 'visible'`) plus `visibilitychange` and `pagehide` handlers that immediately close and flush open segments. |
| **2c** | **Overlapping `flush()` data-loss race & timeout deadlock** | `flush()` had no `inFlight` mutex, sliced `buffer = buffer.slice(sent)` on response, and lacked `timeout` / `ontimeout` / `onabort` handlers. Overlapping flushes deleted unsent newer events, and a hung mobile tunnel XHR wedged `inFlight` permanently. | Guarded XHR with `inFlight` + `flushQueued` latch, added 10 s `timeout` with unified `onerror`/`ontimeout`/`onabort` recovery, and removed acknowledged events by ID set (`buffer.filter(e => !sentIds.has(e.event_id))`). Verified in `tests/test_userscript.py`. |
| **2d** | **`document.querySelector('video')` pool trap, missing `loops`, & swipe-out video bleed** | YouTube Shorts keeps pre-rendered offscreen `<video>` elements in the DOM; `querySelector('video')` read `NaN` or the wrong reel's duration, `loops` was never populated, and sampling `<video>` during swipe-out read the *next* Short's `currentTime = 0.1s` as a false loop wrap-around. | `activeVideo()` selects the playing (`!v.paused && readyState > 0`) or largest viewport-intersecting `<video>`; `sampleVideoPlayback()` tracks `duration_s` and wrap-arounds only while `id === current.id`, while `closeCurrent(now)` accumulates only the final visible `dwellMs` delta. |
| **2e** | **`http://localhost` broken, `/shorts` DOM lag, & mobile `prompt()` friction** | `origin()` unconditionally rewrote `http:` to `https:`, breaking desktop fallback testing against `http://127.0.0.1:8765`, and `/shorts` landing URLs without an ID or delayed `pushState` were missed. | Preserved `http://` on loopback (`localhost`, `127.0.0.1`, `[::1]`), added active-reel DOM / canonical URL fallback in `currentShortId()` + `yt-navigate-finish`/`popstate` listeners, and added **one-tap pairing** (`#scrollsense_pair=<base64url>`). |

---

### Finding 3 — Bridging Scientific Claims (`feat/docs`) With `scrollsense/feed.py`

Cross-referencing `scrollsense/feed.py` against `feat/docs/research/evidence-and-sources.md` exposed three places where the pure composition core was throwing away already-computed signals:

1. **Russell's 2-D Circumplex (`low_arousal_negative_share`):**
   * *Evidence (`feat/docs` §3.2 — Millgram et al., 2015; Yoon & Rottenberg, 2020):* Depressive media selection pulls specifically toward **low-valence, low-arousal** stimuli, whereas 1-D `negative_share` (`valence <= 2`) conflates sadcore withdrawal (`arousal <= 2`) with high-arousal outrage, horror, or breaking news (`arousal >= 4`).
   * *Fix:* Added `low_arousal_negative_share` (`valence <= 2 and arousal <= 2`) to `Composition`, `RULES`, the `anhedonia_hopelessness` cluster, and shaded the calm-negative quadrant directly on the Affect circumplex plot.

2. **Sample-Size-Invariant Semantic Dispersion (`semantic_dispersion`):**
   * *Evidence (`feat/docs` §3.5.1 — Saeb et al., 2015 location entropy analogue; Amir et al., 2017 embeddings):* Topical filter-bubble collapse happens in semantic space even when editing formats (`meme`, `talking_to_camera`, `broll_with_text`) remain mixed (`format_entropy` stays high).
   * *Statistical subtlety caught during design:* Naive spherical variance $1 - \|\bar{u}\|_2^2$ on unit vectors $\hat{u}_1, \dots, \hat{u}_k$ has expectation $1 - \frac{1}{k} - \frac{k-1}{k}\mu_{\cos}$, meaning a 4-clip current window appears artificially narrower than a 40-clip baseline window of *identical* topical diversity ($0.75$ vs $0.975$ for orthogonal topics!).
   * *Fix:* Derived and implemented the unbiased off-diagonal cosine dispersion estimator:
     $$\hat{\mu}_{\cos} = \frac{k\|\bar{u}\|_2^2 - 1}{k - 1}, \qquad \text{semantic\_dispersion} = \operatorname{clamp}_{[0,1]}\!\bigl(1 - \max(0, \hat{\mu}_{\cos})\bigr)$$
     which runs in $O(k \cdot d)$ time, requires no random seed, is invariant to 2-D PCA axis rotations, and yields identical values across $k = 2$ and $k = 100$ windows (verified in `tests/test_iteration.py`).

3. **Selective Attentional Dwell Maintenance (`dwell_negative_share`, `completion_rate`, `loop_share`):**
   * *Evidence (`feat/docs` §3.3 — Suslow et al., 2020 MDD eye-tracking meta-analysis, Hedges' $g = 0.66$ dysphoric dwell / $g = -0.51$ positive dwell; Newman et al., 2019 prospective relapse prediction; ByteDance "TikTok Algo 101" $E[\text{playtime}]$):* Before a feed saturates, a viewer's *dwell ratio* shifts — lingering 16–19 s (and looping) on heavy clips while swiping past everyday clips in 1 s.
   * *Fix:* Added watch-time-weighted `dwell_negative_share`, median bounded `completion_rate`, and `loop_share` to `Composition` and `RULES` (`+0.20` rise threshold for `dwell_negative_share`, suppressed if shared by `control`).

---

### Finding 4 — Queue Starvation on Skipped Shorts (`scrollsense/analysis_queue.py`)
* **Problem:** `docs/phone-prototype-plan.md` §3 specified *"prioritise events with dwell ≥ 2 s"*, yet `AnalysisQueue` used a single FIFO `deque`. Rapidly flicking past 8 irrelevant Shorts in $0.5\text{ s}$ each forced Gemini workers (and the RPM token bucket) to spend 40–80 s analysing skipped clips before scoring the clip the viewer actually stopped to watch.
* **Solution:** Upgraded `AnalysisQueue` to a two-lane priority queue (`__watched` ahead of `__skips`). Live arrivals (`watching` / `dwell_s is None`) and clips with `dwell_s >= 2.0` enter the high-priority lane; if a previously skipped video is watched again before a worker pops it, `enqueue_if_new(video, priority=True)` promotes it in place without double-counting queue depth.

---

### Finding 5 — Global vs Viewer-Scoped Semantic PCA (`scrollsense/views_api.py`)
* **Problem:** `ViewerReports.feed` passed `None` for every `ClipSummary.semantic` point, forcing `web/app.js` to fetch `/api/clips` (all stored clips across all viewers) on every 2 s poll and distorting `patient-01`'s PCA projection with `control-01` and CLI test clips.
* **Solution:** `ViewerReports.feed` now computes `semantic_points()` scoped strictly to that viewer's unique analysed clips and embeds `semantic: Point | None` directly on each `FeedItem.clip`, cutting redundant HTTP polling and enabling accurate **Baseline → Current centroid shift vectors** on both maps.

---

### Finding 6 — Same-Afternoon Demo Window Trap (`web/app.js`)
* **Problem:** `docs/phone-prototype-plan.md` §4 plans collecting 45 min of neutral baseline scrolling followed immediately by drift scrolling *on the same afternoon*. Under the hardcoded 24-hour default cutoff (`now - 86400`), both sessions land inside `current` (`last 24 h`) and `baseline` has `n_shown = 0`, silencing every delta and flag.
* **Solution:** Added a **Window preset selector** (`Last 24h vs prior`, `Last 2h vs prior`, and `Recent half vs earlier` midpoint split), plus an inline one-click recovery banner whenever `baseline.n_shown == 0` and `current.n_shown >= 4` under the 24 h preset.

---

### Finding 7 — Offline Mock Mode & `scripts/try_feed.sh` Calibration (`scrollsense/mock.py`)
* **Problem:** `MockAnalyser` previously set `format="other"` on every clip (`format_entropy == 0.0` always) and generated uncorrelated hashes where `try_feed.sh`'s `HEAVY` IDs received `valence = 4, arousal = 5` (producing zero flags offline). In addition, `scripts/try_feed.sh` set `OLD=$((NOW - 2 * 86400))` without anchoring local clock hours, so running the script at 04:00 local put baseline in `[00:00, 05:00)` too and running at 14:00 put current in daytime.
* **Solution:** Replaced random uncalibrated mock hashes with nine coherent `[MOCK]` archetypes spanning diverse formats, stances (`coping_or_recovery` vs `dwelling_or_romanticising`), and 32-D topic-clustered embeddings (plus one explicit opt-in ID `mockA9safet` for testing the deterministic A9 crisis path offline while keeping arbitrary IDs strictly `a9 = 0`). Updated `scripts/try_feed.sh` and the UI's one-click **Sample feed** seeder to anchor baseline at `14:00` local, `patient-01`'s drift at `02:15` local, and `control-01`'s current window at `14:00` local (so running the demo late at night never shifts `control-01` into `[00:00, 05:00)` or suppresses `patient-01`'s `night_share` flag).

---

## 3. Closed-Loop Design & Clinical / Regulatory Boundaries

Following `feat/docs` (`pitch/narrative.md` Beat 4 and `research/evidence-and-sources.md` §4.1 & §5.2), `scrollsense/loop.py` implements pure, deterministic decision-support rules with four explicit guardrails:

1. **Deterministic A9 Safety Override:** Any `a9_death_suicide >= 1` exposure in the current window (`safety_hits` non-empty) sets `safety_active = True`, surfaces immediate human crisis contacts (**MIELI Crisis Helpline Finland `09 2525 0111`**, **US/CA `988`**, **EU `112`**), and suppresses wellness micro-interventions so algorithmic nudges never substitute for crisis protocol.
2. **Zero-Prompt Stability Rule:** When `triage_level == "stable"` and no acute drift threshold is crossed, `resets` is empty (`()`). Respecting Astill Wright et al. (2026, $N = 17{,}123$), remitted users who are doing well receive zero nagging prompts.
3. **State-Matched Fast Loop + Recommender Hygiene:**
   * *Nocturnal shift (`night_share`, `a4_sleep`, `a6_fatigue`):* Circadian wind-down prompt.
   * *Calm-negative pull (`low_arousal_negative_share`, `mean_valence`):* Arousal-matched calm audio bridge (matching low arousal first before lifting valence; Yoon & Rottenberg, 2020).
   * *Filter-bubble contraction (`semantic_dispersion`, `dwell_negative_share`, dwelling themes):* **2-minute Comfort-Anchor feed re-seed** — launching user-customizable curiosity Shorts searches to re-weight minute-level session embeddings (Liu et al., 2022 *Monolith*; Leung et al., 2026).
   * *Anhedonic fatigue (`a2_anhedonia`, `a6_fatigue`, `a8_concentration`):* 60-second paced HRV breathing or brief active cognitive play (*Meru Health* / *Soihtu Meliora* JITAI routing).
4. **EU AI Act Art. 50(3) & MDR Discipline:** Stage 1 (`DESCRIBE_PROMPT`) continues to forbid inferring emotions or mental state of creators on screen; all UI copy and API models explicitly frame outputs as **content-exposure telemetry and longitudinal baseline-drift triage**, never automated diagnosis.

---

## 4. Remaining Risks & Recommended Next Steps When You Wake Up

1. **Verify `m.youtube.com/shorts` SPA URL Mutation on Physical Phone (10 min):**
   * `scrollsense.user.js` v0.3 polls `location.pathname` every 250 ms. On Firefox Android + Violentmonkey, confirm YouTube's mobile-web Shorts player updates `location.pathname` on every vertical swipe (and check that Android's *"Open supported links"* is disabled on the native YouTube app so Firefox stays in browser).
   * If iOS Safari or a mobile A/B experiment updates the active Reel DOM node without calling `history.pushState` on swipe, add a fallback reading the active `ytm-reel-item-renderer` / canonical link href inside `currentShortId()`.
2. **Tunnel End-to-End Check with One-Tap Pairing (5 min):**
   * Set `SCROLLSENSE_TOKEN` in `.env`, start `uvicorn scrollsense.server:app --port 8765`, run `cloudflared tunnel --url http://127.0.0.1:8765`, open the dashboard with `?token=<TOKEN>`, click **Pair phone**, paste the `https://….trycloudflare.com` URL into *Server URL*, install `/scrollsense.user.js` on Firefox Android, and open the generated `https://m.youtube.com/shorts#scrollsense_pair=…` link once.
3. **Live Gemini Rate-Limit & Quota Observation (`gemini-4-hydrogen`):**
   * Gemini YouTube-URL ingestion is a preview feature capped at 8 hours of video/day per project. Keep `SCROLLSENSE_RPM=20` and `SCROLLSENSE_WORKERS=2`; pre-warm your 8–10 primary stage demo Shorts into `data/clips/` before going on stage so cache hits return in `< 50 ms` while 1–2 live phone swipes run fresh on Gemini.
4. **Threshold Calibration Is Heuristic:**
   * All drift thresholds in `scrollsense/feed.py` (`THEME_SHARE_RISE = 0.15`, `MEAN_VALENCE_DROP = -0.5`, `DWELL_SHARE_RISE = 0.20`, `SEMANTIC_DISPERSION_DROP = -0.12`) are transparent prototype defaults designed for legibility over 10–50 clip windows, not clinically calibrated cutoffs. Prospective calibration requires the longitudinal post-TMS cohort proposed in `feat/docs`.
