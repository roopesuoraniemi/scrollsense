# kNN z-scores for drift (14 Nov 2026)

> **All numbers come from simulated sessions over 50 analysed Shorts (25 heavy, 25 light), not from patients.**

**Verdict:** keep the mean-shift detector (V0) for the level. kNN anomaly does not detect drift towards depression-themed content in this data. If it is added at all, it is a separate "novelty" line that never raises the level.

## What kNN z-scoring is
- Each Short gets a distance: its mean distance to its k nearest Shorts in the person's baseline. Leave-one-out distances inside the baseline give a mean and SD, so each Short also gets a z ("how unusual is this for this person").
- A rolling window of the last 10 Shorts averages those z values into one window score, which is then compared with a threshold.

## Variants
| Variant | Space | Per-Short score |
|---|---|---|
| V0 | five features: valence, arousal, negative affect, theme load, dwelling | current `DriftDetector`, risk-direction effect sizes |
| V1 | 3072-d text-package embedding, cosine | kNN z (k = 3/5/8); "window z" = mean z × √n |
| V2 | standardised features: V0's five, or valence/arousal/neg/pos + A1–A9 | kNN z, Euclidean |
| V3a | embedding | V1 z, counted only when content-axis x is above the baseline mean |
| V3b | embedding | V1 z, counted only when valence is below or theme load above the baseline mean |
| V4 | embedding | kNN distance to the baseline minus distance to the 25 heavy reference Shorts (the scored clip is excluded) |

## Method
- **Harness:** the same as `docs/drift-tuning.md`.
  - The baseline is the first 20 Shorts and the window is 10.
  - A session is judged once at least 5 Shorts follow the baseline.
  - Every view gets a synthetic id.
  - In kNN, a Short is never its own neighbour, and copies of the same clip are not neighbours either. Simulated feeds repeat clips; real feeds rarely repeat a video.
- **Fair thresholds:** each variant's watch and warning thresholds are set so that it has V0's false-alarm rate on 1,000 steady calibration sessions (seed 11): **3% watch, 1% warning**. Test scenarios use 300 different sessions each (seed 7).
- **Scenarios:**

  | Scenario | Baseline | Then | Measures |
  |---|---|---|---|
  | steady | 15% heavy | 25 Shorts, same mix | false alarms |
  | full drift | 15% heavy | 20 heavy | Shorts to warning, misses |
  | partial drift | 15% heavy | 20 Shorts at 60% heavy | share caught |
  | topic shift | light topics A (cats, dogs, recipes, satisfying) | light topics B (football, comedy, Japan travel, iPhone tips, life hacks), and the reverse | false warnings |
  | demo steady / demo | 0% heavy | 25 light / 20 heavy | false warnings / speed and misses |

- **Re-run:** `PYTHONPATH=. uv run python scripts/knn_drift_eval.py` (about 1 minute, no API calls).

## Results
| Variant | Watch / warn | False watch | False warning | Full drift: Shorts to warning (median) | Full drift missed | Partial caught | Topic shift: false warning | Demo steady: false warning | Demo: Shorts to warning | Demo missed |
|---|---|---|---|---|---|---|---|---|---|---|
| **V0 mean-shift (current)** | 1.20 / 1.50 | 4% | 1% | **5** | **12%** | **47%** | **0%** | 0% | **5** | **0%** |
| V1 emb kNN k=3 | 1.16 / 1.41 | 3% | 1% | never | 95% | 2% | 36% | 1% | never | 71% |
| V1 emb kNN k=5 | 1.19 / 1.42 | 3% | 1% | never | 94% | 2% | 42% | 2% | never | 70% |
| V1 emb kNN k=8 | 1.27 / 1.51 | 3% | 1% | never | 94% | 2% | 45% | 1% | never | 74% |
| V1 k=5, window z | 3.45 / 3.99 | 4% | 2% | never | 92% | 3% | 46% | 1% | never | 61% |
| V2 5-feature kNN | 3.02 / 4.87 | 2% | 0% | never | 88% | 8% | 0% | 0% | 5 | 0% |
| V2 13-feature kNN | 2.46 / 3.80 | 2% | 1% | never | 88% | 8% | 0% | 0% | 5 | 0% |
| V3a emb kNN + axis gate | 0.75 / 1.08 | 2% | 0% | never | 83% | 6% | 4% | 2% | 9 | 33% |
| V3b emb kNN + affect gate | 0.84 / 1.06 | 2% | 1% | never | 87% | 7% | 1% | 8% | 7 | 31% |
| V4 baseline vs heavy | 1.56 / 2.08 | 3% | 1% | 15 | 47% | 22% | 14% | 0% | 5 | 0% |

