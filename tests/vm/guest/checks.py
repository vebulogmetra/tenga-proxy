"""Сценарии блокировки трафика на установленном пакете. Запускает `tests/vm/run_vm_tests.py`.

Файл не называется test_*: основной pytest его не соберёт, вне виртуалки он сбросил бы сеть
(`lab.py` дополнительно проверяет, что запущен в виртуалке). Порядок важен только в конце:
последняя проверка удаляет пакет.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import lab
import pytest
from lab import (
    DIRECT,
    DIRECT6,
    EXIT_A,
    EXIT_B,
    LAN_PEER,
    LAN_SELF,
    SITE,
    SITE6,
    VPN_NAME,
    VPN_PEER,
    VPN_SELF,
    VPN_SERVER,
    Application,
    Prober,
    direct_hits,
    kill_core,
    refusal_seconds,
    resolve,
    table,
    tun_is_default,
    uplink_is_default,
    wait_until,
)

# Отказ правила приходит сразу; запас — на загруженную виртуалку.
FAST_REFUSAL = 1.0


@pytest.fixture(scope="session", autouse=True)
def laboratory():
    lab.set_up_once()


@pytest.fixture
def app(request):
    lab.reset_network()
    application = Application()
    application.seed(kill_switch=False)
    application.start()
    yield application
    lab.save_logs(request.node.name)
    application.kill()


@pytest.fixture
def guarded(app):
    """Сессия с блокировкой: приложение перезапущено с настройкой, утечки ловятся в конце."""
    app.kill()
    app.seed(kill_switch=True)
    app.start()
    lab.clear_logs()
    yield app
    assert direct_hits() == [], "Запросы ушли мимо туннеля"


def probe_name() -> str:
    return f"probe-{uuid.uuid4().hex[:12]}.veblock.test"


def dns_sources(name: str) -> list[str]:
    return [entry["src"] for entry in lab.read_log("dns.jsonl") if entry["name"] == name]


@contextmanager
def core_unavailable():
    """Следующий запуск ядра не удастся: так проще всего сорвать подключение."""
    os.chmod(lab.PACKAGE_XRAY, 0o000)
    try:
        yield
    finally:
        os.chmod(lab.PACKAGE_XRAY, 0o755)


def crash_until_blocked(app: Application) -> None:
    """Первое падение ядро переживает перезапуском, второе за минуту — уже нет."""
    first = kill_core()
    wait_until(lambda: lab.core_pids() and first not in lab.core_pids(), "перезапуск ядра")
    app.wait_for_exit(EXIT_A)
    kill_core()
    app.wait_state("трафик заблокирован")
    wait_until(lambda: not lab.core_pids(), "ядро больше не запущено")


def assert_closed_outside_open_inside() -> None:
    for host in (SITE, SITE6):
        assert refusal_seconds(host) < FAST_REFUSAL
    assert lab.try_get(LAN_PEER) == LAN_SELF, "Локальная сеть должна остаться доступной"
    name = probe_name()
    assert resolve(name) is None, "Имя разрешилось при закрытом трафике"
    assert dns_sources(name) == [], "DNS-запрос дошёл до сервера"


# --- пакет ---


def test_package_grants_only_what_the_tun_mode_needs():
    capabilities = lab.sh("getcap", lab.PACKAGE_XRAY).stdout
    assert "cap_net_admin" in capabilities

    as_tester = ("runuser", "-u", lab.USER, "--", "sudo", "-n")
    helper = "/usr/libexec/tenga-proxy/tun-route-helper"
    features = lab.sh(*as_tester, helper, "features").stdout
    assert "firewall" in features.split()

    refused = lab.sh(
        *as_tester, helper, "firewall-apply", "full", "x;id", "-", "-", "open", check=False
    )
    assert refused.returncode != 0
    assert table() is None

    assert lab.sh(*as_tester, "nft", "list", "ruleset", check=False).returncode != 0


# --- без настройки: закрыт только IPv6 ---


def test_tun_session_closes_ipv6_and_disconnect_undoes_everything(app):
    assert lab.try_get(SITE6) == DIRECT6, "IPv6 до подключения должен работать"

    app.connect("A", EXIT_A)

    rules = table()
    assert rules is not None and "meta nfproto ipv6" in rules
    assert tun_is_default()
    assert refusal_seconds(SITE6) < FAST_REFUSAL
    assert lab.try_get(LAN_PEER) == LAN_SELF
    name = probe_name()
    assert resolve(name) == SITE
    assert set(dns_sources(name)) == {EXIT_A}

    app.action("disconnect")
    app.wait_state("отключено")

    wait_until(lambda: table() is None, "таблица снята")
    wait_until(uplink_is_default, "маршрут возвращён")
    assert lab.try_get(SITE) == DIRECT
    assert lab.try_get(SITE6) == DIRECT6


def test_without_the_setting_a_dead_core_opens_direct_traffic(app):
    app.connect("A", EXIT_A)
    first = kill_core()
    wait_until(lambda: lab.core_pids() and first not in lab.core_pids(), "перезапуск ядра")
    app.wait_for_exit(EXIT_A)

    kill_core()

    app.wait_state("ошибка")
    wait_until(lambda: table() is None, "таблица снята")
    wait_until(uplink_is_default, "маршрут возвращён")
    assert lab.try_get(SITE) == DIRECT


# --- уровень full ---


def test_full_session_sends_everything_through_the_reality_server(guarded):
    guarded.connect("A", EXIT_A)

    rules = table()
    assert "tcp dport 53 reject" in rules, "Окно DNS должно быть закрыто после подключения"
    assert tun_is_default()
    assert refusal_seconds(SITE6) < FAST_REFUSAL
    assert lab.try_get(LAN_PEER) == LAN_SELF
    name = probe_name()
    assert resolve(name) == SITE
    assert set(dns_sources(name)) == {EXIT_A}


def test_first_core_crash_restarts_without_a_gap(guarded):
    guarded.connect("A", EXIT_A)

    with Prober() as probe:
        first = kill_core()
        wait_until(lambda: lab.core_pids() and first not in lab.core_pids(), "перезапуск ядра")
        guarded.wait_for_exit(EXIT_A)
        guarded.wait_state("A")

    assert DIRECT not in probe.sources, "Запрос ушёл напрямую, пока ядра не было"
    assert table() is not None


def test_second_crash_blocks_and_reconnect_returns_to_the_same_server(guarded):
    guarded.connect("A", EXIT_A)

    with Prober() as probe:
        crash_until_blocked(guarded)
        time.sleep(1)
    assert DIRECT not in probe.sources

    assert table() is not None
    assert_closed_outside_open_inside()

    guarded.action("toggle-connection")
    guarded.wait_for_exit(EXIT_A)
    guarded.wait_state("A")
    assert table() is not None


def test_release_block_opens_the_network(guarded):
    guarded.connect("A", EXIT_A)
    crash_until_blocked(guarded)
    lab.clear_logs()

    guarded.action("release-block")

    guarded.wait_state("отключено")
    wait_until(lambda: table() is None, "таблица снята")
    wait_until(uplink_is_default, "маршрут возвращён")
    assert lab.try_get(SITE) == DIRECT
    # Сайт видел прямой адрес после снятия, и это не утечка.
    lab.clear_logs()


@pytest.mark.parametrize("with_core", [False, True], ids=["app-only", "app-and-core"])
def test_killed_application_stays_closed_until_the_next_start(guarded, with_core):
    guarded.connect("A", EXIT_A)

    with Prober() as probe:
        guarded.kill()
        if with_core:
            for pid in lab.core_pids():
                os.kill(pid, signal.SIGKILL)
            wait_until(lambda: not lab.core_pids(), "ядро убито")
            assert refusal_seconds(SITE) < FAST_REFUSAL
        time.sleep(2)
    assert DIRECT not in probe.sources
    assert table() is not None, "Падение приложения не должно открывать трафик"

    guarded.start()

    wait_until(lambda: table() is None, "таблицу снял запуск")
    wait_until(uplink_is_default, "маршрут вернул запуск")
    wait_until(lambda: not lab.core_pids(), "осиротевшее ядро погашено")
    assert "Traffic block left by a crashed session was removed" in guarded.log_text()
    lab.clear_logs()
    assert lab.try_get(SITE) == DIRECT
    lab.clear_logs()


def test_server_change_keeps_the_block_and_resolves_a_named_server(guarded):
    guarded.connect("A", EXIT_A)

    with Prober() as probe:
        guarded.connect("B", EXIT_B)
    assert DIRECT not in probe.sources

    rules = table()
    assert rules is not None
    assert "tcp dport 53 reject" in rules, "Окно DNS должно закрыться после смены"


def test_named_server_connects_when_the_network_dns_is_public(guarded):
    """DNS сети не в локальных адресах: мобильная точка, 8.8.8.8, прописанный вручную."""
    lab.sh("nmcli", "connection", "modify", lab.UPLINK_PROFILE, "ipv4.dns", lab.DNS_SERVER)
    lab.sh("nmcli", "connection", "up", lab.UPLINK_PROFILE, timeout=45)
    try:
        guarded.connect("B", EXIT_B)
    except AssertionError:
        # Неудачное первое подключение открывает сеть, и проверка шла напрямую законно.
        lab.clear_logs()
        raise
    finally:
        lab.sh("nmcli", "connection", "modify", lab.UPLINK_PROFILE, "ipv4.dns", lab.LAN_PEER)


def test_failed_server_change_stays_blocked(guarded):
    guarded.connect("A", EXIT_A)
    with core_unavailable():
        guarded.action("connect-profile", f"[<int32 {guarded.ids['B']}>]")
        guarded.wait_state("трафик заблокирован")

    assert table() is not None
    assert_closed_outside_open_inside()


def test_failed_first_connect_does_not_leave_the_network_closed(guarded):
    with core_unavailable():
        guarded.action("connect-profile", f"[<int32 {guarded.ids['A']}>]")
        guarded.wait_state("ошибка")

    wait_until(lambda: table() is None, "таблица снята")
    assert lab.try_get(SITE) == DIRECT
    lab.clear_logs()


@pytest.mark.parametrize("how", ["disconnect", "quit", "sigterm"])
def test_every_clean_exit_opens_the_network(guarded, how):
    guarded.connect("A", EXIT_A)

    if how == "disconnect":
        guarded.action("disconnect")
    elif how == "quit":
        guarded.action("quit")
    else:
        guarded.terminate()

    wait_until(lambda: table() is None, "таблица снята", timeout=30)
    wait_until(uplink_is_default, "маршрут возвращён", timeout=30)
    wait_until(lambda: not lab.core_pids(), "ядро остановлено")
    assert lab.try_get(SITE) == DIRECT
    lab.clear_logs()


def test_network_flap_does_not_leak_and_the_session_recovers(guarded):
    """Замена смены Wi-Fi: физическое подключение пропадает и появляется снова."""
    guarded.connect("A", EXIT_A)

    with Prober() as probe:
        lab.sh("nmcli", "connection", "down", lab.UPLINK_PROFILE, timeout=45)
        time.sleep(2)
        lab.sh("nmcli", "connection", "up", lab.UPLINK_PROFILE, timeout=45)
        guarded.wait_for_exit(EXIT_A, timeout=60)

    assert DIRECT not in probe.sources
    assert table() is not None


def test_container_traffic_is_closed_with_the_host(guarded):
    command = (
        "docker", "run", "--rm", "lab-busybox",
        "/bin/busybox", "wget", "-T", "5", "-q", "-O", "-", f"http://{SITE}/container",
    )  # fmt: skip
    guarded.connect("A", EXIT_A)

    assert lab.sh(*command, timeout=60).stdout == EXIT_A

    crash_until_blocked(guarded)

    assert lab.sh(*command, check=False, timeout=60).returncode != 0, "Контейнер вышел наружу"


def vpn_active() -> bool:
    active = lab.sh("nmcli", "-t", "-f", "NAME", "connection", "show", "--active").stdout
    return VPN_NAME in active.split()


def test_openvpn_survives_the_block_and_reconnects_under_it(guarded):
    guarded.connect("V", EXIT_B)

    assert vpn_active()
    rules = table()
    assert VPN_SERVER in rules, "Адрес сервера VPN должен быть открыт"
    wait_until(lambda: lab.try_get(VPN_PEER) == VPN_SELF, "сайт за VPN")

    first = kill_core()
    wait_until(lambda: lab.core_pids() and first not in lab.core_pids(), "перезапуск ядра")
    guarded.wait_for_exit(EXIT_B)
    kill_core()
    guarded.wait_state("трафик заблокирован")

    assert vpn_active(), "VPN не должен гаснуть вместе с ядром"
    assert lab.try_get(VPN_PEER) == VPN_SELF, "VPN должен работать при блокировке"
    assert refusal_seconds(SITE) < FAST_REFUSAL

    # Обрыв и переподключение: достучаться до сервера VPN можно только через его адрес в таблице.
    lab.sh("nmcli", "connection", "down", VPN_NAME, timeout=45)
    # Пока tun0 не освобождён, новый клиент получит tun1, а в таблице открыт tun0.
    wait_until(
        lambda: lab.sh("ip", "link", "show", "tun0", check=False).returncode != 0,
        "tun0 освобождён",
    )
    lab.sh("nmcli", "connection", "up", VPN_NAME, timeout=60)
    wait_until(lambda: lab.try_get(VPN_PEER) == VPN_SELF, "VPN снова работает")
    assert refusal_seconds(SITE) < FAST_REFUSAL

    guarded.action("release-block")
    wait_until(lambda: table() is None, "таблица снята")
    wait_until(lambda: not vpn_active(), "VPN погашен отключением", timeout=45)
    lab.clear_logs()


# --- обновление и удаление: последними, удаление убирает пакет ---


def test_package_upgrade_keeps_the_session_closed(guarded):
    guarded.connect("A", EXIT_A)

    subprocess.run(["dpkg", "-i", os.environ["VEBLOCK_PACKAGE"]], check=True, capture_output=True)

    assert table() is not None, "Обновление не должно снимать блокировку"
    assert lab.try_get(SITE) == EXIT_A
    assert "cap_net_admin" in lab.sh("getcap", lab.PACKAGE_XRAY).stdout


def test_package_removal_opens_a_blocked_network(guarded):
    guarded.connect("A", EXIT_A)
    crash_until_blocked(guarded)
    assert table() is not None

    guarded.kill()
    subprocess.run(
        ["apt-get", "remove", "-y", "tenga-proxy"],
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
    )

    assert table() is None, "Удаление пакета должно снять таблицу"
    assert not Path("/usr/libexec/tenga-proxy/tun-route-helper").exists()
    wait_until(lambda: lab.try_get(SITE) == DIRECT, "сайт напрямую")
    lab.clear_logs()
