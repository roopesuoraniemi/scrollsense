"""Build web/demo-feed.json: a scripted Shorts feed for the web demo, from analysed clips.

The feed opens with upbeat Shorts, drifts into low-mood ones (so the warning and the check-in
card appear) and ends with upbeat ones again. Only Shorts YouTube allows to be embedded are
kept; Shorts about death or self-harm are left out of a demo shown to an audience.

Run:  PYTHONPATH=. uv run python scripts/build_demo_feed.py [--data data]
"""
import argparse
import json
import random
import urllib.error
import urllib.request
from pathlib import Path

from scrollsense.domain import ClipAnalysis
from scrollsense.store import JsonFileStore

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "demo-feed.json"
UPBEAT = {(4, 3), (4, 4), (5, 3), (5, 4)}
LOW = {(2, 1), (2, 2), (3, 1)}
AVOID = ("death", "die", "dying", "suicid", "kill", "hospital", "grief", "funeral", "self-harm")
PLAN = (("upbeat", 5), ("low", 9), ("upbeat", 5))


def mood_of(clip: ClipAnalysis) -> str | None:
    pair = (clip.scores.valence, clip.scores.arousal)
    return "upbeat" if pair in UPBEAT else "low" if pair in LOW else None


def suitable(clip: ClipAnalysis) -> bool:
    text = f"{clip.package.title} {clip.package.main_message}".lower()
    return not any(word in text for word in AVOID)


def embeddable(video_id: str) -> bool:
    url = f"https://www.youtube.com/oembed?format=json&url=https://www.youtube.com/shorts/{video_id}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


def pick(pool: list[ClipAnalysis], count: int) -> list[ClipAnalysis]:
    chosen: list[ClipAnalysis] = []
    while pool and len(chosen) < count:
        clip = pool.pop()
        if embeddable(clip.video_id):
            chosen.append(clip)
    return chosen


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--seed", type=int, default=7)
    return parser.parse_args()


def main() -> None:
    args = arguments()
    clips = [c for c in JsonFileStore(args.data / "clips").list_all() if suitable(c)]
    random.Random(args.seed).shuffle(clips)
    pools = {mood: [c for c in clips if mood_of(c) == mood] for mood in ("upbeat", "low")}
    feed = [{"id": c.video_id, "title": c.package.title, "mood": mood}
            for mood, count in PLAN for c in pick(pools[mood], count)]
    OUT.write_text(json.dumps(feed, indent=1) + "\n")
    print(f"{len(feed)} Shorts written to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
