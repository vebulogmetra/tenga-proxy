from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from src.core.config import LOG_DIR
from src.core.log_manager import LogManager

# Логи хранятся за три дня: сегодняшний файл и два суточных архива.
LOG_RETENTION_DAYS = 3


def daily_file_handler(log_file: Path) -> TimedRotatingFileHandler:
    """File handler that archives the log at midnight.

    Архив получает дату в имени (`xray.log.2026-10-08`), лишние архивы
    обработчик удаляет сам при очередной ротации. Файл открывается при первой
    записи: процесс, который ничего не пишет, не плодит пустых логов.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)
    return TimedRotatingFileHandler(
        log_file,
        when="midnight",
        backupCount=LOG_RETENTION_DAYS - 1,
        encoding="utf-8",
        delay=True,
    )


def setup_logging(log_file: Path, level: int = logging.INFO) -> None:
    """
    Basic logging setup for the application.

    All loggers will write to the specified file and to stdout.
    The file is rotated daily; logs older than LOG_RETENTION_DAYS are removed.

    This function works even if basicConfig was already called earlier.
    It will add handlers to the root logger without replacing existing ones.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # Архивы чужих процессов (CLI, ядро) и файлы, в которые давно никто не
    # пишет, обработчик не тронет — их подчищаем при запуске.
    LogManager(log_file.parent).cleanup_old_logs(days=LOG_RETENTION_DAYS)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    file_handler = daily_file_handler(log_file)
    console_handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    console_handler.setLevel(level)

    log_file_resolved = str(log_file.resolve())
    has_file_handler = any(
        isinstance(h, logging.FileHandler)
        and hasattr(h, "baseFilename")
        and str(Path(h.baseFilename).resolve()) == log_file_resolved
        for h in root_logger.handlers
    )
    has_console_handler = any(
        isinstance(h, logging.StreamHandler) and hasattr(h, "stream") and h.stream == sys.stdout
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
