# Clinical calibration of the drift detector (14 Nov 2026)

Drift is no longer measured against each viewer's own first Shorts. It is measured against two
global yardsticks taken from published research:

1. **Affect:** where everyday English words sit on valence and arousal (published word norms),
   mapped onto the scoring model's 1–5 scales.
2. **Clinical:** the PHQ-9's definition of depression, applied to the *themes of the content* in
   the recent window of Shorts.

**Defaults:** `SCROLLSENSE_DRIFT_WINDOW=10` (was 14; changed for a faster demo), `SCROLLSENSE_DRIFT_WATCH=1.0`, `SCROLLSENSE_DRIFT_WARN=1.0`
(SDs of drift into the bottom-left quadrant).

> **Update (14 Nov 2026, afternoon): the affect rule is now geometric, not tuned.** Within 1 SD of
> the norm is the normal range by definition. A deviation (`warning`) is a drift of the window's
> mean (valence, arousal) that points into the bottom-left quadrant (both at or below the norm)
> and is longer than 1 research SD (Euclidean length of the two effects; no SD floor, no
> weights). Any other direction scores 0. The sections below on SD floors, weights and the tuned
> 0.2 / 0.3 thresholds describe the previous rule; their simulation numbers are not re-run. The PHQ-9 cutoffs are fixed by the research and are not settings.

> This describes the content a feed showed. It does not describe the person and is not a
> diagnosis. Research prototype, not a medical device.

## 1. Affect baseline: word-affect norms mapped onto the LLM scales

| | Warriner, Kuperman & Brysbaert (2013) | Mohammad (2018), NRC VAD Lexicon v1 |
|---|---|---|
| Reference | Behav Res Methods 45:1191–1207, doi 10.3758/s13428-012-0314-x | ACL 2018, P18-1017 |
| Words | 13,915 lemmas | 20,007 words (19,971 in the file) |
| Rating method | 1–9 Likert | 0–1 best–worst scaling (relative ranking) |
| Split-half reliability V / A / D | 0.914 / 0.689 / 0.770 | 0.95 / 0.90 / 0.91 |
| Valence mean, SD (median) | 5.0638, 1.2748 (5.20) | 0.500 by construction, 0.2157 |
| Arousal mean, SD (median) | 4.2106, 0.8964 (4.11) | 0.500 by construction, 0.1711 |
| Mapping onto 1–5 | x′ = 1 + (x − 1) / 2 | x′ = 1 + 4x |
| **Valence on 1–5: centre, SD** | **3.032, 0.637** | 3.000, 0.863 |
| **Arousal on 1–5: centre, SD** | **2.605, 0.448** | 3.000, 0.684 |
| Download | https://raw.githubusercontent.com/JULIELab/XANEW/master/Ratings_Warriner_et_al.csv | https://www.saifmohammad.com/WebDocs/Lexicons/NRC-VAD-Lexicon.zip |
| Licence | Supplementary material of the article; check the authors' terms before redistributing | Non-commercial research and education only |

Cross-check over the 13,855 words in both lexicons: r = 0.814 for valence and 0.615 for arousal.

**Design:**
- **Warriner supplies the centre and SD.** It is a Likert scale like ours.
- **NRC is only a cross-check for the spread.** Best–worst scaling ranks words against each other, so its mean of 0.5 says nothing about where "neutral" is. Its wider spread (0.86 and 0.68 on 1–5) suggests the Warriner SDs are, if anything, narrow.
- **SD floors stay at 0.5.** So valence uses 0.637 and arousal uses max(0.448, 0.5) = 0.5.
- **Effect** = (recent mean − norm centre) / floored SD. Only falls count (risk direction down).
- **Affect score** = weighted mean of the risk effects (valence weight 1, arousal 0.5).

