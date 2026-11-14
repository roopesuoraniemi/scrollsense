# Affect calibration of the drift detector (14 Nov 2026)

Drift is measured against one global yardstick from published research: where everyday English
words sit on valence and arousal, mapped onto the scoring model's 1-5 scales. There is no
personal baseline.

**Defaults:** `SCROLLSENSE_DRIFT_WINDOW=10`, `SCROLLSENSE_DRIFT_WATCH=1.0`, `SCROLLSENSE_DRIFT_WARN=1.0`.

> This describes the content a feed showed. It does not describe the person and is not a
> diagnosis. Research prototype, not a medical device.

## 1. The norm: word-affect ratings mapped onto the LLM scales

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
- **NRC is only a cross-check for the spread.** Best-worst scaling ranks words against each other, so its mean of 0.5 says nothing about where "neutral" is. Its wider spread (0.86 and 0.68 on 1-5) suggests the Warriner SDs are, if anything, narrow.

**Shipped values:**
- `scrollsense/reference/affect_norms.json` holds the derived numbers with full provenance. It is built by `python -I scripts/build_affect_norms.py --lexicons DIR` (standard library only).
- **The raw lexicons are not in the repository.** NRC VAD is licensed for non-commercial use only.
- **SD convention:** population SD. It reproduces the published 1.2748.
- `affect_norms.py` loads the file at the edge, and `server.py` and the CLI inject it into `DriftDetector`.

## 2. The rule: drift into the bottom-left quadrant, longer than 1 SD

- **Effect per axis** = (window mean - norm centre) / norm SD, using the research SDs as they are
  (valence 0.637, arousal 0.448; no floor, no weights).
- **Drift** = the vector of the two effects. Its length is the distance from the norm in SD.
- **Normal range:** within 1 SD, by definition.
- **Warning:** the drift points into the bottom-left quadrant (valence and arousal both at or
  below the norm) and is longer than 1 SD. The affect score is that length; in any other
  direction it is 0, so calm but happy feeds and agitated feeds never count.
- **Watch:** off by default (watch = warn = 1.0). Setting `SCROLLSENSE_DRIFT_WARN` above 1.0
  makes the band between the two thresholds `watch`. Neither threshold may be below 1 SD.
- **On the page:** the dashed ellipse on the affect map is exactly the 1 SD edge, so an arrow tip
  outside it, pointing down-left, is a warning.

## 3. Evaluation on simulated feeds

**Test set:** the 50 real analysed Shorts in `data/sim/clips` (labels in `scripts/test_shorts.json`; 25 heavy, 25 light, `gemini-4-hydrogen`).

| Set | Mean valence | Mean arousal |
|---|---|---|
| Heavy | 2.60 | 2.12 |
| Light | 4.08 | 3.64 |

**Method** (`PYTHONPATH=. uv run python scripts/tune_drift.py`): random feeds of these analyses, 300 sessions per scenario per window. Each simulated view gets a unique synthetic video id, because the detector counts a Short once.

| Scenario | Feed | What counts |
|---|---|---|
| steady 15% heavy | 45 Shorts at 15% heavy | any warning is false |
| steady 0% heavy | 45 light Shorts | any warning is false |
| steady 30% heavy | 45 Shorts at 30% heavy (stress test) | any warning is false |
| full drift | 20 Shorts at 15% heavy, then 20 heavy | share warned, Shorts until warning |
| partial drift | 20 Shorts at 15% heavy, then 20 at 60% heavy | share warned |
| heavy from the start | 20 heavy Shorts | share warned, Shorts until warning |

**Results (watch = warn = 1.0):**

| Scenario | Window 10 | Window 14 |
|---|---|---|
| steady 15% heavy, false warnings | 0% | 0% |
| steady 0% heavy, false warnings | 0% | 0% |
| steady 30% heavy, false warnings | 2% | 0% |
| full drift: warned, median Shorts until warning | 99%, 10 | 95%, 13 |
| partial drift: warned | 14% | 3% |
| heavy from the start: warned, median Shorts until warning | 99%, 5 | 99%, 7 |

**Reading it:** the rule almost never raises a false warning, and catches a switch to a heavy
feed within about one window. It is strict: a feed that is only partly heavy rarely moves the
window average more than 1 SD. Window 10 is the default because it reacts faster for a demo.

## 4. Caveats

- **Word norms describe single English words, not video content.** The linear mapping from 1-9 (or 0-1) ratings onto the LLM's 1-5 video scores is nominal, not calibrated. The "norm" is a reference point, not the typical Short.
- **The evaluation is simulated:** a small pool (25 + 25 Shorts), one model, synthetic sessions, no real viewers and no clinical outcome to validate against. The numbers show that the detector behaves sensibly. They are not clinical validity.
