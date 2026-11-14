"""Offline comparison: kNN anomaly z-scores vs the mean-shift drift detector.

Replays simulated feeds of the 50 real analysed Shorts in data/sim/clips (labelled in
scripts/test_shorts.json) through the current `DriftDetector` (V0) and several kNN variants,
with thresholds per variant set to V0's false-alarm budget on steady feeds. No API calls.

Run:  PYTHONPATH=. uv run python scripts/knn_drift_eval.py
"""
import json
import pathlib
import random
import statistics
import time
from dataclasses import dataclass
from functools import partial
from typing import Callable, Sequence

import numpy as np

from scrollsense.domain import ClipAnalysis, ContentAxis
from scrollsense.drift.core import DriftConfig, DriftDetector, observe
from scrollsense.schemas import CRITERIA, ClipScores
from scrollsense.views import ViewEvent

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASELINE_N = 20
WINDOW = 10
MIN_RECENT = 5
SESSIONS = 300
CALIBRATION_SESSIONS = 1000
BASE_HEAVY = 0.15
NOT_FOUND = 99  # "never warned", as in scripts/tune_drift.py
# Light topics split in two halves for the topic-shift scenario (keys of the "why" hint).
TOPIC_A = ("cat", "dog", "puppy", "recipe", "dinner", "dessert", "satisfying")
EMB_SD_FLOOR = 0.01   # cosine distance
FEAT_SD_FLOOR = 0.25  # standardised Euclidean distance
FEAT_FLOOR = 0.5      # per-feature SD floor for the 13-d space

Scores = np.ndarray  # window score per position after the baseline; nan = not judged yet
Scorer = Callable[["Pool", "Session"], Scores]


# ---------------------------------------------------------------- data

@dataclass(frozen=True)
class Pool:
    """The 50 analysed Shorts as arrays, indexed by clip number."""

    analyses: tuple[ClipAnalysis, ...]
    heavy: tuple[int, ...]
    light_a: tuple[int, ...]
    light_b: tuple[int, ...]
    cosine: np.ndarray       # (n, n) cosine distance between unit embeddings
    feats5: np.ndarray       # V0's five features
    feats13: np.ndarray      # valence, arousal, neg, pos, a1..a9
    axis_x: np.ndarray       # content-axis x (0 light centroid, 1 heavy centroid)

    @property
    def light(self) -> tuple[int, ...]:
        return self.light_a + self.light_b


def five(s: ClipScores) -> list[float]:
    return [s.valence, s.arousal, s.negative_affect, s.theme_load,
            float(s.stance == "dwelling_or_romanticising")]


def thirteen(s: ClipScores) -> list[float]:
    return [s.valence, s.arousal, s.negative_affect, s.positive_affect,
            *(s.score_of(c) for c in CRITERIA)]


def load_pool() -> Pool:
    sets = json.loads((ROOT / "scripts/test_shorts.json").read_text())
    clips = {p.stem: ClipAnalysis.model_validate_json(p.read_text())
             for p in (ROOT / "data/sim/clips").glob("*.json")}
    axis = ContentAxis.model_validate_json(
        (ROOT / "scrollsense/reference/content_axis.json").read_text())
    rows = [(x, "heavy") for x in sets["heavy"]] + [(x, "light") for x in sets["light"]]
    rows = [(x, kind) for x, kind in rows if x["id"] in clips]
    analyses = tuple(clips[x["id"]] for x, _ in rows)

    def in_a(why: str) -> bool:
        return any(key in why.lower() for key in TOPIC_A)

    heavy = tuple(i for i, (_, k) in enumerate(rows) if k == "heavy")
    light_a = tuple(i for i, (x, k) in enumerate(rows) if k == "light" and in_a(x["why"]))
    light_b = tuple(i for i, (x, k) in enumerate(rows) if k == "light" and not in_a(x["why"]))
    unit = np.array([np.asarray(a.embedding.vector) / np.linalg.norm(a.embedding.vector)
                     for a in analyses])
    projected = [axis.project(a) for a in analyses]
    return Pool(analyses=analyses, heavy=heavy, light_a=light_a, light_b=light_b,
                cosine=np.clip(1.0 - unit @ unit.T, 0.0, 2.0),
                feats5=np.array([five(a.scores) for a in analyses]),
                feats13=np.array([thirteen(a.scores) for a in analyses]),
                axis_x=np.array([p.x if p else np.nan for p in projected]))


