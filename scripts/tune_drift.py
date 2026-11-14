"""Tune and evaluate the globally calibrated drift detector on simulated feeds of real Shorts.

Replays random sequences of the 50 analysed test Shorts in data/sim/clips (labels in
scripts/test_shorts.json) through `DriftDetector.judge`, and reports affect-only,
clinical-only (PHQ-9-style, fixed cutoffs) and combined levels per scenario. Only the affect
watch/warn thresholds are tuned; see docs/clinical-calibration.md for the results.

Setup:  SCROLLSENSE_DATA=data/sim uv run python -m scrollsense $(python3 -c "import json;d=json.load(open('scripts/test_shorts.json'));print(*[x['id'] for x in d['heavy'][:25]+d['light'][:25]])")
Run:    PYTHONPATH=. uv run python scripts/tune_drift.py [--sessions 300] [--window 14]
"""
import argparse
import itertools
import json
import pathlib
import random
import statistics
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from scrollsense.affect_norms import load_affect_norms
from scrollsense.domain import ClipAnalysis
from scrollsense.drift.core import DriftConfig, DriftDetector
from scrollsense.drift.levels import SEVERITY, Level, most_severe
from scrollsense.drift.observe import Group, Observation

ROOT = pathlib.Path(__file__).resolve().parent.parent
SETS = json.loads((ROOT / "scripts/test_shorts.json").read_text())
CLIPS = {p.stem: ClipAnalysis.model_validate_json(p.read_text())
         for p in (ROOT / "data/sim/clips").glob("*.json")}
HEAVY = [x["id"] for x in SETS["heavy"] if x["id"] in CLIPS]
LIGHT = [x["id"] for x in SETS["light"] if x["id"] in CLIPS]
NORM = load_affect_norms().baseline
BASE_HEAVY = 0.15
LEAD_IN = 20      # Shorts of the usual feed before a drift starts
DRIFT_LEN = 20    # Shorts after the drift starts (or from the start, for heavy-from-start)
STEADY_LEN = 45   # same length as the old 20-Short baseline + 25 recent Shorts
MODES = ("affect", "clinical", "combined")
NEVER = 99
WATCH_GRID = (1.0, 1.25, 1.5)
WARN_GRID = (1.0, 1.25, 1.5, 2.0)


@dataclass(frozen=True)
class Point:
    """One judged prefix: the affect score and the (threshold-free) clinical level."""

    judged: bool
    score: float
    clinical: Level


@dataclass(frozen=True)
class Session:
    points: tuple[Point, ...]
    start: int    # index of the first Short after the drift starts (0 for steady feeds)


def observations(ids: Sequence[str]) -> tuple[Observation, ...]:
    # every simulated view is a distinct "video": real feeds rarely repeat
    return tuple(Observation(video_id=f"sim{i:08d}", title=v, seen_at=1_000_000 + 10.0 * i,
                             scores=CLIPS[v].scores) for i, v in enumerate(ids))


def replay(ids: Sequence[str], start: int, window: int) -> Session:
    detector = DriftDetector(DriftConfig(window=window), NORM)
    shown = Group(observations(ids))
    judged = [detector.judge(shown.upto(end).last(window)) for end in range(1, len(ids) + 1)]
    return Session(points=tuple(Point(judged=j.clinical_level != "learning", score=j.score or 0.0,
                                      clinical=j.clinical_level) for j in judged), start=start)


def mixed(p_heavy: float, n: int, rng: random.Random) -> list[str]:
    return [rng.choice(HEAVY) if rng.random() < p_heavy else rng.choice(LIGHT) for _ in range(n)]


SCENARIOS: dict[str, Callable[[random.Random], tuple[list[str], int]]] = {
    "steady 15% heavy": lambda rng: (mixed(BASE_HEAVY, STEADY_LEN, rng), 0),
    "steady 0% heavy": lambda rng: (mixed(0.0, STEADY_LEN, rng), 0),
    "steady 30% heavy": lambda rng: (mixed(0.3, STEADY_LEN, rng), 0),   # stress test, not a target
    "full drift to heavy": lambda rng: (mixed(BASE_HEAVY, LEAD_IN, rng) + mixed(1.0, DRIFT_LEN, rng),
                                        LEAD_IN),
    "partial drift 60%": lambda rng: (mixed(BASE_HEAVY, LEAD_IN, rng) + mixed(0.6, DRIFT_LEN, rng),
                                      LEAD_IN),
    "heavy from the start": lambda rng: (mixed(1.0, DRIFT_LEN, rng), 0),
}


