"""Bounded, sanitized diagnostics from logs, never from profiles/configuration."""

from __future__ import annotations

import os
from pathlib import Path

from src import __version__
from src.core.log_redaction import redact

_OPEN_FLAGS = (
    getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
)


def read_diagnostics(log_dir: Path, *, max_bytes: int = 256 * 1024) -> str:
    max_bytes = min(max(0, max_bytes), 1024 * 1024)
    blocks = [f"Veblock {__version__}\nЖурналы хранятся 3 дня. Секреты замаскированы.\n"]
    remaining = max_bytes
    for path in sorted(log_dir.glob("*.log*"), key=lambda p: p.name, reverse=True)[:12]:
        if remaining <= 0:
            break
        try:
            # Never follow a substituted symlink out of the log directory.
            # Windows has no O_NOFOLLOW/O_NONBLOCK, but needs O_BINARY.
            if path.is_symlink():
                continue
            fd = os.open(path, os.O_RDONLY | _OPEN_FLAGS)
            with os.fdopen(fd, "rb") as stream:
                import stat

                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    continue
                length = min(remaining, os.fstat(stream.fileno()).st_size)
                size = os.fstat(stream.fileno()).st_size
                start = size - length
                stream.seek(max(0, start - 1))
                previous = stream.read(1) if start else b"\n"
                raw = stream.read(length)
                remaining -= len(raw)
                if start and previous != b"\n":
                    # Do not expose the tail of a token whose scheme/key was
                    # cut off by the bounded read.
                    raw = raw.partition(b"\n")[2]
            blocks.append(
                f"\n--- {path.name} ---\n" + redact(raw.decode("utf-8", errors="replace"))
            )
        except OSError:
            continue
    return redact("\n".join(blocks))
