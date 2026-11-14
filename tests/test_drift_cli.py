from pathlib import Path

import pytest

from scrollsense.drift.cli import parse_args, render
from scrollsense.drift.core import DriftConfig, DriftDetector

from .test_drift import NEUTRAL, SAD, feed


def test_flags_override_the_environment_config() -> None:
    args = parse_args(["patient-01", "--window", "6", "--warn", "2.5", "--data", "/tmp/x"])
    assert (args.viewer, args.window, args.warn, args.data) == ("patient-01", 6, 2.5, Path("/tmp/x"))
    assert args.baseline_n is None and args.watch is None
    base = DriftConfig(baseline_n=30)
    assert args.config(base) == DriftConfig(baseline_n=30, window=6, warn=2.5)
    assert parse_args(["patient-01"]).config(base) == base


def test_bad_flags_exit_and_inconsistent_overrides_raise() -> None:
    with pytest.raises(SystemExit):
        parse_args(["patient-01", "--window", "many"])
    with pytest.raises(SystemExit):
        parse_args([])
    with pytest.raises(ValueError):
        parse_args(["patient-01", "--watch", "3"]).config(DriftConfig())


def test_render_prints_verdict_reasons_table_and_timeline() -> None:
    config = DriftConfig(baseline_n=8, min_baseline=8, window=4)
    report = DriftDetector(config).report("patient-01", feed([NEUTRAL] * 8 + [SAD] * 4), None)
    text = render(report)
    assert text.startswith("patient-01: WARNING  score 5.48")
    assert "Not a diagnosis." in text and "dwelling stance 6.7 SD above normal" in text
    assert "  valence" in text and text.count(" warning") == 3
