from __future__ import annotations

import logging
import sys
from pathlib import Path

from src.core.config import LOG_DIR


def setup_logging(log_file: Path, level: int = logging.INFO) -> None:
    """
    Basic logging setup for the application.

    All loggers will write to the specified file and to stdout.
    
    This function works even if basicConfig was already called earlier.
    It will add handlers to the root logger without replacing existing ones.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    console_handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    console_handler.setLevel(level)

    log_file_resolved = str(log_file.resolve())
    has_file_handler = any(
        isinstance(h, logging.FileHandler) and 
        hasattr(h, 'baseFilename') and 
        str(Path(h.baseFilename).resolve()) == log_file_resolved
        for h in root_logger.handlers
    )
    has_console_handler = any(
        isinstance(h, logging.StreamHandler) and 
        hasattr(h, 'stream') and 
        h.stream == sys.stdout
        for h in root_logger.handlers
    )
    
    if not has_file_handler:
        root_logger.addHandler(file_handler)
    if not has_console_handler:
        root_logger.addHandler(console_handler)

    for logger_name in logging.Logger.manager.loggerDict:
        logger_obj = logging.getLogger(logger_name)
        if logger_obj is not root_logger:
            logger_obj.propagate = True
            if logger_obj.level == logging.NOTSET or logger_obj.level > level:
                logger_obj.setLevel(logging.NOTSET)
