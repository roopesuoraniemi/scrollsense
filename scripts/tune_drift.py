"""Tune drift thresholds: replay simulated feeds of real analysed Shorts (data/sim/clips) through the detector.

Setup:  SCROLLSENSE_DATA=data/sim uv run python -m scrollsense $(python3 -c "import json;d=json.load(open('scripts/test_shorts.json'));print(*[x['id'] for x in d['heavy'][:25]+d['light'][:25]])")
Run:    PYTHONPATH=. uv run python scripts/tune_drift.py
"""
import itertools, json, pathlib, random, statistics, sys

from scrollsense.domain import ClipAnalysis
from scrollsense.drift.core import DriftConfig, DriftDetector, observe
from scrollsense.views import ViewEvent

ROOT = pathlib.Path(__file__).resolve().parent.parent
SETS = json.load(open(ROOT / "scripts/test_shorts.json"))
clips = {p.stem: ClipAnalysis.model_validate_json(p.read_text()) for p in (ROOT / "data/sim/clips").glob("*.json")}
HEAVY = [x["id"] for x in SETS["heavy"] if x["id"] in clips]
LIGHT = [x["id"] for x in SETS["light"] if x["id"] in clips]
LEVELS = {"learning": -1, "normal": 0, "watch": 1, "warning": 2}


def synthetic(i):  # every simulated view is a distinct "video" (real feeds rarely repeat)
    return f"sim{i:08d}"


def events(ids):
    return [ViewEvent(event_id=f"e{i}", viewer="sim-01", video_id=synthetic(i), seen_at=1_000_000 + 10 * i)
            for i, v in enumerate(ids)]


def report(ids, cfg):
    analyses = {synthetic(i): clips[v] for i, v in enumerate(ids)}
    return DriftDetector(cfg).report("sim-01", observe(events(ids), analyses), None)


def timeline(ids, cfg):
    return report(ids, cfg).timeline


def draw(pool, n, rng):
    return [rng.choice(pool) for _ in range(n)]


def mixed(p_heavy, n, rng):
    return [rng.choice(HEAVY) if rng.random() < p_heavy else rng.choice(LIGHT) for _ in range(n)]


def first_index(tl, level, start):
    for i, point in enumerate(tl):
        if i >= start and LEVELS[point.level] >= LEVELS[level]:
            return i - start + 1
    return None


def run(cfg, seeds=300, base_p=0.15):
    rng = random.Random(7)
    fp_watch = fp_warn = 0
    det_watch, det_warn, miss = [], [], 0
    part_warn = 0
    for _ in range(seeds):
        # steady: baseline mix 15% heavy, then the same mix -> any warning is a false alarm
        tl = timeline(mixed(base_p, cfg.baseline_n, rng) + mixed(base_p, 25, rng), cfg)
        top = max((LEVELS[p.level] for p in tl), default=-1)
        fp_watch += top >= 1
        fp_warn += top >= 2
        # drift: baseline mix 15% heavy, then all heavy -> Shorts until watch / warning
        ids = mixed(base_p, cfg.baseline_n, rng) + draw(HEAVY, 20, rng)
        tl = timeline(ids, cfg)
        w, x = first_index(tl, "watch", 0), first_index(tl, "warning", 0)
        det_watch.append(w or 99)
        det_warn.append(x or 99)
        miss += x is None
        # partial drift: then 60% heavy for 20 Shorts
        tl = timeline(mixed(base_p, cfg.baseline_n, rng) + mixed(0.6, 20, rng), cfg)
        part_warn += any(p.level == "warning" for p in tl)
    return dict(fp_watch=fp_watch / seeds, fp_warn=fp_warn / seeds,
                med_watch=statistics.median(det_watch), med_warn=statistics.median(det_warn),
                miss=miss / seeds, partial_warn=part_warn / seeds)


if __name__ == "__main__":
    print(f"pool: heavy {len(HEAVY)}, light {len(LIGHT)}")
    for base_p in (0.15, 0.0):
        print(f"\n== baseline heavy share {base_p}")
        print("window watch warn | FP watch FP warn | med Shorts→watch →warn | miss | partial 60% warn")
        for window, watch, warn in itertools.product([8, 10], [1.0, 1.2], [1.2, 1.3, 1.5]):
            if watch > warn:
                continue
            cfg = DriftConfig(baseline_n=20, min_baseline=8, window=window, watch=watch, warn=warn)
            r = run(cfg, base_p=base_p)
            print(f"{window:6} {watch:5} {warn:4} | {r['fp_watch']:8.2f} {r['fp_warn']:7.2f} | "
                  f"{r['med_watch']:14} {r['med_warn']:5} | {r['miss']:4.2f} | {r['partial_warn']:.2f}")
