"""Loading the fixed content-similarity axes shipped with the app."""
from pathlib import Path

from .domain import ContentAxis

AXIS_PATH = Path(__file__).resolve().parent / "reference" / "content_axis.json"


def load_content_axis(path: Path = AXIS_PATH) -> ContentAxis | None:
    """The axes from `path`, or None if the file is missing (rebuild it with
    `scripts/build_content_axis.py`). Raises pydantic.ValidationError on a malformed file."""
    return ContentAxis.model_validate_json(path.read_text()) if path.exists() else None
