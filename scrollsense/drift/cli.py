"""Print one viewer's drift report in the terminal, for tuning thresholds without the UI.

Usage:  uv run python -m scrollsense.drift <viewer> [--window N] [--watch X] [--warn Y]
            [--data DIR]

Flags override the SCROLLSENSE_* environment values (and `.env`); `--data` replaces
SCROLLSENSE_DATA. Read-only: it never analyses anything.
"""
import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

from ..affect_norms import load_affect_norms
from ..composition import ROOT, DataDirs, Settings
from ..drift_api import FeedObserver
from ..schemas import Frozen
from ..store import JsonFileStore
from ..views import ViewerId
from ..viewlog import JsonlViewLog
from .affect import FeatureRow
from .clinical import ClinicalExposure, ClinicalItem
from .core import DriftConfig, DriftDetector, DriftReport, TimelinePoint


@dataclass(frozen=True)
class Override:
    """A flag that overrides one DriftConfig field."""

    flag: str
    kind: type
    field: str


OVERRIDES: tuple[Override, ...] = (
    Override("--window", int, "window"),
    Override("--watch", float, "watch"),
    Override("--warn", float, "warn"),
)
BAR_WIDTH = 30
BAR_FULL_SCALE = 3.0


class CliArgs(Frozen):
    """Parsed command line; None means "not given, keep the environment's value"."""

    viewer: str
    window: int | None = None
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
    return (f"  {row.name:<10} {'+' if row.direction > 0 else '-':>3} "
            f"{row.norm_mean:>6.2f} {row.norm_sd:>6.2f} {row.recent_mean:>7.2f} "
            f"{row.effect:>7.2f} {row.risk_effect:>6.2f}")


def item_line(item: ClinicalItem) -> str:
    return (f"  {item.code} {item.label:<24} {item.present:>3} {item.share:>6.2f} "
            f"{item.score:>3}  {item.frequency_label}")


def timeline_line(point: TimelinePoint) -> str:
    filled = round(min(point.score, BAR_FULL_SCALE) / BAR_FULL_SCALE * BAR_WIDTH)
    return (f"  {clock(point.seen_at)}  {point.score:5.2f} {'#' * filled:<{BAR_WIDTH}} "
            f"PHQ {point.exposure:>2}  {point.level}")


def clinical_lines(clinical: ClinicalExposure | None) -> list[str]:
    if clinical is None:
        return ["clinical: no analysed Shorts yet"]
    return [f"clinical (content exposure, PHQ-9 style, over {clinical.window_n} Shorts): "
            f"{clinical.total}/27 {clinical.band}, pattern {clinical.pattern}",
            "  item                         n  share score frequency",
            *map(item_line, clinical.items), f"  {clinical.reference}"]


def render(report: DriftReport) -> str:
    """The report as plain text: verdict, reasons, affect table, clinical items, evidence,
    timeline."""
    c, n, r = report.config, report.affect_baseline, report.recent
    score = f"{report.score:.2f}" if report.score is not None else "-"
    head = [f"{report.viewer}: {report.level.upper()}  affect {report.affect_level} "
            f"(score {score} SD into the bottom left; watch > {c.watch}, warn > {c.warn})  clinical "
            f"{report.clinical_level}  (window {c.window})",
            f"{report.note}. Describes the content shown; not a diagnosis.",
            f"recent: {r.n} Shorts since {clock(r.first_seen_at)}; pending analysis: "
            f"{report.pending}; affect norm: {n.source}"]
    table = ["affect vs norm:", "  feature     dir   norm     sd  recent  effect   risk",
             *map(feature_line, report.features)]
    return "\n".join([*head, *__listing("reasons", report.reasons), *table,
                      *clinical_lines(report.clinical),
                      *__listing("evidence", [f"{e.video_id} {'/'.join(e.central) or '-'} "
                                              f"risk {e.risk:.2f}: {e.title}"
                                              for e in report.evidence]),
                      f"timeline (affect score and PHQ-9-style exposure of the last {c.window} "
                      "Shorts at each Short):", *map(timeline_line, report.timeline)])


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
    detector = DriftDetector(args.config(settings.drift), load_affect_norms().baseline)
    print(render(detector.report(viewer.value, observer.observed(viewer))))
