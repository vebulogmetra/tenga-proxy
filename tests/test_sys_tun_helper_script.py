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


# --- таблица nftables: правила собирает сам помощник, по аргументам ---


def test_firewall_apply_full_writes_one_atomic_script(fakebin, tmp_path):
    result, log = run_helper(
        fakebin,
        tmp_path,
        "firewall-apply",
        "full",
        "xray0",
        "tun0",
        "203.0.113.5,2001:db8::5",
        "closed",
    )

    assert result.returncode == 0, result.stderr
    assert log.startswith("-f -\n")
    assert log.count("-f -") == 1
    assert "flush table inet veblock" in log
    assert log.index("flush table") < log.index("chain output")
    assert 'oifname "xray0" accept' in log
    assert 'oifname "tun0" accept' in log
    assert "ip daddr { 203.0.113.5 } accept" in log
    assert "ip6 daddr { 2001:db8::5 } accept" in log
    assert "tcp dport 53 reject with tcp reset" in log
    assert "udp dport 53 reject with icmpx type admin-prohibited" in log
    assert "meta mark 0x7e6a accept" in log
    assert "\n    meta l4proto tcp reject with tcp reset\n" in log
    assert "\n    reject with icmpx type admin-prohibited\n" in log
    assert "nfproto ipv6" not in log
    assert log.rstrip().endswith("}")


def test_firewall_mark_is_the_one_the_core_sets():
    from src.sys.firewall_policy import SOCKET_MARK

    assert f"meta mark 0x{SOCKET_MARK:x} accept" in HELPER.read_text()


def test_firewall_vpn_rules_go_before_the_dns_rule(fakebin, tmp_path):
    """DNS до сервера VPN и внутри него не должен упираться в запрет порта 53."""
    _, log = run_helper(
        fakebin, tmp_path, "firewall-apply", "full", "xray0", "tun0", "203.0.113.5", "closed"
    )

    output = log[log.index("chain output") : log.index("chain forward")]
    assert output.index('oifname "tun0"') < output.index("dport 53")
    assert output.index("203.0.113.5") < output.index("dport 53")


def test_firewall_dns_rule_goes_before_local_networks(fakebin, tmp_path):
    """Иначе запрос на роутер пройдёт по разрешению локальной сети."""
    _, log = run_helper(fakebin, tmp_path, "firewall-apply", "full", "xray0", "-", "-", "closed")

    output = log[log.index("chain output") : log.index("chain forward")]
    assert output.index("dport 53") < output.index("192.168.0.0/16")


def test_firewall_forward_chain_does_not_trust_the_mark(fakebin, tmp_path):
    _, log = run_helper(fakebin, tmp_path, "firewall-apply", "full", "xray0", "-", "-", "open")

    assert "meta mark" not in log[log.index("chain forward") :]


def test_firewall_ipv6_only_touches_only_ipv6(fakebin, tmp_path):
    result, log = run_helper(
        fakebin, tmp_path, "firewall-apply", "ipv6_only", "xray0", "-", "-", "open"
    )

    assert result.returncode == 0, result.stderr
    assert "meta nfproto ipv6 meta l4proto tcp reject with tcp reset" in log
    assert "meta nfproto ipv6 reject with icmpx type admin-prohibited" in log
    assert "\n    reject with" not in log
    assert "\n    meta l4proto tcp reject" not in log
    assert "dport 53" not in log
    assert 'oifname "tun0"' not in log


def test_firewall_with_open_dns_has_no_dns_rule(fakebin, tmp_path):
    _, log = run_helper(fakebin, tmp_path, "firewall-apply", "full", "xray0", "-", "-", "open")

    assert "dport 53" not in log


def test_firewall_local_networks_match_the_routing_list(fakebin, tmp_path):
    from src.db.config import LOCAL_NETWORKS

    _, log = run_helper(fakebin, tmp_path, "firewall-apply", "full", "xray0", "-", "-", "open")

    for network in LOCAL_NETWORKS:
        assert network in log


@pytest.mark.parametrize(
    "args",
    [
        ("loose", "xray0", "-", "-", "closed"),
        ("full", "xray0; nft flush ruleset", "-", "-", "closed"),
        ("full", "xray0\nflush ruleset", "-", "-", "closed"),
        ("full", "xray0", 'tun0"', "-", "closed"),
        ("full", "xray0", "-", "not-an-ip", "closed"),
        ("full", "xray0", "-", "1.2.3.4 } accept; flush ruleset; {", "closed"),
        ("full", "xray0", "-", "1.2.3.4\nflush ruleset", "closed"),
        ("full", "xray0", "-", "2001:db8::1\nflush ruleset", "closed"),
        ("full", "xray0", "-", "*", "closed"),
        ("full", "xray0", "-", "-", "maybe"),
        ("full", "xray0", "-", "-"),
        ("full", "xray0", "-", "-", "closed", "extra"),
    ],
)
def test_firewall_bad_arguments_are_refused_before_nft_runs(fakebin, tmp_path, args):
    result, log = run_helper(fakebin, tmp_path, "firewall-apply", *args)

    assert result.returncode == 1
    assert log == ""


def test_firewall_remove_tolerates_a_missing_table(fakebin, tmp_path):
    _fake(fakebin, "nft", "exit 1")

    result, _ = run_helper(fakebin, tmp_path, "firewall-remove")

    assert result.returncode == 0


def test_firewall_remove_deletes_only_our_table(fakebin, tmp_path):
    _fake(fakebin, "nft", 'echo "$@" >> "$FAKE_LOG"')

    _, log = run_helper(fakebin, tmp_path, "firewall-remove")

    assert log.strip() == "delete table inet veblock"


def test_features_lists_the_firewall(fakebin, tmp_path):
    result, _ = run_helper(fakebin, tmp_path, "features")

    assert result.returncode == 0
    assert "firewall" in result.stdout.split()


def test_unknown_action_is_refused(fakebin, tmp_path):
    result, log = run_helper(fakebin, tmp_path, "flush-everything")

    assert result.returncode == 1
    assert log == ""


# --- prerm: find и nft подменены, настоящая установка не затрагивается ---

PRERM = HELPER.parents[2] / "packaging/linux/prerm"


def run_prerm(fakebin, tmp_path, *args):
    _fake(fakebin, "find", 'echo "find" >> "$FAKE_LOG"')
    log = tmp_path / "commands.log"
    env = {**os.environ, "PATH": f"{fakebin}:{os.environ['PATH']}", "FAKE_LOG": str(log)}
    result = subprocess.run(["sh", str(PRERM), *args], env=env, capture_output=True, text=True)
    return result, (log.read_text() if log.exists() else "")


@pytest.mark.parametrize("action", ["remove", "purge"])
def test_prerm_removes_the_table_when_the_package_goes_away(fakebin, tmp_path, action):
    result, log = run_prerm(fakebin, tmp_path, action)

    assert result.returncode == 0
    assert "delete table inet veblock" in log


@pytest.mark.parametrize("action", ["upgrade", "failed-upgrade", "deconfigure"])
def test_prerm_keeps_the_table_on_upgrade(fakebin, tmp_path, action):
    """Трафик не должен открыться посреди apt upgrade у идущего сеанса."""
    result, log = run_prerm(fakebin, tmp_path, action)

    assert result.returncode == 0
    assert "veblock" not in log


def test_prerm_survives_a_missing_table(fakebin, tmp_path):
    _fake(fakebin, "nft", "exit 1")

    result, _ = run_prerm(fakebin, tmp_path, "remove")

    assert result.returncode == 0
