from __future__ import annotations

import logging
import sys
from pathlib import Path

from src.core.config import LOG_DIR


def setup_logging(log_file: Path, level: int = logging.INFO) -> None:
    """
    Basic logging setup for the application.

    All loggers will write to the specified file and to stdout.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    handlers = [
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


