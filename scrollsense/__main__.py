"""Batch-analyse videos from the command line.

Usage:  uv run python -m scrollsense [--force] <youtube-url> [<url> ...]

--force re-analyses videos that are already stored.
"""
import sys

from .composition import ROOT, Settings, wire
from .domain import AnalysisRequest, ClipAnalysis, Stage, VideoId

__FORCE = "--force"


def main(urls: list[str], force: bool = False) -> None:
    """Analyse each URL in turn (stored ones are skipped unless `force`) and print a one-line summary."""
    wiring = wire(Settings.from_env(ROOT))
    for url in urls:
        video = VideoId.parse(url)
        wiring.service.run(AnalysisRequest(video=video, force=force),
                           lambda stage, v=video: __report(v, stage))
        analysis = wiring.store.load(video)
        print(__summary(analysis) if analysis else f"{video}: not stored")


def __report(video: VideoId, stage: Stage) -> None:
    print(f"{video}: {stage.value}")


def __summary(analysis: ClipAnalysis) -> str:
    s = analysis.scores
    return (f"  -> {analysis.package.title} | valence {s.valence} (neg {s.negative_affect} "
            f"pos {s.positive_affect}) arousal {s.arousal} "
            f"| theme load {s.theme_load}/27 A9 {s.a9_death_suicide} | {s.stance}")


if __name__ == "__main__":
    urls = [arg for arg in sys.argv[1:] if arg != __FORCE]
    if not urls:
        sys.exit(__doc__)
    main(urls, force=__FORCE in sys.argv[1:])