def sessions(name: str, n: int, window: int) -> list[Session]:
    rng = random.Random(f"{name}-{window}")
    return [replay(*SCENARIOS[name](rng), window=window) for _ in range(n)]


def levels(session: Session, config: DriftConfig, mode: str) -> list[Level]:
    def one(p: Point) -> Level:
        if not p.judged:
            return "learning"
        affect = config.level_of(p.score)
        return {"affect": affect, "clinical": p.clinical,
                "combined": most_severe((affect, p.clinical))}[mode]
    return [one(p) for p in session.points[session.start:]]


def first(found: Iterable[Level], level: Level) -> int:
    return next((i + 1 for i, x in enumerate(found) if SEVERITY[x] >= SEVERITY[level]), NEVER)


@dataclass(frozen=True)
class Outcome:
    """Share of sessions reaching watch / warning, and median Shorts until each."""

    watch: float
    warning: float
    to_watch: float
    to_warning: float

    def row(self) -> str:
        def shorts(x: float) -> str:
            return "never" if x >= NEVER else f"{x:g}"
        return (f"{self.watch:5.0%} {self.warning:5.0%}  {shorts(self.to_watch):>5} "
                f"{shorts(self.to_warning):>5}")


def outcome(group: Sequence[Session], config: DriftConfig, mode: str) -> Outcome:
    watch = [first(levels(s, config, mode), "watch") for s in group]
    warn = [first(levels(s, config, mode), "warning") for s in group]
    return Outcome(watch=sum(w < NEVER for w in watch) / len(group),
                   warning=sum(w < NEVER for w in warn) / len(group),
                   to_watch=statistics.median(watch), to_warning=statistics.median(warn))


def grid(simulated: dict[str, list[Session]], window: int) -> None:
    print(f"\n== affect threshold grid, window {window} (affect-only; clinical is fixed)")
    print("watch  warn | steady15 FP watch/warn | steady0 FP | steady30 watch/warn | "
          "full: warned, median | "
          "partial warned | start warned")
    for watch, warn in itertools.product(WATCH_GRID, WARN_GRID):
        if watch > warn:
            continue
        config = DriftConfig(window=window, watch=watch, warn=warn)
        o = {name: outcome(group, config, "affect") for name, group in simulated.items()}
        print(f"{watch:5} {warn:5} | {o['steady 15% heavy'].watch:5.0%} "
              f"{o['steady 15% heavy'].warning:5.0%} | {o['steady 0% heavy'].warning:5.0%} | "
              f"{o['steady 30% heavy'].watch:5.0%} {o['steady 30% heavy'].warning:5.0%} | "
              f"{o['full drift to heavy'].warning:5.0%} {o['full drift to heavy'].to_warning:>4g} | "
              f"{o['partial drift 60%'].warning:5.0%} | {o['heavy from the start'].warning:5.0%}")


def table(simulated: dict[str, list[Session]], config: DriftConfig) -> None:
    print(f"\n== window {config.window}, affect watch {config.watch} warn {config.warn}")
    print(f"{'scenario':<22} {'mode':<9} watch  warn  →watch →warn")
    for name, group in simulated.items():
        for mode in MODES:
            print(f"{name:<22} {mode:<9} {outcome(group, config, mode).row()}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=int, default=300)
    parser.add_argument("--window", type=int, nargs="*", default=[10, 14])
    parser.add_argument("--watch", type=float, default=DriftConfig().watch)
    parser.add_argument("--warn", type=float, default=DriftConfig().warn)
    args = parser.parse_args()
    print(f"pool: heavy {len(HEAVY)}, light {len(LIGHT)}; {args.sessions} sessions per scenario")
    for window in args.window:
        simulated = {name: sessions(name, args.sessions, window) for name in SCENARIOS}
        grid(simulated, window)
        table(simulated, DriftConfig(window=window, watch=args.watch, warn=args.warn))


if __name__ == "__main__":
    main()