"never" means that most sessions never reach warning, so the median is the no-detection value.

**Mean cosine distance between embeddings:**

| | Heavy | Light A | Light B |
|---|---|---|---|
| Heavy | 0.552 | 0.663 | 0.613 |
| Light A | | 0.615 | 0.608 |
| Light B | | | 0.552 |

## Reading it
- **kNN asks "seen anything like this before?" A realistic baseline has.** About 3 of its 20 Shorts are already heavy, so later heavy Shorts find close neighbours and score as normal. This hits every kNN variant, in either space: 83–95% of full drifts are missed. V0 compares means, so a feed that becomes *mostly* heavy still moves it.
- **The embedding encodes topic and format more than mood.** Heavy Shorts are about as far from light topic B (0.613) as light topics are from each other (0.608–0.615). So embedding anomaly is topic novelty:
  - it misses 70% of drifts even from a purely light baseline;
  - it gives a false warning on 42% of harmless topic shifts.
- **Gating by direction (V3) removes the topic-shift false alarms but not the misses.** The content axis is also fit on these same 50 Shorts, so V3a is optimistic.
- **V4 is the best kNN variant, and still worse than V0** (47% missed vs 12%). It also gives 14% topic-shift false warnings. Its reference set is the same pool the drift sessions draw from, so it is optimistic too.
- **V2 matches V0 on the demo baseline only.** There, the light Shorts all sit at one point in feature space (valence 4–5, no themes), so any heavy Short is an outlier.

## Recommendation
- **Do not replace V0.** Nothing here beats it on any detection column at the same false-alarm budget.
- **Do not combine kNN into the level.** OR-ing in embedding novelty would add about 40% false warnings on harmless topic changes.
- **Optional, later:** show "unusual for this person" (embedding kNN z) as an informational *novelty* line next to the level, never raising it. Revisit with real feeds, where baselines are longer and more varied.

## If adopted (novelty line only)
- **Seam:** add a `DriftMethod` protocol in `drift/core.py`. It maps `(baseline, recent) -> per-Short scores + window score`. `MeanShift` (today's code) and `KnnNovelty` implement it.
  - `SCROLLSENSE_DRIFT_METHOD` selects the method for the level (default `mean_shift`).
  - `SCROLLSENSE_NOVELTY=1` turns on the novelty line.
  - `Observation` needs the embedding vector, or the analysis, next to `scores`.
- **Report fields:**
  - `novelty: float | None`, the window mean of the per-Short z;
  - `novelty_level: "usual" | "unusual"`;
  - `EvidenceItem.novelty_z`, to rank "least like their normal" Shorts;
  - `novelty_note`, for example "Recent Shorts are unlike this person's usual topics". Never a risk claim.
- **UI:** one grey line under the level in the clinician dashboard, with no colour escalation.
- **Cost:**
  - About 9 ms per report from raw 3072-d vectors for 20 baseline and 20 recent Shorts, including the timeline.
  - About 0.2 ms per report with a cached distance matrix. V0's full report takes about 14 ms.
  - No extra API calls, because the embedding already exists. Memory is 30 × 3072 floats per viewer.

## Risks
- **Embedding model changes:** distances from a different model, or a different text-package prompt, are not comparable. The baseline must be re-embedded or re-learned, as `ContentAxis` already guards with `embed_model`.
- **Small baselines:** below about 20 Shorts, the leave-one-out mean and SD rest on a handful of distances, and k=5 covers a quarter of the baseline. z swings widely, so withhold novelty below `baseline_n`.
- **Distance concentration in 3072-d:** all pairwise cosine distances fall in about 0.45–0.66. Differences of a few hundredths decide everything, so the SD floor and the k choice matter more than they should.
- **Repeats:** a real feed that shows the same video twice gives a zero distance. It must be deduplicated by video id, as `observe` already does.
- **Leakage in this test:** the content axis (V3a) and the heavy reference set (V4) come from the same 50 Shorts as the sessions.
- **Limits:**
  - 50 Shorts, one analysis model, one embedding model, simulated sessions, no real people.
  - These numbers compare methods. They say nothing clinical.
