"""Политика блокировки трафика превращается в аргументы помощника."""

from __future__ import annotations

from dataclasses import replace

from src.sys.firewall_policy import FirewallPolicy, Level
from src.sys.linux import tun_firewall


def test_ipv6_only_policy_arguments():
    policy = FirewallPolicy(level=Level.IPV6_ONLY, tun_name="xray0")

    assert policy.helper_args() == ["ipv6_only", "xray0", "-", "-", "open"]


def test_full_policy_with_vpn_and_closed_dns():
    policy = FirewallPolicy(
        level=Level.FULL,
        tun_name="xray0",
        vpn_interface="tun0",
        vpn_addresses=("203.0.113.5", "2001:db8::5"),
        dns_closed=True,
    )

    assert policy.helper_args() == ["full", "xray0", "tun0", "203.0.113.5,2001:db8::5", "closed"]


def test_network_dns_is_passed_only_while_the_window_is_open():
    policy = FirewallPolicy(Level.FULL, "xray0", dns_addresses=("203.0.113.53", "8.8.8.8"))

    assert policy.helper_args() == ["full", "xray0", "-", "-", "open", "203.0.113.53,8.8.8.8"]
    assert replace(policy, dns_closed=True).helper_args() == [
        "full",
        "xray0",
        "-",
        "-",
        "closed",
    ]


def _helper_answers(monkeypatch, answer):
    calls = []

    def run_helper(action, args):
        calls.append((action, args))
        return answer

    monkeypatch.setattr(tun_firewall, "_run_helper", run_helper)
    return calls


def test_apply_goes_through_the_helper(monkeypatch):
    calls = _helper_answers(monkeypatch, (True, ""))

    result = tun_firewall.apply_firewall(FirewallPolicy(Level.IPV6_ONLY, "xray0"))

    assert result == (True, "")
    assert calls == [("firewall-apply", ["ipv6_only", "xray0", "-", "-", "open"])]


def test_apply_without_a_helper_reports_the_reason(monkeypatch):
    """Из исходников помощника нет: nft напрямую не зовём, пароль не спрашиваем."""
    _helper_answers(monkeypatch, (False, "helper not installed"))

    ok, error = tun_firewall.apply_firewall(FirewallPolicy(Level.FULL, "xray0"))

    assert not ok
    assert "helper not installed" in error


def test_remove_goes_through_the_helper(monkeypatch):
    calls = _helper_answers(monkeypatch, (True, ""))

    assert tun_firewall.remove_firewall() == (True, "")
    assert calls == [("firewall-remove", [])]


def test_remove_without_a_helper_is_not_an_error(monkeypatch):
    """Без помощника таблицу некому было поставить."""
    _helper_answers(monkeypatch, (False, "helper not installed"))

    assert tun_firewall.remove_firewall() == (True, "")


def test_remove_failure_is_reported(monkeypatch):
    _helper_answers(monkeypatch, (False, "sudo: a password is required"))

    ok, error = tun_firewall.remove_firewall()

    assert not ok
    assert "password" in error
