"""Entry point: `uv run python -m scrollsense.drift <viewer> [flags]` (see `cli`)."""
import sys

from .cli import main

if __name__ == "__main__":
    main(sys.argv[1:])
