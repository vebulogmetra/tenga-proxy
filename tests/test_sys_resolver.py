"""Какие DNS-серверы использует система на физическом интерфейсе."""

from __future__ import annotations

import subprocess

from src.sys import resolver


def fake_resolvectl(monkeypatch, stdout: str, returncode: int = 0) -> list[list[str]]:
    calls: list[list[str]] = []

    def run(cmd, **_kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(resolver.subprocess, "run", run)
    return calls


def test_link_servers_come_from_systemd_resolved(monkeypatch):
    calls = fake_resolvectl(monkeypatch, "Link 2 (wlp1s0): 192.168.0.1 fe80::1%2 8.8.8.8\n")

    assert resolver.link_dns_servers("wlp1s0") == ["192.168.0.1", "8.8.8.8"]
    assert calls == [["resolvectl", "dns", "wlp1s0"]]


def test_link_without_servers_gives_empty_list(monkeypatch):
    fake_resolvectl(monkeypatch, "Link 5 (docker0):\n")

    assert resolver.link_dns_servers("docker0") == []


def test_missing_resolvectl_gives_empty_list(monkeypatch):
    def run(*_args, **_kwargs):
        raise FileNotFoundError("resolvectl")

    monkeypatch.setattr(resolver.subprocess, "run", run)

    assert resolver.link_dns_servers("eth0") == []


def test_resolv_conf_servers_skip_loopback_stub(tmp_path):
    """`127.0.0.53` — заглушка systemd-resolved, а не настоящий сервер."""
    path = tmp_path / "resolv.conf"
    path.write_text("# comment\nnameserver 127.0.0.53\nnameserver 77.88.8.8\nnameserver ::1\n")

    assert resolver.resolv_conf_servers(path) == ["77.88.8.8"]


def test_system_servers_prefer_the_link_and_fall_back_to_resolv_conf(monkeypatch, tmp_path):
    path = tmp_path / "resolv.conf"
    path.write_text("nameserver 77.88.8.8\n")
    monkeypatch.setattr(resolver, "RESOLV_CONF", path)

    fake_resolvectl(monkeypatch, "Link 2 (eth0): 192.168.0.1\n")
    assert resolver.system_dns_servers("eth0") == ["192.168.0.1"]

    fake_resolvectl(monkeypatch, "", returncode=1)
    assert resolver.system_dns_servers("eth0") == ["77.88.8.8"]
