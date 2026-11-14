"""Build the fixed content-similarity axes from the labelled test Shorts.

x: from the light centroid (0) to the heavy centroid (1) of the unit-normalised text-package
   embeddings; y: the main remaining topic direction, orthogonal to x, in SD units.
Labels come from the search query that found each Short (scripts/test_shorts.json), not from a
clinician; the axes describe "similar to depression-themed Shorts", not a person.

Setup:  analyse the test set into data/sim (see scripts/tune_drift.py)
Run:    uv run python scripts/build_content_axis.py
Writes: scrollsense/reference/content_axis.json
"""
import json
import pathlib

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scrollsense" / "reference" / "content_axis.json"


def labelled() -> tuple[np.ndarray, np.ndarray, str]:
    sets = json.loads((ROOT / "scripts" / "test_shorts.json").read_text())
    label = {x["id"]: 1 for x in sets["heavy"]} | {x["id"]: 0 for x in sets["light"]}
    rows, labels, models = [], [], set()
    for path in sorted((ROOT / "data" / "sim" / "clips").glob("*.json")):
        analysis = json.loads(path.read_text())
        vector = analysis["embedding"]["vector"]
        if vector and path.stem in label:
            rows.append(np.asarray(vector) / np.linalg.norm(vector))
            labels.append(label[path.stem])
            models.add(analysis["analyser"]["embed_name"])
    if len(models) != 1:
        raise SystemExit(f"expected one embedding model, found {models}")
    return np.array(rows), np.array(labels), models.pop()


def axes(x: np.ndarray, y: np.ndarray) -> dict:
    heavy, light = x[y == 1].mean(0), x[y == 0].mean(0)
    along = (heavy - light) / np.linalg.norm(heavy - light)
    residual = (x - x.mean(0)) - np.outer((x - x.mean(0)) @ along, along)
    topic = np.linalg.svd(residual, full_matrices=False)[2][0]
    topic_scores = x @ topic
    return {"x": along, "x_light": float(light @ along), "x_heavy": float(heavy @ along),
            "y": topic, "y_mean": float(topic_scores.mean()), "y_sd": float(topic_scores.std())}


def main() -> None:
    x, y, model = labelled()
    built = axes(x, y)
    projected = (x @ built["x"] - built["x_light"]) / (built["x_heavy"] - built["x_light"])
    accuracy = float(((projected > 0.5) == (y == 1)).mean())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "embed_model": model, "trained_on": int(len(y)), "train_accuracy": round(accuracy, 3),
        "x": [round(float(v), 7) for v in built["x"]], "x_light": built["x_light"], "x_heavy": built["x_heavy"],
        "y": [round(float(v), 7) for v in built["y"]], "y_mean": built["y_mean"], "y_sd": built["y_sd"],
    }))
    print(f"{OUT.relative_to(ROOT)}: {len(y)} Shorts, model {model}, threshold-0.5 accuracy {accuracy:.2f}")


if __name__ == "__main__":
    main()
