"""Print one viewer's drift report in the terminal, for tuning thresholds without the UI.

Usage:  uv run python -m scrollsense.drift <viewer> [--window N] [--baseline-n N]
            [--min-baseline N] [--watch X] [--warn Y] [--data DIR]

Flags override the SCROLLSENSE_* environment values (and `.env`); `--data` replaces
SCROLLSENSE_DATA. Read-only: it never marks a baseline or analyses anything.
"""
import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

from ..baselines import JsonBaselineStore
from ..composition import ROOT, DataDirs, Settings
from ..drift_api import FeedObserver
from ..schemas import Frozen
from ..store import JsonFileStore
from ..views import ViewerId
from ..viewlog import JsonlViewLog
from .core import DriftConfig, DriftDetector, DriftReport, FeatureRow, TimelinePoint


@dataclass(frozen=True)
class Override:
    """A flag that overrides one DriftConfig field."""

    flag: str
    kind: type
    field: str


OVERRIDES: tuple[Override, ...] = (
    Override("--window", int, "window"),
    Override("--baseline-n", int, "baseline_n"),
    Override("--min-baseline", int, "min_baseline"),
    Override("--watch", float, "watch"),
    Override("--warn", float, "warn"),
)
BAR_WIDTH = 30
BAR_FULL_SCALE = 3.0


class CliArgs(Frozen):
    """Parsed command line; None means "not given, keep the environment's value"."""

    viewer: str
    window: int | None = None
    baseline_n: int | None = None
    min_baseline: int | None = None
    watch: float | None = None
    warn: float | None = None
    data: Path | None = None

    def config(self, base: DriftConfig) -> DriftConfig:
        """`base` with every given flag applied. Raises ValueError if the result is invalid."""
        given = {o.field: getattr(self, o.field) for o in OVERRIDES
                 if getattr(self, o.field) is not None}
        return DriftConfig.model_validate(base.model_dump() | given)


def parse_args(argv: Sequence[str]) -> CliArgs:
    """Raises SystemExit (argparse's usage error) on unknown or malformed flags."""
    parser = argparse.ArgumentParser(prog="python -m scrollsense.drift", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("viewer", help="viewer pseudonym, e.g. patient-01")
    for o in OVERRIDES:
        parser.add_argument(o.flag, type=o.kind, dest=o.field, help=f"override {o.field}")
    parser.add_argument("--data", type=Path, help="data folder (default SCROLLSENSE_DATA or data/)")
    return CliArgs.model_validate(vars(parser.parse_args(list(argv))))


def clock(moment: float | None) -> str:
    return datetime.fromtimestamp(moment).strftime("%m-%d %H:%M") if moment is not None else "-"


def feature_line(row: FeatureRow) -> str:
    return (f"  {row.label:<16} {row.weight:>4.1f} {'+' if row.direction > 0 else '-':>3} "
            f"{row.baseline_mean:>8.2f} {row.baseline_sd:>6.2f} {row.recent_mean:>7.2f} "
            f"{row.effect:>7.2f} {row.risk_effect:>6.2f}")


def timeline_line(point: TimelinePoint) -> str:
    filled = round(min(point.score, BAR_FULL_SCALE) / BAR_FULL_SCALE * BAR_WIDTH)
    return f"  {clock(point.seen_at)}  {point.score:5.2f} {'#' * filled:<{BAR_WIDTH}} {point.level}"


def render(report: DriftReport) -> str:
    """The report as plain text: verdict, reasons, feature table, evidence, safety, timeline."""
    c, b, r = report.config, report.baseline, report.recent
    score = f"{report.score:.2f}" if report.score is not None else "-"
    head = [f"{report.viewer}: {report.level.upper()}  score {score}  (watch >= {c.watch}, "
            f"warn >= {c.warn}; window {c.window}, baseline {c.baseline_n}, min {c.min_baseline})",
            f"{report.note}. Not a diagnosis.",
            f"baseline: {b.source}, {b.n}/{b.target} Shorts, {clock(b.first_seen_at)} to "
            f"{clock(b.last_seen_at)}; recent: {r.n} Shorts since {clock(r.first_seen_at)}; "
            f"pending analysis: {report.pending}"]
    table = ["features:", "  feature          wt  dir baseline     sd  recent  effect   risk",
             *map(feature_line, report.features)]
    return "\n".join([*head, *__listing("reasons", report.reasons), *table,
                      *__listing("evidence", [f"{e.video_id} risk {e.risk:.2f}: {e.title}"
                                              for e in report.evidence]),
                      *__listing("SAFETY (A9)", [f"{s.video_id} A9={s.a9}: {s.title}"
                                                 for s in report.safety]),
                      f"timeline (score of the last {c.window} Shorts at each Short after the "
                      "baseline):", *map(timeline_line, report.timeline)])


def __listing(title: str, lines: Sequence[str]) -> list[str]:
    return [f"{title}:", *(f"  - {line}" for line in lines)] if lines else []


def main(argv: Sequence[str]) -> None:
    """Load the viewer's log and analyses from disk and print their report."""
    args = parse_args(argv)
    settings = Settings.from_env(ROOT)
    dirs = DataDirs.under(args.data, settings.mock) if args.data else DataDirs(
        clips=settings.data_dir, views=settings.views_dir)
    viewer = ViewerId(args.viewer)
    observer = FeedObserver(JsonlViewLog(dirs.views), JsonFileStore(dirs.clips))
    detector = DriftDetector(args.config(settings.drift))
    mark = JsonBaselineStore(dirs.views).mark_of(viewer)
    print(render(detector.report(viewer.value, observer.observed(viewer), mark)))