**Shipped values:**
- `scrollsense/reference/affect_norms.json` holds the derived numbers with full provenance. It is built by `python -I scripts/build_affect_norms.py --lexicons DIR` (standard library only).
- **The raw lexicons are not in the repository.** NRC VAD is licensed for non-commercial use only.
- **SD convention:** population SD. It reproduces the published 1.2748.
- `affect_norms.py` loads the file at the edge, and `server.py` and the CLI inject it into `DriftDetector`.

## 2. Clinical yardstick: the PHQ-9, applied to content

**Source:** Kroenke, Spitzer & Williams (2001), *The PHQ-9: validity of a brief depression severity measure*, J Gen Intern Med 16:606–613 (PMC1495268).
- **Items:** each of the nine DSM criteria is scored 0 "not at all", 1 "several days", 2 "more than half the days", 3 "nearly every day", over the last 2 weeks.
- **Bands:** "PHQ-9 scores of 5, 10, 15, and 20 represented mild, moderate, moderately severe, and severe depression."
- **Validated cutoff:** a score ≥ 10 had 88% sensitivity and 88% specificity for major depression.
- **Diagnostic algorithm:**
  - *Major depression:* 5 or more of the 9 criteria present at least "more than half the days", one of them depressed mood or anhedonia.
  - *Other depression:* 2–4 such criteria, one of them depressed mood or anhedonia.
- **Use both:** a 2014 meta-analysis (Manea et al.) found the algorithm less sensitive than the ≥ 10 cutoff.

**The content analogue** (`scrollsense/drift/clinical.py`, pure). It measures content exposure, not the person's symptoms.

| Step | Rule |
|---|---|
| Window | the last 14 analysed Shorts (one per PHQ-9 day); judged once at least 7 are analysed |
| Criterion present in a Short | theme score ≥ 2 ("central theme"); 1 = "merely mentioned" does not count |
| Item score from the share of window Shorts | < 2/14 → 0 "not at all"; 2/14 up to and including 1/2 → 1 "several days"; > 1/2 and < 12/14 → 2 "more than half the days"; ≥ 12/14 → 3 "nearly every day" |
| Exposure score | sum of the nine item scores, 0–27 |
| Band | minimal < 5, mild 5–9, moderate 10–14, moderately severe 15–19, severe ≥ 20 |
| Pattern | "major" / "other" / "none" by the algorithm above (an item counts at score ≥ 2) |
| Clinical level | `warning` if exposure ≥ 10 or pattern "major"; `watch` if exposure ≥ 5 or pattern "other"; else `normal` |

Shares are exact fractions, so boundaries are exact. With a 14-Short window the thresholds are whole Shorts: 2, 8 and 12.

**Overall level** = the more severe of the affect level and the clinical level. `timeline` gives the level of the window ending at each analysed Short. The nudge policy (warning streak) reads it unchanged.

### Decisions on the open points

- **Window of 14 rather than 10.** It mirrors the PHQ-9's 14 days, so "several days", "more than half" and "nearly every day" become 2, 8 and 12 Shorts. With 10 Shorts they become 2, 6 and 9: "several days" starts at 20% instead of 14%, and "nearly every day" needs 90%.
  - *Cost:* the first judgement comes after 7 Shorts (5 with 10), and an abrupt drift takes about 3 more Shorts to warn (median 11 vs 8 heavy Shorts).
  - *Gain:* clinical "watch" fires about three times as often on a full drift (42% vs 15%), and false alarms stay lower on a busier feed (2% vs 6% false warnings on a 30% heavy steady feed).
  - *To switch:* `SCROLLSENSE_DRIFT_WINDOW=10` is the fallback for a faster live demo.
- **"More than half" means strictly more than half (> 0.5).** This is the PHQ wording, so 7 of 14 is "several days" and 8 of 14 is "more than half the days".
- **The personal baseline was removed, not kept as a mode.** A `SCROLLSENSE_BASELINE_MODE=personal` option would have kept two report shapes, a baseline store and its port, two endpoints, two UI buttons and their tests. It would also have reintroduced the main flaw this rework fixes: a feed that is heavy from the start is learned as normal.
  - The detector, report, API and UI now have a single global path.
  - Legacy `views/<viewer>.baseline.json` files are no longer read, written or erased.

