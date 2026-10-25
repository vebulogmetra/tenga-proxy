"""Чего не хватает для режима TUN: проверка без изменения системы."""

from __future__ import annotations

import errno
import struct

import pytest

from src.sys.linux import tun_access as linux
from src.sys.windows import tun_access as windows

XRAY = "/home/user/.local/share/tenga-proxy/xray"
CAP_NET_ADMIN = 1 << 12


def caps(permitted: int, *, effective: bool = True) -> bytes:
    magic = 0x02000000 | (1 if effective else 0)
    return struct.pack("<IIIII", magic, permitted, 0, 0, 0)


def no_xattr(_path, _name):
    raise OSError(errno.ENODATA, "No data available")


def sudo(allowed: set[str]):
    """`sudo -n -l <команда>`: успех только для разрешённых без пароля."""

    def run(cmd):
        assert cmd[:3] == ["sudo", "-n", "-l"]
        return cmd[3] in allowed

    return run


def check(*, euid=1000, xattr=no_xattr, allowed=(), helper=True, xray=XRAY):
    return linux.tun_problems(
        xray,
        geteuid=lambda: euid,
        getxattr=xattr,
        sudo_allows=sudo(set(allowed)),
        exists=lambda path: helper and path == linux.HELPER_PATH,
        which=lambda name: f"/usr/sbin/{name}" if name in ("sudo", "ip") else None,
    )


def test_root_needs_nothing():
    assert check(euid=0) == []


def test_ready_system_has_no_problems():
    problems = check(xattr=lambda *_: caps(CAP_NET_ADMIN), allowed={linux.HELPER_PATH})

    assert problems == []


def test_xray_without_capability_is_reported_with_the_fix():
    (problem,) = check(allowed={linux.HELPER_PATH})

    assert "cap_net_admin" in problem
    assert f"sudo setcap cap_net_admin,cap_net_raw+ep {XRAY}" in problem


def test_capability_without_effective_flag_does_not_count():
    problems = check(
        xattr=lambda *_: caps(CAP_NET_ADMIN, effective=False), allowed={linux.HELPER_PATH}
    )

    assert len(problems) == 1


def test_other_capabilities_do_not_count():
    problems = check(xattr=lambda *_: caps(1 << 13), allowed={linux.HELPER_PATH})

    assert len(problems) == 1


def test_routes_through_passwordless_ip_are_enough():
    problems = check(xattr=lambda *_: caps(CAP_NET_ADMIN), allowed={"/usr/sbin/ip"}, helper=False)

    assert problems == []


def test_routes_without_passwordless_sudo_are_reported():
    (problem,) = check(xattr=lambda *_: caps(CAP_NET_ADMIN))

    assert "маршрут" in problem.lower()
    assert "python cli.py install" in problem


def test_missing_xray_is_not_a_tun_problem():
    # Без ядра не работает ни один режим, об этом говорит само подключение.
    assert check(xray=None, allowed={linux.HELPER_PATH}) == []


def test_unreadable_capabilities_count_as_missing():
    def denied(_path, _name):
        raise PermissionError(errno.EACCES, "denied")

    assert len(check(xattr=denied, allowed={linux.HELPER_PATH})) == 1


@pytest.mark.parametrize(
    ("installed", "expected"),
    [
        (True, []),
        (
            False,
            ["Служба Tenga Proxy не установлена: TUN-режим недоступен. Переустановите приложение"],
        ),
    ],
)
def test_windows_needs_the_service(installed, expected):
    def query(_name):
        if not installed:
            raise OSError("service does not exist")

    assert windows.tun_problems("C:/xray.exe", query=query) == expected
