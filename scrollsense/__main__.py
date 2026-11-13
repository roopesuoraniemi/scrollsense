"""Batch-analyse videos from the command line.

Usage:  uv run python -m scrollsense <youtube-url> [<url> ...]
"""
import sys

from .composition import ROOT, Settings, wire
from .domain import AnalysisRequest, ClipAnalysis, Stage, VideoId


def main(urls: list[str]) -> None:
    """Analyse each URL in turn (cached ones are skipped) and print a one-line summary."""
    wiring = wire(Settings.from_env(ROOT))
    for url in urls:
        video = VideoId.parse(url)
        wiring.service.run(AnalysisRequest(video=video), lambda stage, v=video: __report(v, stage))
        analysis = wiring.store.load(video)
        print(__summary(analysis) if analysis else f"{video}: not stored")


def __report(video: VideoId, stage: Stage) -> None:
    print(f"{video}: {stage.value}")


def __summary(analysis: ClipAnalysis) -> str:
    s = analysis.scores
    return (f"  -> {analysis.package.title} | valence {s.valence} arousal {s.arousal} "
            f"| theme load {s.theme_load}/27 | {s.stance}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
