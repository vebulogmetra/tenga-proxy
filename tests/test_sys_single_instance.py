import os
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
    with pytest.raises(RuntimeError):
        with inst:
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
