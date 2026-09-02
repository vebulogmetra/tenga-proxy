from __future__ import annotations

import fcntl
import hashlib
import logging
import os
import socket
import tempfile
from pathlib import Path

logger = logging.getLogger("tenga.sys.single_instance")

# Linux limits sockaddr_un.sun_path to 108 bytes including the trailing NUL.
_MAX_UNIX_SOCKET_PATH = 107


def _socket_path_for(lock_file: Path) -> Path:
    """Pick an activation socket path that fits into sun_path.

    The socket normally sits next to the lock file, but a long TENGA_CONFIG_DIR
    would overflow the AF_UNIX limit and bind() would fail with EINVAL, silently
    disabling single-instance activation. In that case fall back to the runtime
    directory with a name derived from the lock path.
    """
    candidate = lock_file.with_suffix(".sock")
    if len(str(candidate).encode()) <= _MAX_UNIX_SOCKET_PATH:
        return candidate

    runtime_dir = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
    digest = hashlib.sha1(str(lock_file).encode()).hexdigest()[:12]
    fallback = runtime_dir / f"tenga-proxy-{digest}.sock"
    logger.debug("Lock path too long for AF_UNIX, using socket at %s", fallback)
    return fallback


class SingleInstance:
    """Ensure only one instance of the application is running."""

    def __init__(self, lock_file: Path):
        """
        Initialize single instance lock.

        Args:
            lock_file: Path to lock file
        """
        self._lock_file = lock_file
        self._lock_fd: int | None = None
        self._acquired = False
        self._socket_file = _socket_path_for(lock_file)

    def is_running(self) -> bool:
        """
        Check if another instance is already running.

        Returns:
            True if another instance is running, False otherwise
        """
        if not self._lock_file.exists():
            return False

        try:
            pid_str = self._lock_file.read_text().strip()
            if not pid_str:
                return False

            pid = int(pid_str)
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                logger.warning("Stale lock file found (PID %s not running), removing", pid)
                try:
                    self._lock_file.unlink()
                    if self._socket_file.exists():
                        self._socket_file.unlink()
                except Exception:
                    pass
                return False

        except (ValueError, OSError) as e:
            logger.warning("Error reading lock file: %s", e)
            try:
                self._lock_file.unlink()
                if self._socket_file.exists():
                    self._socket_file.unlink()
            except Exception:
                pass
            return False

    def send_activation_signal(self) -> bool:
        """
        Send activation signal to the existing instance to bring window to foreground.

        Returns:
            True if signal was sent successfully, False otherwise
        """
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.connect(str(self._socket_file))
                sock.send(b'ACTIVATE')
                return True
            except socket.error as e:
                logger.warning("Could not connect to existing instance socket: %s", e)
                return False
            finally:
                sock.close()
        except Exception as e:
            logger.error("Error sending activation signal: %s", e)
            return False

    def setup_socket_server(self) -> bool:
        """
        Setup socket server for receiving activation signals.

        Returns:
            True if socket server was setup successfully, False otherwise
        """
        try:
            if self._socket_file.exists():
                self._socket_file.unlink()

            self._server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._server_socket.bind(str(self._socket_file))
            self._server_socket.listen(1)

            logger.info("Socket server setup at: %s", self._socket_file)
            return True
        except Exception as e:
            logger.error("Error setting up socket server: %s", e)
            return False

    def close_socket_server(self):
        """Close and cleanup socket server."""
        try:
            if hasattr(self, '_server_socket'):
                self._server_socket.close()
        except Exception as e:
            logger.error("Error closing socket server: %s", e)

        try:
            if self._socket_file.exists():
                self._socket_file.unlink()
        except Exception as e:
            logger.error("Error removing socket file: %s", e)

    def acquire(self) -> bool:
        """
        Acquire lock.

        Returns:
            True if lock was acquired, False if another instance is running
        """
        if self.is_running():
            return False

        try:
            self._lock_file.parent.mkdir(parents=True, exist_ok=True)
            self._lock_fd = os.open(str(self._lock_file), os.O_CREAT | os.O_WRONLY | os.O_TRUNC)

            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(self._lock_fd)
                self._lock_fd = None
                return False

            pid_str = str(os.getpid())
            os.write(self._lock_fd, pid_str.encode())
            os.fsync(self._lock_fd)

            self._acquired = True
            logger.info("Lock acquired, PID: %s", pid_str)
            self.setup_socket_server()

            return True

        except Exception as e:
            logger.error("Error acquiring lock: %s", e)
            if self._lock_fd is not None:
                try:
                    os.close(self._lock_fd)
                except Exception:
                    pass
                self._lock_fd = None
            return False

    def release(self) -> None:
        """Release lock."""
        if not self._acquired:
            return

        try:
            if self._lock_fd is not None:
                try:
                    fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                except Exception:
                    pass
                try:
                    os.close(self._lock_fd)
                except Exception:
                    pass
                self._lock_fd = None

            if self._lock_file.exists():
                try:
                    self._lock_file.unlink()
                except Exception:
                    pass
            self.close_socket_server()

            self._acquired = False
            logger.info("Lock released")

        except Exception as e:
            logger.error("Error releasing lock: %s", e)

    def __enter__(self):
        """Context manager entry."""
        if not self.acquire():
            raise RuntimeError("Another instance is already running")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.release()
