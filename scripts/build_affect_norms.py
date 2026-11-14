"""Build scrollsense/reference/affect_norms.json: the global affect baseline of the drift detector.

The centre and spread of everyday English word affect, from two published lexicons, mapped
linearly onto the 1-5 valence and arousal scales the scoring model uses:

- Warriner, Kuperman & Brysbaert (2013), 1-9 Likert ratings: supplies the centre and SD
  (a Likert scale like ours), mapped with x' = 1 + (x - 1) / 2.
- Mohammad (2018) NRC VAD Lexicon v1, 0-1 best-worst scaling: the cross-check for the spread,
  mapped with x' = 1 + 4x. Its mean is 0.5 by construction (relative ranking), so it says
  nothing about the centre.

The raw lexicons are not shipped (NRC VAD is licensed for non-commercial research only);
download them into one folder and run:

    python -I scripts/build_affect_norms.py --lexicons DIR [--out PATH]

DIR must hold `Ratings_Warriner_et_al.csv` (columns Word, V.Mean.Sum, A.Mean.Sum) and
`nrc/NRC-VAD-Lexicon/NRC-VAD-Lexicon.txt` (tab-separated word, valence, arousal, dominance;
no header row). Standard library only, so it can run isolated (-I) next to untrusted files.
"""
import argparse
import csv
import json
import statistics
from dataclasses import dataclass
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "scrollsense" / "reference" / "affect_norms.json"
WARRINER_FILE = "Ratings_Warriner_et_al.csv"
NRC_FILE = Path("nrc") / "NRC-VAD-Lexicon" / "NRC-VAD-Lexicon.txt"
DECIMALS = 4

WARRINER = {
    "name": "Warriner, Kuperman & Brysbaert (2013)",
    "citation": "Warriner, A. B., Kuperman, V., & Brysbaert, M. (2013). Norms of valence, arousal, "
                "and dominance for 13,915 English lemmas. Behavior Research Methods, 45, 1191-1207.",
    "doi": "10.3758/s13428-012-0314-x",
    "download_url": "https://raw.githubusercontent.com/JULIELab/XANEW/master/Ratings_Warriner_et_al.csv",
    "licence": "Supplementary material of the article, mirrored by the JULIELab/XANEW repository; "
               "check the authors' terms before redistributing. Not redistributed here, only "
               "derived summary statistics.",
    "rating_scale": "1-9 Likert (valence: unhappy..happy; arousal: calm..excited)",
    "mapping": "x' = 1 + (x - 1) / 2",
    "split_half_reliability": {"valence": 0.914, "arousal": 0.689, "dominance": 0.770},
}
NRC = {
    "name": "Mohammad (2018), NRC VAD Lexicon v1",
    "citation": "Mohammad, S. M. (2018). Obtaining reliable human ratings of valence, arousal, and "
                "dominance for 20,000 English words. Proceedings of ACL 2018 (P18-1017), 174-184.",
    "doi": "10.18653/v1/P18-1017",
    "download_url": "https://www.saifmohammad.com/WebDocs/Lexicons/NRC-VAD-Lexicon.zip",
    "licence": "Free for non-commercial research and educational use only; commercial use needs "
               "a licence from the National Research Council Canada. The lexicon itself is not "
               "redistributed here, only derived summary statistics.",
    "rating_scale": "0-1 best-worst scaling (relative ranking: mean 0.5 by construction)",
    "mapping": "x' = 1 + 4x",
    "split_half_reliability": {"valence": 0.95, "arousal": 0.90, "dominance": 0.91},
}


@dataclass(frozen=True)
class Lexicon:
    """Valence and arousal per word, on the lexicon's own scale."""

    valence: dict[str, float]
    arousal: dict[str, float]


@dataclass(frozen=True)
class Linear:
    """x' = offset + scale * x, onto the model's 1-5 scales."""

    offset: float
    scale: float

    def describe(self, values: list[float]) -> dict[str, float]:
        mean, sd = statistics.fmean(values), statistics.pstdev(values)
        return {"mean": round(mean, DECIMALS), "sd": round(sd, DECIMALS),
                "median": round(statistics.median(values), DECIMALS),
                "mapped_centre": round(self.offset + self.scale * mean, 3),
                "mapped_sd": round(self.scale * sd, 3)}


def read_warriner(path: Path) -> Lexicon:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return Lexicon(valence={r["Word"]: float(r["V.Mean.Sum"]) for r in rows},
                   arousal={r["Word"]: float(r["A.Mean.Sum"]) for r in rows})


def read_nrc(path: Path) -> Lexicon:
    lines = [line.split("\t") for line in path.read_text(encoding="utf-8").splitlines() if line]
    return Lexicon(valence={w: float(v) for w, v, _a, _d in lines},
                   arousal={w: float(a) for w, _v, a, _d in lines})


def summary(meta: dict, lexicon: Lexicon, mapping: Linear) -> dict:
    return meta | {"n_words": len(lexicon.valence),
                   "valence": mapping.describe(list(lexicon.valence.values())),
                   "arousal": mapping.describe(list(lexicon.arousal.values()))}


def overlap(a: Lexicon, b: Lexicon) -> dict:
    shared = sorted(a.valence.keys() & b.valence.keys())
    r = {dim: statistics.correlation([getattr(a, dim)[w] for w in shared],
                                     [getattr(b, dim)[w] for w in shared])
         for dim in ("valence", "arousal")}
    return {"n_shared_words": len(shared), "r_valence": round(r["valence"], 3),
            "r_arousal": round(r["arousal"], 3)}


def build(directory: Path) -> dict:
    warriner, nrc = read_warriner(directory / WARRINER_FILE), read_nrc(directory / NRC_FILE)
    likert = summary(WARRINER, warriner, Linear(offset=0.5, scale=0.5))
    bws = summary(NRC, nrc, Linear(offset=1.0, scale=4.0))
    baseline = {"source": "Warriner, Kuperman & Brysbaert (2013), mapped 1-9 -> 1-5",
                "cite": "Warriner 2013",
                "centre": {d: likert[d]["mapped_centre"] for d in ("valence", "arousal")},
                "sd": {d: likert[d]["mapped_sd"] for d in ("valence", "arousal")}}
    return {"generated_by": "scripts/build_affect_norms.py",
            "target_scale": "the scoring model's 1-5 valence and arousal (see schemas.ClipScores)",
            "baseline": baseline, "sources": [likert, bws], "cross_check": overlap(warriner, nrc),
            "caveat": "Word norms describe single English words, not video content; the linear "
                      "mapping onto the model's scales is nominal, not calibrated."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lexicons", type=Path, required=True, help="folder with both lexicons")
    parser.add_argument("--out", type=Path, default=OUT, help=f"output (default {OUT})")
    args = parser.parse_args()
    norms = build(args.lexicons)
    args.out.write_text(json.dumps(norms, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(norms["baseline"]), json.dumps(norms["cross_check"]))


if __name__ == "__main__":
    main()
