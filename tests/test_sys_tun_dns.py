"""Направление системного DNS в TUN через systemd-resolved."""

from __future__ import annotations

from src.sys import tun_dns


def test_installed_helper_is_preferred(monkeypatch):
    calls: list[tuple] = []

    def helper(action, args, timeout=15):
        calls.append((action, args))
        return True, ""

    monkeypatch.setattr(tun_dns, "_run_helper", helper)
    monkeypatch.setattr(tun_dns.shutil, "which", lambda _name: "/usr/bin/resolvectl")

    assert tun_dns.route_system_dns_to_tun("xray0") == (True, "")
    assert calls == [("dns", ["xray0"])]


def test_without_helper_resolvectl_is_called_without_prompting(monkeypatch):
    """Старый helper действия `dns` не знает — пробуем сами, но пароль не спрашиваем."""
    commands: list[list[str]] = []

    def run(cmd, timeout=10):
        commands.append(cmd)
        return True, "", ""

    monkeypatch.setattr(tun_dns, "_run_helper", lambda *_a, **_k: (False, "unknown action"))
    monkeypatch.setattr(tun_dns, "_run_command", run)
    monkeypatch.setattr(tun_dns.shutil, "which", lambda name: f"/usr/bin/{name}")

    assert tun_dns.route_system_dns_to_tun("xray0") == (True, "")
    assert commands == [
        ["resolvectl", "--no-ask-password", "dns", "xray0", tun_dns.TUN_DNS_ADDRESS],
        ["resolvectl", "--no-ask-password", "domain", "xray0", "~."],
    ]


def test_sudo_is_the_last_resort(monkeypatch):
    commands: list[list[str]] = []

    def run(cmd, timeout=10):
        commands.append(cmd)
        return cmd[0] == "sudo", "", "" if cmd[0] == "sudo" else "access denied"

    monkeypatch.setattr(tun_dns, "_run_helper", lambda *_a, **_k: (False, "helper not installed"))
    monkeypatch.setattr(tun_dns, "_run_command", run)
    monkeypatch.setattr(tun_dns.shutil, "which", lambda name: f"/usr/bin/{name}")

    assert tun_dns.route_system_dns_to_tun("xray0") == (True, "")
    assert commands[-1] == ["sudo", "-n", "resolvectl", "domain", "xray0", "~."]


def test_failure_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(tun_dns, "_run_helper", lambda *_a, **_k: (False, "helper not installed"))
    monkeypatch.setattr(tun_dns, "_run_command", lambda *_a, **_k: (False, "", "denied"))
    monkeypatch.setattr(tun_dns.shutil, "which", lambda name: f"/usr/bin/{name}")

    ok, error = tun_dns.route_system_dns_to_tun("xray0")

    assert not ok
    assert "denied" in error


def test_system_without_systemd_resolved_is_left_alone(monkeypatch):
    called: list[str] = []
    monkeypatch.setattr(tun_dns, "_run_helper", lambda *_a, **_k: called.append("helper"))
    monkeypatch.setattr(tun_dns.shutil, "which", lambda _name: None)

    ok, error = tun_dns.route_system_dns_to_tun("xray0")

    assert not ok
    assert "resolvectl" in error
    assert called == []


def test_helper_uses_fixed_dns_without_touching_the_system(tmp_path):
    import os
    import subprocess
    from pathlib import Path

    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls"
    for name, body in {
        "id": "echo 0",
        "resolvectl": 'printf "%s\\n" "$*" >> "$TEST_DNS_LOG"',
    }.items():
        executable = bindir / name
        executable.write_text("#!/bin/sh\n" + body + "\n")
        executable.chmod(0o755)
    result = subprocess.run(
        ["sh", str(Path("core/scripts/tun_route_helper.sh")), "dns", "testtun0"],
        env={**os.environ, "PATH": f"{bindir}:/usr/bin:/bin", "TEST_DNS_LOG": str(log)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == ["dns testtun0 1.1.1.1", "domain testtun0 ~."]


def test_invalid_interface_is_rejected_before_any_system_call(monkeypatch):
    calls = []
    monkeypatch.setattr(tun_dns.shutil, "which", lambda _name: "/usr/bin/resolvectl")
    monkeypatch.setattr(tun_dns, "_run_helper", lambda *args: calls.append(args) or (True, ""))
    for interface in ["", "-option", "bad name", "bad\nname", "/dev/xray", "x" * 33]:
        ok, error = tun_dns.route_system_dns_to_tun(interface)
        assert not ok
        assert error
    assert calls == []
