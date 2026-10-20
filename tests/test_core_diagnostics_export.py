import logging

from src.core.diagnostics_export import read_diagnostics
from src.core.log_manager import LogManager


def test_old_log_tail_is_bounded_and_redacted(tmp_path):
    (tmp_path / "xray.log").write_text("old\n" * 5000 + "trojan://secret@host:443\n")
    result = read_diagnostics(tmp_path, max_bytes=200)
    assert "secret" not in result
    assert "скрыто" in result
    assert len(result) < 500


def test_clear_keeps_active_handler_writable(tmp_path):
    path = tmp_path / "active.log"
    handler = logging.FileHandler(path)
    logger = logging.Logger("isolated")
    logger.addHandler(handler)
    try:
        logger.warning("before")
        LogManager(tmp_path).clear_all_logs()
        logger.warning("after")
        handler.flush()
        assert path.read_text().strip() == "after"
    finally:
        handler.close()
