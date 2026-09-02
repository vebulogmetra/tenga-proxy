import os
from pathlib import Path

import pytest

from src.sys.single_instance import SingleInstance


def test_is_running_false_when_no_file(tmp_path):
    lock = tmp_path / "lock"
    inst = SingleInstance(lock)
    assert inst.is_running() is False


def test_is_running_true_when_pid_alive(monkeypatch, tmp_path):
    lock = tmp_path / "lock"
    pid = 12345
    lock.write_text(str(pid))

    called = {"pid": None}

    def fake_kill(p: int, sig: int) -> None:
        called["pid"] = p

    monkeypatch.setattr(os, "kill", fake_kill)

    inst = SingleInstance(lock)
    assert inst.is_running() is True
    assert called["pid"] == pid


def test_is_running_removes_stale_lock(monkeypatch, tmp_path):
    lock = tmp_path / "lock"
    lock.write_text("99999")

    def fake_kill(p: int, sig: int) -> None:
        raise OSError("no such process")

    monkeypatch.setattr(os, "kill", fake_kill)

    inst = SingleInstance(lock)
    assert inst.is_running() is False
    assert not lock.exists()


def test_acquire_and_release_creates_and_removes_lock(tmp_path):
    lock = tmp_path / "lock"
    inst = SingleInstance(lock)

    acquired = inst.acquire()
    assert acquired is True
    assert lock.exists()
    assert lock.read_text().strip() == str(os.getpid())

    inst.release()
    assert not lock.exists()


def test_context_manager_ensures_single_instance(tmp_path):
    lock = tmp_path / "lock"

    with SingleInstance(lock) as inst:
        assert inst.is_running() is True
        assert lock.exists()

    assert not lock.exists()


def test_context_manager_raises_if_other_instance(monkeypatch, tmp_path):
    lock = tmp_path / "lock"
    lock.write_text("123")

    def fake_kill(p: int, sig: int) -> None:
        return None

    monkeypatch.setattr(os, "kill", fake_kill)

    inst = SingleInstance(lock)
    with pytest.raises(RuntimeError), inst:
        pass


def test_is_running_empty_pid(tmp_path):
    lock = tmp_path / "lock"
    lock.write_text("")
    inst = SingleInstance(lock)
    assert inst.is_running() is False


def test_is_running_invalid_pid(tmp_path):
    lock = tmp_path / "lock"
    lock.write_text("not_a_number")
    inst = SingleInstance(lock)
    assert inst.is_running() is False
    assert not lock.exists()


def test_is_running_read_error(monkeypatch, tmp_path):
    lock = tmp_path / "lock"
    lock.write_text("123")

    def fake_read_text(path):
        raise OSError("read error")

    monkeypatch.setattr("src.sys.single_instance.Path.read_text", lambda self: fake_read_text(self))

    inst = SingleInstance(lock)
    assert inst.is_running() is False


def test_acquire_blocking_io_error(monkeypatch, tmp_path):
    import fcntl

    lock = tmp_path / "lock"
    inst = SingleInstance(lock)

    def fake_flock(fd, op):
        raise BlockingIOError("locked")

    monkeypatch.setattr(fcntl, "flock", fake_flock)

    acquired = inst.acquire()
    assert acquired is False
    assert inst._lock_fd is None


def test_acquire_exception(monkeypatch, tmp_path):
    lock = tmp_path / "lock"
    inst = SingleInstance(lock)

    def fake_open(*args, **kwargs):
        raise OSError("open failed")

    monkeypatch.setattr(os, "open", fake_open)

    acquired = inst.acquire()
    assert acquired is False


def test_release_not_acquired(tmp_path):
    lock = tmp_path / "lock"
    inst = SingleInstance(lock)
    inst.release()
    assert not inst._acquired


def test_release_with_exceptions(monkeypatch, tmp_path):
    import fcntl

    lock = tmp_path / "lock"
    inst = SingleInstance(lock)
    inst.acquire()
    inst._acquired = True
    inst._lock_fd = 999

    def fake_flock(fd, op):
        raise OSError("flock error")

    def fake_close(fd):
        raise OSError("close error")

    monkeypatch.setattr(fcntl, "flock", fake_flock)
    monkeypatch.setattr(os, "close", fake_close)

    inst.release()
    assert not inst._acquired


def test_release_unlink_error(monkeypatch, tmp_path):
    lock = tmp_path / "lock"
    inst = SingleInstance(lock)
    inst.acquire()
    inst._acquired = True

    def fake_unlink(path):
        raise OSError("unlink error")

    monkeypatch.setattr("src.sys.single_instance.Path.unlink", lambda self: fake_unlink(self))

    inst.release()
    assert not inst._acquired


def test_socket_path_falls_back_to_runtime_dir_when_too_long(tmp_path, monkeypatch):
    runtime = tmp_path / "run"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    long_dir = tmp_path / ("x" * 120)
    long_dir.mkdir()

    instance = SingleInstance(long_dir / "tenga.lock")

    assert instance._socket_file.parent == runtime
    # sun_path ограничен в БАЙТАХ, не в символах
    assert len(str(instance._socket_file).encode()) <= 107


def test_socket_path_stays_next_to_lock_when_short(tmp_path):
    instance = SingleInstance(tmp_path / "tenga.lock")

    assert instance._socket_file == tmp_path / "tenga.sock"


def test_socket_path_uses_bytes_not_characters_for_the_limit(tmp_path, monkeypatch):
    """Кириллица: путь короче 108 символов, но длиннее 107 байт — лимит считается в байтах."""
    from src.sys.single_instance import _socket_path_for

    runtime = tmp_path / "run"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))

    lock = Path("/tmp") / ("ы" * 50) / "tenga.lock"
    assert len(str(lock)) < 108, "в символах помещается"
    assert len(str(lock).encode()) > 107, "в байтах не помещается"

    socket_file = _socket_path_for(lock)

    assert socket_file.parent == runtime, "путь должен считаться в байтах, а не символах"
    assert len(str(socket_file).encode()) <= 107


def test_socket_in_runtime_dir_actually_binds(tmp_path, monkeypatch):
    """Запасной путь должен реально проходить bind(), иначе смысл фикса теряется."""
    import socket as socket_module

    runtime = tmp_path / "run"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    long_dir = tmp_path / ("x" * 120)
    long_dir.mkdir()

    instance = SingleInstance(long_dir / "tenga.lock")
    sock = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    try:
        sock.bind(str(instance._socket_file))
    finally:
        sock.close()


def test_socket_path_skips_runtime_dir_that_is_itself_too_long(tmp_path, monkeypatch):
    """Если XDG_RUNTIME_DIR сам не помещается в sun_path, берётся временный каталог."""
    from src.sys.single_instance import _socket_path_for

    monkeypatch.setenv("XDG_RUNTIME_DIR", "/tmp/" + "r" * 100)
    long_dir = tmp_path / ("x" * 120)
    long_dir.mkdir()

    socket_file = _socket_path_for(long_dir / "tenga.lock")

    assert len(str(socket_file).encode()) <= 107
    assert not str(socket_file).startswith("/tmp/rrrr")