@dataclass(frozen=True)
class Session:
    """Clip numbers in seen order: the baseline, then everything after it."""

    baseline: np.ndarray
    after: np.ndarray


def mixed(pool: Pool, p_heavy: float, n: int, rng: random.Random) -> list[int]:
    return [rng.choice(pool.heavy) if rng.random() < p_heavy else rng.choice(pool.light)
            for _ in range(n)]


def draw(choices: Sequence[int], n: int, rng: random.Random) -> list[int]:
    return [rng.choice(choices) for _ in range(n)]


def session(baseline: list[int], after: list[int]) -> Session:
    return Session(baseline=np.array(baseline), after=np.array(after))


def scenarios(pool: Pool, n: int, seed: int) -> dict[str, list[Session]]:
    rng = random.Random(seed)
    base = partial(mixed, pool, BASE_HEAVY, BASELINE_N)

    def topic_shift(i: int) -> Session:
        old, new = (pool.light_a, pool.light_b) if i % 2 == 0 else (pool.light_b, pool.light_a)
        return session(draw(old, BASELINE_N, rng), draw(new, 25, rng))

    return {
        "steady": [session(base(rng), mixed(pool, BASE_HEAVY, 25, rng)) for _ in range(n)],
        "full": [session(base(rng), draw(pool.heavy, 20, rng)) for _ in range(n)],
        "partial": [session(base(rng), mixed(pool, 0.6, 20, rng)) for _ in range(n)],
        "topic": [topic_shift(i) for i in range(n)],
        "demo_steady": [session(draw(pool.light, BASELINE_N, rng), draw(pool.light, 25, rng))
                        for _ in range(n)],
        "demo": [session(draw(pool.light, BASELINE_N, rng), draw(pool.heavy, 20, rng))
                 for _ in range(n)],
    }


# ---------------------------------------------------------------- V0: current detector

def synthetic(i: int) -> str:
    """Every simulated view is a distinct video: the detector counts a video once."""
    return f"sim{i:08d}"


def v0_scores(detector: DriftDetector, pool: Pool, s: Session) -> Scores:
    ids = [*s.baseline, *s.after]
    events = [ViewEvent(event_id=f"e{i}", viewer="sim", video_id=synthetic(i),
                        seen_at=1_000_000 + 10 * i) for i in range(len(ids))]
    analyses = {synthetic(i): pool.analyses[c] for i, c in enumerate(ids)}
    timeline = detector.report("sim", observe(events, analyses), None).timeline
    return np.array([np.nan if p.level == "learning" else p.score for p in timeline])


# ---------------------------------------------------------------- kNN machinery

def knn_mean(dist: np.ndarray, excluded: np.ndarray, k: int) -> np.ndarray:
    """Per row, the mean of the k smallest distances not excluded (fewer if fewer remain).

    Excluded are the same source clip: simulated feeds repeat clips, real ones rarely
    repeat a video, so a Short is never its own neighbour (this is also the leave-one-out)."""
    masked = np.where(excluded, np.inf, dist)
    nearest = np.sort(masked, axis=1)[:, :k]
    finite = np.isfinite(nearest)
    return np.where(finite, nearest, 0.0).sum(1) / np.maximum(finite.sum(1), 1)


