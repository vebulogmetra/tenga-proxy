"""Встроенные VPN Windows: список, состояние, подключение."""

from __future__ import annotations

import json
import subprocess

from src.sys.windows import ras

LISTING = json.dumps(
    [
        {"name": "Office", "status": "Connected"},
        {"name": "Home", "status": "Disconnected"},
    ]
)


def test_parse_connections():
    assert ras.parse_connections(LISTING) == {"Office": True, "Home": False}


def test_single_object_and_garbage():
    assert ras.parse_connections(json.dumps({"name": "A", "status": "Connected"})) == {"A": True}
    assert ras.parse_connections("oops") == {}


def test_connect_uses_rasdial_exit_code(monkeypatch):
    seen = []

    def run(cmd, **kwargs):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(ras.subprocess, "run", run)

    assert ras.connect("Office") is True
    assert seen == [["rasdial", "Office"]]


def test_disconnect(monkeypatch):
    seen = []
    monkeypatch.setattr(
        ras.subprocess,
        "run",
        lambda cmd, **_kw: seen.append(cmd) or subprocess.CompletedProcess(cmd, 691, "", ""),
    )

    assert ras.disconnect("Office") is False
    assert seen == [["rasdial", "Office", "/disconnect"]]
