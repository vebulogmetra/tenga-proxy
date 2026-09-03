from __future__ import annotations

import ipaddress
import logging
import os
import shlex
import shutil
import socket
import subprocess
from dataclasses import dataclass

logger = logging.getLogger("tenga.sys.tun_route")
HELPER_PATH = "/usr/local/libexec/tenga-proxy/tun-route-helper"


@dataclass
class TunRouteState:
    """State required to restore system routes after TUN session."""

    default_gateway: str | None
    default_dev: str
    default_metric: str | None
    proxy_ip: str
    tun_name: str


def _run_command(cmd: list[str], timeout: int = 10) -> tuple[bool, str, str]:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return False, "", str(e)


def _run_ip_privileged(args: list[str], timeout: int = 15) -> tuple[bool, str]:
    """Run `ip` command with best-effort privilege escalation."""
    attempts: list[list[str]] = [["ip", *args]]

    if shutil.which("sudo"):
        attempts.append(["sudo", "-n", "ip", *args])

    last_err = "unknown error"
    for cmd in attempts:
        ok, _out, err = _run_command(cmd, timeout=timeout)
        if ok:
            return True, ""
        last_err = err or "command failed"

    return False, last_err


def _run_ip_batch_privileged(commands: list[list[str]], timeout: int = 20) -> tuple[bool, str]:
    """Run multiple `ip` commands with single privilege escalation prompt."""
    if not commands:
        return True, ""

    # Try direct execution first (no escalation)
    all_ok = True
    for args in commands:
        ok, _out, _err = _run_command(["ip", *args], timeout=timeout)
        if not ok:
            all_ok = False
            break
    if all_ok:
        return True, ""

    # Single escalated shell invocation to avoid multiple password prompts.
    chain = " && ".join("ip " + " ".join(shlex.quote(part) for part in args) for args in commands)

    attempts: list[list[str]] = []
    if shutil.which("sudo"):
        attempts.append(["sudo", "-n", "/bin/sh", "-lc", chain])

    last_err = "unknown error"
    for cmd in attempts:
        ok, _out, err = _run_command(cmd, timeout=timeout)
        if ok:
            return True, ""
        last_err = err or "command failed"

    return False, last_err


def _run_helper(action: str, args: list[str], timeout: int = 15) -> tuple[bool, str]:
    """Run installed root helper via passwordless sudo if available."""
    if not os.path.exists(HELPER_PATH):
        return False, "helper not installed"
    if not shutil.which("sudo"):
        return False, "sudo not found"

    cmd = ["sudo", "-n", HELPER_PATH, action, *args]
    ok, _out, err = _run_command(cmd, timeout=timeout)
    if ok:
        return True, ""
    return False, err or "helper command failed"


def _parse_default_route(line: str) -> tuple[str | None, str | None, str | None]:
    """Parse `ip route show default` line into gateway/dev/metric."""
    parts = line.split()
    gateway = None
    dev = None
    metric = None

    if "via" in parts:
        i = parts.index("via")
        if i + 1 < len(parts):
            gateway = parts[i + 1]
    if "dev" in parts:
        i = parts.index("dev")
        if i + 1 < len(parts):
            dev = parts[i + 1]
    if "metric" in parts:
        i = parts.index("metric")
        if i + 1 < len(parts):
            metric = parts[i + 1]

    return gateway, dev, metric


def _resolve_ipv4(host: str) -> str | None:
    """Resolve host to IPv4 address."""
    host = (host or "").strip()
    if not host:
        return None

    try:
        return str(ipaddress.IPv4Address(host))
    except Exception:
        pass

    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
        for info in infos:
            ip = info[4][0]
            if ip:
                try:
                    return str(ipaddress.IPv4Address(ip))
                except Exception:
                    continue
    except Exception as e:
        logger.warning("Failed to resolve host '%s': %s", host, e)
    return None


def apply_tun_routes(tun_name: str, proxy_host: str) -> tuple[bool, TunRouteState | None, str]:
    """
    Route default traffic into TUN while keeping proxy server reachable via physical interface.
    """
    ok, out, err = _run_command(["ip", "route", "show", "default"])
    if not ok:
        return False, None, f"Cannot read default route: {err}"

    default_line = ""
    for line in out.splitlines():
        if line.strip().startswith("default "):
            default_line = line.strip()
            break
    if not default_line:
        return False, None, "Default route not found"

    gateway, dev, metric = _parse_default_route(default_line)
    if not dev:
        return False, None, f"Cannot parse default route device from: {default_line}"

    proxy_ip = _resolve_ipv4(proxy_host)
    if not proxy_ip:
        return False, None, f"Cannot resolve proxy host: {proxy_host}"

    if gateway:
        route_proxy_args = ["route", "replace", f"{proxy_ip}/32", "via", gateway, "dev", dev]
    else:
        route_proxy_args = ["route", "replace", f"{proxy_ip}/32", "dev", dev]

    helper_args = [
        tun_name,
        proxy_ip,
        gateway if gateway else "-",
        dev,
        metric if metric else "-",
    ]
    ok, err = _run_helper("apply", helper_args)
    if not ok:
        ok, err = _run_ip_batch_privileged(
            [
                route_proxy_args,
                ["route", "replace", "default", "dev", tun_name],
            ]
        )
    if not ok:
        return False, None, f"Cannot apply TUN routes: {err}"

    state = TunRouteState(
        default_gateway=gateway,
        default_dev=dev,
        default_metric=metric,
        proxy_ip=proxy_ip,
        tun_name=tun_name,
    )
    logger.info("TUN routes applied: default->%s, proxy %s via %s", tun_name, proxy_ip, dev)
    return True, state, ""


def restore_tun_routes(state: TunRouteState | None) -> tuple[bool, str]:
    """Restore system routes after TUN session."""
    if state is None:
        return True, ""

    if state.default_gateway:
        args = [
            "route",
            "replace",
            "default",
            "via",
            state.default_gateway,
            "dev",
            state.default_dev,
        ]
    else:
        args = ["route", "replace", "default", "dev", state.default_dev]

    if state.default_metric:
        args.extend(["metric", state.default_metric])

    helper_args = [
        state.proxy_ip,
        state.default_gateway if state.default_gateway else "-",
        state.default_dev,
        state.default_metric if state.default_metric else "-",
    ]
    used_helper = False
    ok, err = _run_helper("restore", helper_args)
    if not ok:
        ok, err = _run_ip_batch_privileged([args])
    else:
        used_helper = True
    if not ok:
        return False, f"Cannot restore default route: {err}"

    # Best effort cleanup when helper was not used.
    if not used_helper:
        _run_command(["ip", "route", "del", f"{state.proxy_ip}/32"])
    logger.info("TUN routes restored: default->%s", state.default_dev)
    return True, ""
