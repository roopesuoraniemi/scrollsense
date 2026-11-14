# Drift threshold tuning (14 Nov 2026)

**Defaults:** `SCROLLSENSE_DRIFT_WINDOW=10`, `SCROLLSENSE_DRIFT_WATCH=1.2`, `SCROLLSENSE_DRIFT_WARN=1.5`, `SCROLLSENSE_BASELINE_N=20`.

## Method
- **Test set:** 50 real public Shorts (`scripts/test_shorts.json`), analysed with `gemini-4-hydrogen` into `data/sim/clips`.
  - 25 "heavy": depression psychoeducation, sad edits, burnout, insomnia, numbness, "I'm a burden".
  - 25 "light": animals, cooking, sport, comedy, tips.
- **How the sets score:**

  | Set | Valence | Negative affect | Theme load | Dwelling stance |
  |---|---|---|---|---|
  | Heavy | ≈ 2.6 | ≈ 1.6 | ≈ 3.2 | 39% |
  | Light | ≈ 4.1 | 0 | 0 | 0% |

  The scoring separates the two sets well.
- **Simulation:** feeds are random sequences of these analyses. Each simulated view gets its own video id, because the detector counts a video once and real feeds rarely repeat. Each config runs 300 sessions per scenario:
  - **steady:** a 20-Short baseline, then 25 more Shorts from the same mix. Any watch or warning is a false alarm.
  - **full drift:** baseline, then 20 heavy Shorts. Measures Shorts until warning, and misses.
  - **partial drift:** baseline, then 20 Shorts at 60% heavy. Measures the share of sessions that reach warning.
- **Two baselines:**
  - *realistic*: 15% heavy mixed into the normal feed
  - *demo*: purely light (scroll neutral content, then press "Set baseline now")
- **Re-run:** `PYTHONPATH=. uv run python scripts/tune_drift.py` (the setup command is in its docstring).

## Results (full 25 + 25 pool)

| Baseline | Window | Watch | Warn | False watch | False warning | Heavy Shorts to warning (median) | Missed full drift | Partial drift caught |
|---|---|---|---|---|---|---|---|---|
| realistic | 10 | **1.2** | **1.5** | 3% | 1% | 5 | 11% | 42% |
| realistic | 10 | 1.0 | 1.3 | 7% | 2% | 5 | 4% | 60% |
| realistic | 8 | 1.2 | 1.5 | 6% | 2% | 4 | 10% | 52% |
| demo | 10 | **1.2** | **1.5** | 0% | 0% | 5 | 0% | 91% |
| demo | 10 | 1.0 | 1.3 | 0% | 0% | 5 | 0% | 98% |

Before tuning, watch was 0.8: false "watch" in 16–38% of steady sessions (first grid, partial pool).

## Reading it
- **Fast enough for a live demo:** about 5 heavy Shorts after the baseline give a warning, because judging starts once the window is half full.
- **Watch and warning often fire together on abrupt drift.** A sudden all-heavy feed jumps straight past watch. Watch matters more for gradual drift.
- **The realistic-baseline trade-off:** a wide baseline (heavy Shorts already in it) makes moderate drift hard to see. If the clinic prefers sensitivity, use `WATCH=1.0 WARN=1.3`: catches 60% vs 42% of partial drifts, with 2% vs 1% false warnings.
- **Limits:**
  - Simulated sessions, a small pool, one model, no real patients.
  - Real feeds change gradually, and an algorithm's drift may lag the person.
  - These numbers show that the detector behaves sensibly. They are not clinical validity.

## Bug found while tuning (fixed)
4 of 50 describe calls came back empty with `finish_reason: RECITATION`: Gemini refuses to quote copyrighted text, typically song lyrics in music edits, and our prompt asks for verbatim transcripts. Each one raised a JSON validation error.
- `GeminiAnalyser.describe` now retries once with `PARAPHRASE_PROMPT` ("paraphrase, don't quote").
- `score` retries once on malformed output.
- All 11 Shorts lost to these crashes (including the rest of their CLI batches) then analysed fine.
