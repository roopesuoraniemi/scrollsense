"""Loading the global affect norms shipped with the app (the drift detector's affect baseline)."""
from pathlib import Path

from .drift.affect import AffectNorm
from .schemas import Frozen

NORMS_PATH = Path(__file__).resolve().parent / "reference" / "affect_norms.json"


class NormStats(Frozen):
    """One dimension of a lexicon on its own scale, and its centre and SD mapped onto 1-5."""

    mean: float
    sd: float
    median: float
    mapped_centre: float
    mapped_sd: float


class NormSource(Frozen):
    """A published lexicon the norms were derived from, with its provenance and licence."""

    name: str
    citation: str
    doi: str
    download_url: str
    licence: str
    rating_scale: str
    mapping: str
    split_half_reliability: dict[str, float]
    n_words: int
    valence: NormStats
    arousal: NormStats


class CrossCheck(Frozen):
    """Pearson r between the two lexicons over the words they share."""

    n_shared_words: int
    r_valence: float
    r_arousal: float


class AffectNorms(Frozen):
    """The file as written by `scripts/build_affect_norms.py`: the baseline and its sources."""

    generated_by: str
    target_scale: str
    baseline: AffectNorm
    sources: tuple[NormSource, ...]
    cross_check: CrossCheck
    caveat: str


def load_affect_norms(path: Path = NORMS_PATH) -> AffectNorms:
    """The norms from `path`. Raises FileNotFoundError if it is missing (rebuild it with
    `scripts/build_affect_norms.py`), pydantic.ValidationError if it is malformed."""
    return AffectNorms.model_validate_json(path.read_text(encoding="utf-8"))
