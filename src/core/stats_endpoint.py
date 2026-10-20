"""A private filesystem namespace for the core's per-run gRPC socket.

xray 26.9.9 supports Unix dokodemo-door listeners and statsquery unix:// targets.
Access is controlled by the owning directory, mode 0700; no TCP fallback.
"""

from __future__ import annotations

import tempfile
from pathlib import Path


class StatsEndpoint:
    def __init__(self):
        self._directory: tempfile.TemporaryDirectory | None = None

    @property
    def path(self) -> str:
        if self._directory is None:
            # Keep AF_UNIX paths below the Linux 108-byte limit regardless of
            # the user's potentially long XDG runtime/config directory.
            self._directory = tempfile.TemporaryDirectory(prefix="tenga-api-", dir="/tmp")
        return str(Path(self._directory.name) / "stats.sock")

    @property
    def address(self) -> str:
        return "unix://" + self.path

    def close(self):
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None
