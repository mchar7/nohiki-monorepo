"""Management script for messaging service operations."""

import sys
from pathlib import Path

from nohiki_observability import get_logger

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))


logger = get_logger(__name__)


def main() -> None:
    """Run management commands."""
    min_args = 2
    if len(sys.argv) < min_args:
        logger.info("Usage: python manage.py <command>")
        logger.info("Available commands:")
        sys.exit(1)

    command = sys.argv[1]
    logger.error("Unknown command", command=command)
    sys.exit(1)


if __name__ == "__main__":
    main()
