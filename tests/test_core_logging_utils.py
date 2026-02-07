import logging
from logging.handlers import RotatingFileHandler

from src.core.logging_utils import setup_logging


def test_setup_logging_creates_log_file(tmp_path):
    log_file = tmp_path / "app.log"

    setup_logging(log_file, level=logging.DEBUG)

    assert log_file.exists()


def test_setup_logging_uses_rotating_handler(tmp_path):
    """Test that setup_logging uses RotatingFileHandler."""
    log_file = tmp_path / "test_rotating.log"

    # Need to patch LOG_DIR for this test
    from src.core import logging_utils
    original_log_dir = logging_utils.LOG_DIR
    logging_utils.LOG_DIR = tmp_path

    try:
        logging_utils.setup_logging(log_file)

        # Check that a RotatingFileHandler was added
        root_logger = logging.getLogger()
        rotating_handlers = [
            h for h in root_logger.handlers
            if isinstance(h, RotatingFileHandler)
        ]

        assert len(rotating_handlers) > 0
        handler = rotating_handlers[0]
        assert handler.maxBytes == 10 * 1024 * 1024  # 10 MB
        assert handler.backupCount == 5
    finally:
        logging_utils.LOG_DIR = original_log_dir
