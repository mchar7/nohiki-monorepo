"""Entry point for python -m qdrant_init."""

from qdrant_init.cli import app

if __name__ == "__main__":  # pragma: no cover: only reached via `python -m qdrant_init`
    app()
