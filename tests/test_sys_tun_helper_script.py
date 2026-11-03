"""Помощник tun-route-helper запускается от root без пароля: аргументам он не верит."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[1] / "core/scripts/tun_route_helper.sh"


def _fake(bindir: Path, name: str, body: str) -> None:
    path = bindir / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)


@pytest.fixture
def fakebin(tmp_path):
    """`id` отвечает root, `ip` и `nft` записывают аргументы и stdin и больше ничего."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _fake(bindir, "id", "echo 0")
    _fake(bindir, "ip", 'echo "ip $*" >> "$FAKE_LOG"')
    _fake(bindir, "nft", 'echo "$@" >> "$FAKE_LOG"\ncat >> "$FAKE_LOG"')
    return bindir


def run_helper(fakebin, tmp_path, *args):
    log = tmp_path / "commands.log"
    env = {**os.environ, "PATH": f"{fakebin}:{os.environ['PATH']}", "FAKE_LOG": str(log)}
    result = subprocess.run(["sh", str(HELPER), *args], env=env, capture_output=True, text=True)
    return result, (log.read_text() if log.exists() else "")


def test_apply_with_valid_arguments_runs_ip(fakebin, tmp_path):
    result, log = run_helper(
        fakebin, tmp_path, "apply", "xray0", "1.2.3.4", "10.0.0.1", "eth0", "-"
    )

    assert result.returncode == 0, result.stderr
    assert "ip route replace 1.2.3.4/32 via 10.0.0.1 dev eth0" in log


@pytest.mark.parametrize(
    "proxy_ip",
    [
        "not-an-ip",
        "default",
        "999.1.1.1",
        "1.2.3",
        "1.2.3.4.5",
        "1.2.3.4; reboot",
        "1.2.3.4\n5.6.7.8",
        "01.2.3.4 ",
        "",
    ],
)
def test_bad_ipv4_is_refused_before_ip_runs(fakebin, tmp_path, proxy_ip):
    result, log = run_helper(fakebin, tmp_path, "apply", "xray0", proxy_ip, "-", "eth0", "-")

    assert result.returncode == 1
    assert log == ""


@pytest.mark.parametrize("ifname", ["xray0\nflush ruleset", "xray 0", 'xray0"', "", "a" * 33])
def test_bad_interface_name_is_refused(fakebin, tmp_path, ifname):
    result, log = run_helper(fakebin, tmp_path, "apply", ifname, "1.2.3.4", "-", "eth0", "-")

    assert result.returncode == 1
    assert log == ""


@pytest.mark.parametrize("metric", ["100\n200", "1e3", "-1", ""])
def test_bad_metric_is_refused(fakebin, tmp_path, metric):
    result, log = run_helper(fakebin, tmp_path, "apply", "xray0", "1.2.3.4", "-", "eth0", metric)

    assert result.returncode == 1
    assert log == ""