### Deviations from the PHQ-9 (on purpose)

- **Content, not a person.** A Short stands in for a day, and "central theme in the Short" stands in for "bothered by the problem that day". Each Short is scored by an LLM, not self-reported.
- **A9 counts like every other item.** Some PHQ-9 versions count the suicide item at "several days" in the algorithm. A9 alerts were removed from this app, so A9 has no special threshold and triggers nothing on its own.
- **"Several days" starts at 2 of 14.** The PHQ-9 leaves "several" undefined. One Short in 14 counts as "not at all".
- **Item scores come from a sliding window.** The PHQ-9 is asked once, about a fixed past fortnight. Here a window is judged at every new Short.

## 3. Evaluation on simulated feeds

**Test set:** the 50 real analysed Shorts in `data/sim/clips` (labels in `scripts/test_shorts.json`; 25 heavy, 25 light, `gemini-4-hydrogen`).
- **How the sets score:**

  | Set | Mean valence | Mean arousal |
  |---|---|---|
  | Heavy | 2.60 | 2.12 |
  | Light | 4.08 | 3.64 |

- **Central criteria (score ≥ 2) per heavy Short:** 0 for 3 Shorts, 1 for 17, 2 for 5. Never more than 2.
- **Share of heavy Shorts where each criterion is central:**

  | A1 | A2 | A3 | A4 | A5 | A6 | A7 | A8 | A9 |
  |---|---|---|---|---|---|---|---|---|
  | 44% | 20% | 0% | 8% | 0% | 12% | 16% | 4% | 4% |

- **Light Shorts** have no central criterion.

**Method** (`PYTHONPATH=. uv run python scripts/tune_drift.py`): random feeds of these analyses, 300 sessions per scenario per window. Each simulated view gets a unique synthetic video id, because the detector counts a Short once.

| Scenario | Feed | What counts |
|---|---|---|
| steady 15% heavy | 45 Shorts at 15% heavy | any watch / warning is false |
| steady 0% heavy | 45 light Shorts | any watch / warning is false |
| steady 30% heavy | 45 Shorts at 30% heavy (stress test, not a target) | any watch / warning is false |
| full drift to heavy | 20 Shorts at 15%, then 20 heavy | sessions warned within the 20, and median Shorts to warning |
| partial drift 60% | 20 Shorts at 15%, then 20 at 60% heavy | sessions warned within the 20 |
| heavy from the start | 20 heavy Shorts from the first one | sessions warned, and median Shorts to warning |

**Tuning:**
- **What was tuned:** only the affect watch/warn thresholds.
- **Target:** ≤ 2% false warnings on the 15%-heavy steady feed.
- **Result:** every pair in the grid (watch 0.05–0.3, warn 0.1–0.5) met the target with 0% false warnings. The light Shorts sit far above the word norm.
- **Choice:** warn 0.3, the lowest value that also keeps the doubled-heaviness stress feed at ≤ 2% false warnings. Watch 0.2 keeps false watches on that feed at 3%.

