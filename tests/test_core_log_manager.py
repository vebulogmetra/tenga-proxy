from pathlib import Path
import tempfile
import time
import pytest
from src.core.log_manager import LogManager


def test_log_manager_init():
    """Test LogManager initialization."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_dir = Path(tmpdir)
        manager = LogManager(log_dir)
        assert manager.log_dir == log_dir


def test_get_logs_info_empty(tmp_path):
    """Test get_logs_info with no log files."""
    manager = LogManager(tmp_path)
    info = manager.get_logs_info()

    assert info["total_size"] == 0
    assert info["files"] == []


def test_get_logs_info_with_files(tmp_path):
    """Test get_logs_info with log files."""
    # Create test log files
    log1 = tmp_path / "test1.log"
    log1.write_text("test data 1")

    log2 = tmp_path / "test2.log.1"
    log2.write_text("test data 2 longer")

    manager = LogManager(tmp_path)
    info = manager.get_logs_info()

    assert info["total_size"] == 11 + 18  # 29 bytes
    assert len(info["files"]) == 2
    assert info["files"][0]["name"] in ["test1.log", "test2.log.1"]
    assert info["files"][0]["size"] in [11, 18]


def test_cleanup_old_logs_removes_old_files(tmp_path):
    """Test cleanup removes files older than threshold."""
    import os

    manager = LogManager(tmp_path)

    # Create old log file
    old_log = tmp_path / "old.log"
    old_log.write_text("old data")

    # Set modification time to 20 days ago
    old_time = time.time() - (20 * 24 * 60 * 60)
    os.utime(old_log, (old_time, old_time))

    # Create recent log file
    recent_log = tmp_path / "recent.log"
    recent_log.write_text("recent data")

    # Cleanup files older than 14 days
    removed = manager.cleanup_old_logs(days=14)

    assert removed == 1
    assert not old_log.exists()
    assert recent_log.exists()


def test_cleanup_old_logs_keeps_recent_files(tmp_path):
    """Test cleanup keeps files newer than threshold."""
    manager = LogManager(tmp_path)

    recent_log = tmp_path / "recent.log"
    recent_log.write_text("recent data")

    removed = manager.cleanup_old_logs(days=14)

    assert removed == 0
    assert recent_log.exists()


def test_clear_all_logs(tmp_path):
    """Test clearing all log files."""
    manager = LogManager(tmp_path)

    # Create multiple log files
    log1 = tmp_path / "test1.log"
    log1.write_text("data1")

    log2 = tmp_path / "test2.log.1"
    log2.write_text("data2 longer")

    log3 = tmp_path / "test3.log.2"
    log3.write_text("data3")

    # Clear all logs
    file_count, bytes_freed = manager.clear_all_logs()

    assert file_count == 3
    assert bytes_freed == 5 + 12 + 5  # 22 bytes
    assert not log1.exists()
    assert not log2.exists()
    assert not log3.exists()


def test_clear_all_logs_empty_dir(tmp_path):
    """Test clearing when no log files exist."""
    manager = LogManager(tmp_path)

    file_count, bytes_freed = manager.clear_all_logs()

    assert file_count == 0
    assert bytes_freed == 0
