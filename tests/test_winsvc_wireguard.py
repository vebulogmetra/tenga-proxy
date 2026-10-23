"""Туннели WireGuard: имена, команды wireguard.exe, состояние служб."""

from __future__ import annotations

import pytest

from src.winsvc import wireguard


def test_tunnel_names_from_configuration_dir(tmp_path):
    (tmp_path / "home.conf.dpapi").write_bytes(b"x")
    (tmp_path / "work-2.conf.dpapi").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("x")

    assert wireguard.list_tunnels(tmp_path) == ["home", "work-2"]


@pytest.mark.parametrize("bad", ["", "a" * 33, "x y", "..\\evil", "a;b"])
def test_bad_names_are_rejected(bad):
    with pytest.raises(ValueError, match="bad WireGuard tunnel name"):
        wireguard.validate_name(bad)


def test_up_command_points_at_dpapi_config(tmp_path):
    cmd = wireguard.up_command("home", exe="C:/WG/wireguard.exe", config_dir=tmp_path)

    assert cmd == [
        "C:/WG/wireguard.exe",
        "/installtunnelservice",
        str(tmp_path / "home.conf.dpapi"),
    ]


def test_down_command():
    assert wireguard.down_command("home", exe="wg.exe") == [
        "wg.exe",
        "/uninstalltunnelservice",
        "home",
    ]


def test_service_name():
    assert wireguard.service_name("home") == "WireGuardTunnel$home"
