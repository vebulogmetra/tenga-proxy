from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("tenga.core.log_manager")


class LogManager:
    """Manage log files: rotation, cleanup, and information."""

    def __init__(self, log_dir: Path):
        """Initialize log manager.

        Args:
            log_dir: Directory containing log files
        """
        self.log_dir = log_dir

    def get_logs_info(self) -> dict[str, Any]:
        """Get information about all log files.

        Returns:
            Dictionary with:
            - total_size: Total size in bytes
            - files: List of {name, size, modified} dicts
        """
        if not self.log_dir.exists():
            return {"total_size": 0, "files": []}

        log_files = []
        total_size = 0

        # Find all *.log* files
        for log_file in self.log_dir.glob("*.log*"):
            if log_file.is_file():
                size = log_file.stat().st_size
                modified = log_file.stat().st_mtime

                log_files.append({
                    "name": log_file.name,
                    "size": size,
                    "modified": modified,
                })
                total_size += size

        # Sort by name
        log_files.sort(key=lambda x: x["name"])

        return {
            "total_size": total_size,
            "files": log_files,
        }

    def cleanup_old_logs(self, days: int = 14) -> int:
        """Remove log files older than specified days.

        Args:
            days: Remove files older than this many days

        Returns:
            Number of files removed
        """
        if not self.log_dir.exists():
            return 0

        cutoff_time = time.time() - (days * 24 * 60 * 60)
        removed_count = 0

        for log_file in self.log_dir.glob("*.log*"):
            if not log_file.is_file():
                continue

            try:
                mtime = log_file.stat().st_mtime
                if mtime < cutoff_time:
                    log_file.unlink()
                    removed_count += 1
                    logger.info("Removed old log file: %s", log_file.name)
            except Exception as e:
                logger.warning("Failed to remove log file %s: %s", log_file.name, e)

        if removed_count > 0:
            logger.info("Cleanup complete: removed %d old log files", removed_count)

        return removed_count

    def clear_all_logs(self) -> tuple[int, int]:
        """Remove all log files.

        Returns:
            Tuple of (file_count, bytes_freed)
        """
        if not self.log_dir.exists():
            return 0, 0

        file_count = 0
        bytes_freed = 0

        for log_file in self.log_dir.glob("*.log*"):
            if not log_file.is_file():
                continue

            try:
                size = log_file.stat().st_size
                log_file.unlink()
                file_count += 1
                bytes_freed += size
                logger.info("Removed log file: %s (%d bytes)", log_file.name, size)
            except Exception as e:
                logger.warning("Failed to remove log file %s: %s", log_file.name, e)

        if file_count > 0:
            logger.info("Cleared all logs: %d files, %d bytes", file_count, bytes_freed)

        return file_count, bytes_freed