Window 14, affect thresholds by warn (watch 0.2; the affect-only columns, from the script's grid):

| Warn | False warning, 15% steady | False warning, 30% steady | Full drift warned (median Shorts) | Partial 60% warned | Heavy from start warned |
|---|---|---|---|---|---|
| 0.2 | 0% | 3% | 100% (11) | 26% | 100% |
| **0.3** | **0%** | **2%** | **100% (11)** | **18%** | **100%** |
| 0.4 | 0% | 1% | 99% (12) | 12% | 100% |
| 0.5 | 0% | 0% | 95% (13) | 8% | 99% |

### Results with the defaults (window 14, watch 0.2, warn 0.3)

Share of sessions that reach watch / warning; median Shorts until warning (from the drift start, or from the first Short).

| Scenario | Affect only | Clinical only (PHQ-9 style) | Combined (shipped) |
|---|---|---|---|
| steady 15% heavy (false alarms) | 0% / 0% | 0% / 0% | **0% / 0%** |
| steady 0% heavy (false alarms) | 0% / 0% | 0% / 0% | **0% / 0%** |
| steady 30% heavy (stress) | 3% / 2% | 1% / 0% | 3% / 2% |
| full drift to heavy | 100% / 100%, 11 Shorts | 42% / 0% | **100% / 100%, 11 Shorts; 0% missed** |
| partial drift 60% | 26% / 18% | 2% / 0% | 28% / 18% |
| heavy from the start | 100% / 100%, 7 Shorts | 66% / 0% (watch after 13) | **100% / 100%, 7 Shorts** |

Same thresholds with `SCROLLSENSE_DRIFT_WINDOW=10`, for comparison:

| Scenario | Affect only | Clinical only | Combined |
|---|---|---|---|
| steady 15% heavy | 0% / 0% | 0% / 0% | 0% / 0% |
| steady 0% heavy | 0% / 0% | 0% / 0% | 0% / 0% |
| steady 30% heavy | 12% / 6% | 1% / 0% | 12% / 6% |
| full drift to heavy | 100% / 100%, 8 Shorts | 15% / 0% | 100% / 100%, 8 Shorts |
| partial drift 60% | 55% / 43% | 3% / 0% | 56% / 43% |
| heavy from the start | 100% / 100%, 5 Shorts | 58% / 0% | 100% / 100%, 5 Shorts |

### Reading it

- **Heavy from the start is now caught.** Every session warns within its 20 Shorts, and 92% warn at the first judged point (Short 7). The old personal baseline learned the first 20 Shorts as "normal", so by construction it could never flag a feed that was heavy from the beginning.
- **The nudge** (streak of 2 warning points) comes one Short after the first warning.
- **No false alarms on realistic steady feeds.** The light test Shorts score well above the word norm (valence 4.08 vs 3.03), so a 15% heavy share never pulls the window mean below it.
- **Partial drift is the weak spot.** A 60/40 heavy/light mix still averages valence 3.19 and arousal 2.73, slightly *above* the norm, so the affect score stays near 0. Only windows that are heavier by chance warn. The old personal baseline caught 42% of these sessions because it measured against the light feed itself. A global norm cannot know that a viewer usually watches brighter content than average English words.
- **The clinical yardstick almost never warns on its own.** Reaching 10 needs broad symptom coverage, for example five criteria each central in more than half of the Shorts. The heavy test Shorts mostly carry one central criterion each (depressed mood in 44% of them), so a fully heavy window scores 2–6 (mostly 3–5) ("minimal" to "mild"), and "major" never occurs. It reaches `watch` in 42–66% of fully heavy sessions, which makes it an explainable second opinion ("depressed mood more than half the days").
  - Content with broader coverage would cross the validated cutoff: in the unit tests, five central criteria in every Short score 15.

## 4. Caveats

- **Word norms describe single English words, not video content.** The linear mapping from 1–9 (or 0–1) ratings onto the LLM's 1–5 video scores is nominal, not calibrated. The "norm" is a reference point, not the typical Short.
- **PHQ-9 cutoffs are validated for a person's self-report** of their own symptoms over two weeks. They are not validated for feed content, for LLM theme scores, or for "a Short" as a day. The content analogue is a screening-style signal about what a feed showed, never a diagnosis of anyone.
- **The evaluation is simulated:**
  - a small pool (25 + 25 Shorts), one model, synthetic sessions;
  - no real viewers, and no clinical outcome to validate against.
  - The numbers show that the detector behaves sensibly. They are not clinical validity.
- **The affect thresholds were tuned on this pool.** A real "normal" feed that sits closer to the norm than these light Shorts would raise false alarms. See the 30% stress row.
