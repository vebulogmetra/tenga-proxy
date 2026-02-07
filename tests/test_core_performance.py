import time
import logging
from src.core.performance import measure_time


def test_measure_time_decorator_logs_slow_operations(caplog):
    """Test that measure_time logs slow operations."""
    caplog.set_level(logging.WARNING)

    @measure_time("test operation")
    def slow_function():
        time.sleep(0.15)  # 150ms
        return "result"

    result = slow_function()

    assert result == "result"
    # Should log because > 100ms
    assert "test operation" in caplog.text
    assert "ms" in caplog.text


def test_measure_time_decorator_skips_fast_operations(caplog):
    """Test that measure_time doesn't log fast operations."""
    caplog.set_level(logging.WARNING)

    @measure_time("fast operation")
    def fast_function():
        time.sleep(0.05)  # 50ms
        return "result"

    result = fast_function()

    assert result == "result"
    # Should not log because < 100ms
    assert "fast operation" not in caplog.text