def same_clip(rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    return rows[:, None] == cols[None, :]


@dataclass(frozen=True)
class Distances:
    """kNN distance of each baseline Short (leave-one-out) and each later Short."""

    baseline: np.ndarray
    after: np.ndarray


def embedding_distances(pool: Pool, s: Session, k: int) -> Distances:
    b, a = s.baseline, s.after
    return Distances(baseline=knn_mean(pool.cosine[np.ix_(b, b)], same_clip(b, b), k),
                     after=knn_mean(pool.cosine[np.ix_(a, b)], same_clip(a, b), k))


def standardised(feats: np.ndarray, s: Session, floors: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    base = feats[s.baseline]
    centre, scale = base.mean(0), np.maximum(base.std(0), floors)
    return (base - centre) / scale, (feats[s.after] - centre) / scale


def euclid(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.sqrt(((x[:, None, :] - y[None, :, :]) ** 2).sum(-1))


def feature_distances(feats: np.ndarray, floors: np.ndarray, pool: Pool, s: Session,
                      k: int) -> Distances:
    base, after = standardised(feats, s, floors)
    b, a = s.baseline, s.after
    return Distances(baseline=knn_mean(euclid(base, base), same_clip(b, b), k),
                     after=knn_mean(euclid(after, base), same_clip(a, b), k))


def heavy_contrast(pool: Pool, s: Session, k: int) -> Distances:
    """V4: distance to own baseline minus distance to the heavy reference set (positive =
    closer to heavy than to normal). A Short's own clip is never in either reference."""
    own = embedding_distances(pool, s, k)
    ref = np.array(pool.heavy)

    def to_heavy(rows: np.ndarray) -> np.ndarray:
        return knn_mean(pool.cosine[np.ix_(rows, ref)], same_clip(rows, ref), k)

    return Distances(baseline=own.baseline - to_heavy(s.baseline),
                     after=own.after - to_heavy(s.after))


def per_short_z(d: Distances, sd_floor: float) -> np.ndarray:
    """z of each later Short against the leave-one-out baseline distances."""
    return (d.after - d.baseline.mean()) / max(float(d.baseline.std()), sd_floor)


def windowed(per_short: np.ndarray, sqrt_n: bool) -> Scores:
    """Rolling window score at each position: the mean per-Short z over the last WINDOW,
    or that mean times sqrt(n) (a z for the window mean); nan until MIN_RECENT are in."""
    out = np.full(len(per_short), np.nan)
    for end in range(MIN_RECENT, len(per_short) + 1):
        w = per_short[max(0, end - WINDOW):end]
        out[end - 1] = w.mean() * (np.sqrt(len(w)) if sqrt_n else 1.0)
    return out


# Directional gates: True where a later Short is on the risky side of this person's baseline.
Gate = Callable[[Pool, Session], np.ndarray]


def axis_gate(pool: Pool, s: Session) -> np.ndarray:
    return pool.axis_x[s.after] > pool.axis_x[s.baseline].mean()


def affect_gate(pool: Pool, s: Session) -> np.ndarray:
    """Valence below or theme load above the baseline mean (label-free)."""
    base, after = pool.feats5[s.baseline], pool.feats5[s.after]
    return (after[:, 0] < base[:, 0].mean()) | (after[:, 3] > base[:, 3].mean())


DistanceFn = Callable[[Pool, Session, int], Distances]


def knn_scorer(distances: DistanceFn, sd_floor: float, k: int, sqrt_n: bool = False,
               gate: Gate | None = None) -> Scorer:
    def score(pool: Pool, s: Session) -> Scores:
        z = per_short_z(distances(pool, s, k), sd_floor)
        if gate is not None:
            z = np.where(gate(pool, s), np.maximum(z, 0.0), 0.0)
        return windowed(z, sqrt_n)
    return score


# ---------------------------------------------------------------- evaluation

@dataclass(frozen=True)
class Thresholds:
    watch: float
    warn: float


def first_reach(scores: Scores, threshold: float) -> int | None:
    hits = np.flatnonzero(np.nan_to_num(scores, nan=-np.inf) >= threshold)
    return int(hits[0]) + 1 if hits.size else None


def session_max(scores: Scores) -> float:
    judged = scores[~np.isnan(scores)]
    return float(judged.max()) if judged.size else -np.inf


def threshold_for(maxima: np.ndarray, rate: float) -> float:
    """A threshold that the session maxima reach in about `rate` of sessions."""
    ordered = np.sort(maxima)[::-1]
    m = int(round(rate * len(ordered)))
    if m <= 0:
        return float(ordered[0]) + 1e-6
    return float((ordered[m - 1] + ordered[m]) / 2) if m < len(ordered) else float(ordered[-1])


def calibrate(maxima: np.ndarray, watch_rate: float, warn_rate: float) -> Thresholds:
    return Thresholds(watch=threshold_for(maxima, watch_rate), warn=threshold_for(maxima, warn_rate))


@dataclass(frozen=True)
class Result:
    false_watch: float
    false_warn: float
    full_median: float
    full_miss: float
    partial_caught: float
    topic_false_warn: float
    demo_false_warn: float
    demo_median: float
    demo_miss: float


def rate(runs: list[Scores], threshold: float) -> float:
    return float(np.mean([session_max(r) >= threshold for r in runs]))


def speed(runs: list[Scores], threshold: float) -> tuple[float, float]:
    reached = [first_reach(r, threshold) for r in runs]
    median = statistics.median(x if x is not None else NOT_FOUND for x in reached)
    return float(median), float(np.mean([x is None for x in reached]))


def evaluate(runs: dict[str, list[Scores]], t: Thresholds) -> Result:
    full_median, full_miss = speed(runs["full"], t.warn)
    demo_median, demo_miss = speed(runs["demo"], t.warn)
    return Result(false_watch=rate(runs["steady"], t.watch), false_warn=rate(runs["steady"], t.warn),
                  full_median=full_median, full_miss=full_miss,
                  partial_caught=rate(runs["partial"], t.warn),
                  topic_false_warn=rate(runs["topic"], t.warn),
                  demo_false_warn=rate(runs["demo_steady"], t.warn),
                  demo_median=demo_median, demo_miss=demo_miss)


def run_all(scorer: Scorer, pool: Pool, sessions: dict[str, list[Session]]) -> dict[str, list[Scores]]:
    return {name: [scorer(pool, s) for s in group] for name, group in sessions.items()}


def per_report_ms(scorer: Scorer, pool: Pool, s: Session, repeats: int = 50) -> float:
    start = time.perf_counter()
    for _ in range(repeats):
        scorer(pool, s)
    return (time.perf_counter() - start) / repeats * 1000


def raw_embedding_report_ms(pool: Pool, s: Session, k: int, repeats: int = 50) -> float:
    """Timing without the precomputed distance matrix: normalise 30 raw 3072-d vectors,
    compute the 20x20 and 25x20 distances, kNN, z and the rolling timeline."""
    vectors = [pool.analyses[c].embedding.vector for c in [*s.baseline, *s.after]]
    start = time.perf_counter()
    for _ in range(repeats):
        m = np.asarray(vectors)
        unit = m / np.linalg.norm(m, axis=1, keepdims=True)
        base, after = unit[:BASELINE_N], unit[BASELINE_N:]
        d_base = knn_mean(1 - base @ base.T, np.eye(BASELINE_N, dtype=bool), k)
        d_after = knn_mean(1 - after @ base.T, np.zeros((len(after), BASELINE_N), bool), k)
        windowed((d_after - d_base.mean()) / max(d_base.std(), EMB_SD_FLOOR), False)
    return (time.perf_counter() - start) / repeats * 1000


def variants(detector: DriftDetector) -> dict[str, Scorer]:
    floors5 = np.array([0.5, 0.5, 0.5, 1.5, 0.15])  # V0's sd floors
    floors13 = np.full(13, FEAT_FLOOR)

    def feats(which: str, floors: np.ndarray) -> DistanceFn:
        return lambda pool, s, k: feature_distances(getattr(pool, which), floors, pool, s, k)

    emb = embedding_distances
    return {
        "V0 mean-shift (current)": partial(v0_scores, detector),
        "V1 emb kNN k=3": knn_scorer(emb, EMB_SD_FLOOR, 3),
        "V1 emb kNN k=5": knn_scorer(emb, EMB_SD_FLOOR, 5),
        "V1 emb kNN k=8": knn_scorer(emb, EMB_SD_FLOOR, 8),
        "V1 emb kNN k=5, window z": knn_scorer(emb, EMB_SD_FLOOR, 5, sqrt_n=True),
        "V2 5-feature kNN k=5": knn_scorer(feats("feats5", floors5), FEAT_SD_FLOOR, 5),
        "V2 13-feature kNN k=5": knn_scorer(feats("feats13", floors13), FEAT_SD_FLOOR, 5),
        "V3a emb kNN, axis gate": knn_scorer(emb, EMB_SD_FLOOR, 5, gate=axis_gate),
        "V3b emb kNN, affect gate": knn_scorer(emb, EMB_SD_FLOOR, 5, gate=affect_gate),
        "V4 emb baseline-vs-heavy": knn_scorer(heavy_contrast, EMB_SD_FLOOR, 5),
    }


def group_distances(pool: Pool) -> str:
    """Mean cosine distance between and within the labelled groups (different clips only)."""
    groups = {"heavy": pool.heavy, "light A": pool.light_a, "light B": pool.light_b}

    def mean(x: Sequence[int], y: Sequence[int]) -> float:
        rows, cols = np.array(x), np.array(y)
        return float(pool.cosine[np.ix_(rows, cols)][~same_clip(rows, cols)].mean())

    names = list(groups)
    pairs = [(a, b) for i, a in enumerate(names) for b in names[i:]]
    return ", ".join(f"{a}-{b} {mean(groups[a], groups[b]):.3f}" for a, b in pairs)


def fmt_pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def main() -> None:
    pool = load_pool()
    print(f"pool: heavy {len(pool.heavy)}, light topic A {len(pool.light_a)}, "
          f"light topic B {len(pool.light_b)}")
    print(f"mean cosine distance: {group_distances(pool)}")
    v0_config = DriftConfig(baseline_n=BASELINE_N, window=WINDOW)
    detector = DriftDetector(v0_config)
    calibration = scenarios(pool, CALIBRATION_SESSIONS, seed=11)["steady"]
    test = scenarios(pool, SESSIONS, seed=7)

    v0_cal = np.array([session_max(v0_scores(detector, pool, s)) for s in calibration])
    watch_rate = float(np.mean(v0_cal >= v0_config.watch))
    warn_rate = float(np.mean(v0_cal >= v0_config.warn))
    print(f"false-alarm budget from V0 on {CALIBRATION_SESSIONS} steady calibration sessions "
          f"(seed 11): watch {fmt_pct(watch_rate)}, warning {fmt_pct(warn_rate)}; "
          f"test: {SESSIONS} sessions per scenario (seed 7)\n")

    header = ("| Variant | watch / warn | False watch | False warning | Full drift: Shorts to warning "
              "| Full drift missed | Partial caught | Topic shift false warning "
              "| Demo steady false warning | Demo: Shorts to warning | Demo missed | ms/report |")
    print(header)
    print("|" + "---|" * (header.count("|") - 1))
    probe = test["full"][0]
    for name, scorer in variants(detector).items():
        if name.startswith("V0"):
            t = Thresholds(watch=v0_config.watch, warn=v0_config.warn)
        else:
            maxima = np.array([session_max(scorer(pool, s)) for s in calibration])
            t = calibrate(maxima, watch_rate, warn_rate)
        r = evaluate(run_all(scorer, pool, test), t)
        print(f"| {name} | {t.watch:.2f} / {t.warn:.2f} | {fmt_pct(r.false_watch)} | "
              f"{fmt_pct(r.false_warn)} | {r.full_median:g} | {fmt_pct(r.full_miss)} | "
              f"{fmt_pct(r.partial_caught)} | {fmt_pct(r.topic_false_warn)} | "
              f"{fmt_pct(r.demo_false_warn)} | {r.demo_median:g} | {fmt_pct(r.demo_miss)} | "
              f"{per_report_ms(scorer, pool, probe):.2f} |")
    print(f"\nemb kNN from raw 3072-d vectors (no precomputed matrix), 20 + 20 Shorts with "
          f"timeline: {raw_embedding_report_ms(pool, probe, 5):.2f} ms/report")
    print("V0 ms/report includes building the full DriftReport (evidence, summaries, timeline).")


if __name__ == "__main__":
    main()
