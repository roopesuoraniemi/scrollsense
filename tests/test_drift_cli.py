from pathlib import Path

import pytest

from scrollsense.drift.cli import parse_args, render
from scrollsense.drift.core import DriftConfig

from .test_drift import NEUTRAL, SAD, judge


def test_flags_override_the_environment_config() -> None:
    args = parse_args(["patient-01", "--window", "6", "--warn", "2.5", "--data", "/tmp/x"])
    assert (args.viewer, args.window, args.warn, args.data) == ("patient-01", 6, 2.5, Path("/tmp/x"))
    assert args.watch is None
    base = DriftConfig(window=20)
    assert args.config(base) == DriftConfig(window=6, warn=2.5)
    assert parse_args(["patient-01"]).config(base) == base


def test_bad_flags_exit_and_inconsistent_overrides_raise() -> None:
    with pytest.raises(SystemExit):
        parse_args(["patient-01", "--window", "many"])
    with pytest.raises(SystemExit):
        parse_args(["patient-01", "--baseline-n", "8"])
    with pytest.raises(ValueError):
        parse_args(["patient-01", "--watch", "3"]).config(DriftConfig())


def test_render_prints_both_yardsticks_items_and_timeline() -> None:
    text = render(judge([NEUTRAL] * 4 + [SAD] * 4))
    assert text.startswith("patient-01: WARNING  affect warning (score 4.80 SD")
    assert "clinical watch  (window 4)" in text.splitlines()[0]
    assert "not a diagnosis." in text and "4.8 SD from the norm towards the bottom left" in text
    assert "6/27 mild, pattern other" in text and "  A1 Depressed mood" in text
    assert "nearly every day" in text and "Warriner, Kuperman & Brysbaert (2013)" in text
    assert text.count(" warning") == 4 and "PHQ  6  warning" in text
