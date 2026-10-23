"""Where the core exposes its Stats API for one run.

Linux: a Unix dokodemo-door listener in a private directory, mode 0700; no
TCP. xray 26.9.9 supports Unix listeners and statsquery unix:// targets.

Windows: the same Unix listener accepts the connection and then panics in
dokodemo (checked on windows-latest), so the API listens on loopback TCP on a
free port chosen per run. Only StatsService is exposed: traffic counters.
"""

from __future__ import annotations

import socket
import tempfile
from pathlib import Path

from src.core import platform_info

LOOPBACK = "127.0.0.1"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((LOOPBACK, 0))
        return probe.getsockname()[1]


class StatsEndpoint:
    def __init__(self):
        self._directory: tempfile.TemporaryDirectory | None = None
        self._port: int | None = None

    @property
    def path(self) -> str:
        if self._directory is None:
            # Keep AF_UNIX paths below the Linux 108-byte limit regardless of
            # the user's potentially long XDG runtime/config directory.
            self._directory = tempfile.TemporaryDirectory(prefix="tenga-api-", dir="/tmp")
        return str(Path(self._directory.name) / "stats.sock")

    @property
    def port(self) -> int:
        if self._port is None:
            self._port = _free_port()
        return self._port

    def listen_settings(self) -> dict:
        """`listen` (and `port`) of the api inbound."""
        if platform_info.IS_WINDOWS:
            return {"listen": LOOPBACK, "port": self.port}
        return {"listen": self.path}

    @property
    def address(self) -> str:
        if platform_info.IS_WINDOWS:
            return f"{LOOPBACK}:{self.port}"
        return "unix://" + self.path

    def close(self):
        self._port = None
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None
