"""Mutex единственного экземпляра: логика без настоящего kernel32."""

from __future__ import annotations

from pathlib import Path

from src.sys.windows.single_instance import SingleInstance, mutex_name


class FakeKernel:
    def __init__(self, existing: set[str] | None = None):
        self.existing = existing or set()
        self.closed: list[int] = []

    def create_mutex(self, name: str) -> tuple[int, bool]:
        already = name in self.existing
        self.existing.add(name)
        return 7, already

    def close(self, handle: int) -> None:
        self.closed.append(handle)


def test_name_depends_on_config_dir():
    first = mutex_name(Path("C:/a/tenga-proxy.lock"))
    second = mutex_name(Path("C:/b/tenga-proxy.lock"))

    assert first.startswith("Local\\ru.tenga.Proxy-")
    assert first != second


def test_name_ignores_case():
    assert mutex_name(Path("C:/A/x.lock")) == mutex_name(Path("c:/a/X.lock"))


def test_first_instance_acquires():
    kernel = FakeKernel()
    instance = SingleInstance(Path("C:/a/x.lock"), kernel=kernel)

    assert instance.acquire() is True


def test_second_instance_is_refused_and_closes_handle():
    lock = Path("C:/a/x.lock")
    kernel = FakeKernel(existing={mutex_name(lock)})
    instance = SingleInstance(lock, kernel=kernel)

    assert instance.acquire() is False
    assert kernel.closed == [7]


def test_release_closes_handle_once():
    kernel = FakeKernel()
    instance = SingleInstance(Path("C:/a/x.lock"), kernel=kernel)
    instance.acquire()

    instance.release()
    instance.release()

    assert kernel.closed == [7]
