from __future__ import annotations

import logging
import time
from functools import wraps
from typing import Any, Callable, TypeVar

logger = logging.getLogger("tenga.core.performance")

F = TypeVar("F", bound=Callable[..., Any])


def measure_time(operation_name: str, threshold_ms: int = 100) -> Callable[[F], F]:
    """Decorator to measure and log execution time of operations.

    Logs a warning if operation takes longer than threshold_ms.

    Args:
        operation_name: Name of the operation for logging
        threshold_ms: Threshold in milliseconds (default: 100)

    Returns:
        Decorated function

    Example:
        @measure_time("database query")
        def query_db():
            # ...
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.time()
            result = func(*args, **kwargs)
            elapsed_ms = (time.time() - start) * 1000

            if elapsed_ms > threshold_ms:
                logger.warning("%s took %.0fms", operation_name, elapsed_ms)

            return result
        return wrapper  # type: ignore
    return decorator
