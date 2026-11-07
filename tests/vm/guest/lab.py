"""Лаборатория внутри виртуалки: сеть, серверы и приложение из установленного пакета.

Адреса намеренно публичные (TEST-NET): частные правила блокировки пропускают как
локальную сеть, и проверка ничего бы не доказала.

    приложение ── uplink0 198.51.100.2 ── lab0 198.51.100.1 ── пространство inet
                                                               A  203.0.113.10:443  Reality
                                                               B  203.0.113.11:8080 по имени
                                                               VPN 203.0.113.20:1194
                                                               сайт 203.0.113.80, [2001:db8:2::80]
                                                               DNS 203.0.113.53, 1.1.1.1

Сетевой адаптер QEMU остаётся только для ssh: маршрута по умолчанию на нём нет.
"""

from __future__ import annotations

import json
import os
import pwd
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

GUEST_MARKER = Path("/etc/veblock-vm-guest")
if not GUEST_MARKER.exists():
    raise SystemExit("Только внутри виртуалки: здесь сбрасываются маршруты и таблицы nftables")

HERE = Path(__file__).resolve().parent
LAB = Path("/var/lib/veblock-lab")
RUN = Path("/run/veblock-lab")
RESULTS = Path("/var/log/veblock-lab")
USER = "tester"
HOME = Path(f"/home/{USER}")
CONFIG = HOME / ".config/tenga-proxy"
BUS = "unix:path=/tmp/veblock-lab-bus"
DISPLAY = ":99"
PACKAGE_XRAY = "/usr/lib/tenga-proxy/core/bin/xray"

DIRECT = "198.51.100.2"
DIRECT6 = "2001:db8:1::2"
GATEWAY = "198.51.100.1"
LAN_SELF = "192.168.200.2"
LAN_PEER = "192.168.200.1"
EXIT_A = "203.0.113.10"
EXIT_B = "203.0.113.11"
VPN_SERVER = "203.0.113.20"
DNS_SERVER = "203.0.113.53"
PUBLIC_DNS = "1.1.1.1"
SITE = "203.0.113.80"
SITE6 = "2001:db8:2::80"
VPN_PEER = "100.64.8.1"
VPN_SELF = "100.64.8.2"
TUN = "xray0"
VPN_NAME = "lab-vpn"
UPLINK_PROFILE = "lab-uplink"
# Последняя строка потока подключения: мониторинг в настройках лаборатории выключен
SESSION_READY = "Monitoring is disabled in settings"
UUID = "6f1f7c3a-3a55-4c8e-9a0b-2d3f4a5b6c7d"
SHORT_ID = "abcd1234"
REALITY_SNI = "www.veblock.test"


def sh(*command: str, check: bool = True, timeout: float = 60, **kwargs):
    return subprocess.run(
        command, check=check, timeout=timeout, capture_output=True, text=True, **kwargs
    )


def in_inet(*command: str, **kwargs):
    return sh("ip", "netns", "exec", "inet", *command, **kwargs)


def wait_until(predicate, what: str, timeout: float = 30, interval: float = 0.2):
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError(f"Не дождался за {timeout:.0f} с: {what}\n{diagnostics()}")
        time.sleep(interval)


def diagnostics() -> str:
    routes = sh("ip", "route", check=False).stdout + sh("ip", "-6", "route", check=False).stdout
    table = sh("nft", "list", "table", "inet", "veblock", check=False).stdout
    return f"--- маршруты\n{routes}--- таблица\n{table or 'нет'}"


# --- обращения к «интернету» ---


def http_get(host: str, *, timeout: float = 3.0, path: str = "/check") -> str:
    """Адрес, с которого сайт нас увидел. Отказ сети — исключение OSError."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect((host, 80))
        # Host — адрес, как у curl: имя ядро подхватило бы из запроса и отдало серверу на разрешение
        authority = f"[{host}]" if ":" in host else host
        sock.sendall(f"GET {path} HTTP/1.0\r\nHost: {authority}\r\n\r\n".encode())
        # Длина, а не конец потока: закрытие через ядро доходит с задержкой в секунды
        response = b""
        while chunk := sock.recv(4096):
            response += chunk
            head, separator, body = response.partition(b"\r\n\r\n")
            match = re.search(rb"content-length: *(\d+)", head, re.IGNORECASE)
            if separator and match and len(body) >= int(match.group(1)):
                break
    return response.partition(b"\r\n\r\n")[2].decode()


def try_get(host: str, **kwargs) -> str | None:
    try:
        return http_get(host, **kwargs)
    except OSError:
        return None


def refusal_seconds(host: str, *, timeout: float = 5.0) -> float:
    """Сколько длился отказ; отказа нет — AssertionError."""
    started = time.monotonic()
    try:
        source = http_get(host, timeout=timeout)
    except TimeoutError as error:
        raise AssertionError(f"{host}: ответа нет, отказ по таймауту, а не сразу") from error
    except OSError:
        return time.monotonic() - started
    raise AssertionError(f"{host}: запрос прошёл с адреса {source}")


def resolve(name: str, *, timeout: float = 8.0) -> str | None:
    """Имя через системный резолвер, как у обычного приложения."""
    try:
        result = sh("getent", "ahostsv4", name, check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    return result.stdout.split()[0] if result.returncode == 0 and result.stdout else None


def read_log(name: str) -> list[dict]:
    path = LAB / "logs" / name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def direct_hits() -> list[dict]:
    """Запросы к сайту и пробные имена с настоящего адреса машины: это и есть утечка.

    Остальные имена не считаются: пока окно DNS открыто, спрашивать их законно (имя сервера,
    служба времени самой системы).
    """
    # Сайт локальной сети видит LAN_SELF законно, а вот DNS роутера в сеансе спрашивать нельзя.
    sites = [e for e in read_log("echo.jsonl") if e["src"] in (DIRECT, DIRECT6)]
    names = [
        e
        for e in read_log("dns.jsonl")
        if e["name"].startswith("probe-") and e["src"] in (DIRECT, DIRECT6, LAN_SELF)
    ]
    return sites + names


def clear_logs() -> None:
    for name in ("echo.jsonl", "dns.jsonl"):
        (LAB / "logs" / name).write_text("", encoding="utf-8")


class Prober:
    """Частые запросы наружу на всё время опасного окна: щель видна, даже если короткая."""

    def __init__(self, host: str = SITE) -> None:
        self.host = host
        self.sources: list[str] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self) -> None:
        while not self._stop.is_set():
            source = try_get(self.host, timeout=1.0, path="/probe")
            if source:
                self.sources.append(source)
            time.sleep(0.05)

    def __enter__(self) -> Prober:
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._stop.set()
        self._thread.join(5)


# --- таблица и маршруты ---


def table() -> str | None:
    result = sh("nft", "list", "table", "inet", "veblock", check=False)
    return result.stdout if result.returncode == 0 else None


def default_route() -> str:
    return sh("ip", "route", "show", "default").stdout


def split_routes() -> str:
    """Половины маршрута по умолчанию: их помощник кладёт на TUN."""
    halves = (sh("ip", "route", "show", prefix).stdout for prefix in ("0.0.0.0/1", "128.0.0.0/1"))
    return "".join(halves)


def tun_is_default() -> bool:
    """Трафик идёт в TUN: обе половины маршрута по умолчанию лежат на нём."""
    halves = split_routes().splitlines()
    return len(halves) == 2 and all(f"dev {TUN}" in half for half in halves)


def uplink_is_default() -> bool:
    return (
        f"via {GATEWAY} dev uplink0" in default_route()
        and not tun_is_default()
        and f"dev {TUN}" not in default_route()
    )


def core_pids() -> list[int]:
    """Работающее ядро; короткие `xray api`, `xray version` и `xray -test` сюда не входят."""
    result = sh("pgrep", "-a", "-x", "xray", check=False)
    return [
        int(fields[0])
        for fields in map(str.split, result.stdout.splitlines())
        if fields[2:3] == ["-config"]
    ]


def kill_core() -> int:
    pids = core_pids()
    assert len(pids) == 1, f"Ожидалось одно ядро, а их {pids}"
    os.kill(pids[0], signal.SIGKILL)
    return pids[0]


# --- приложение ---


@dataclass
class Application:
    """Настоящий GUI из пакета: управляется действиями D-Bus, состояние читается из трея."""

    ids: dict[str, int] = field(default_factory=dict)
    process: subprocess.Popen | None = None

    def _as_user(self, *command: str) -> list[str]:
        uid = pwd.getpwnam(USER).pw_uid
        environment = (
            f"HOME={HOME}",
            f"DBUS_SESSION_BUS_ADDRESS={BUS}",
            f"DISPLAY={DISPLAY}",
            f"XDG_RUNTIME_DIR=/run/user/{uid}",
            "LC_ALL=C.UTF-8",
            "TENGA_SOFTWARE_RENDER=1",
            "NO_AT_BRIDGE=1",
        )
        return ["runuser", "-u", USER, "--", "env", *environment, *command]

    def seed(self, *, kill_switch: bool) -> None:
        keys = json.loads((LAB / "reality.json").read_text())
        spec = {
            "config_dir": str(CONFIG),
            "settings": {
                "proxy_mode": "tun",
                "tun_kill_switch": kill_switch,
                "tun_name": TUN,
                "dns": {
                    "provider": "custom",
                    # Не DNS сети: запросы к нему ядро намеренно шлёт напрямую, а не в туннель
                    "custom_url": f"udp://{PUBLIC_DNS}:53",
                    "use_proxy": True,
                    "intercept": True,
                },
                "monitoring": {"enabled": False},
                "app_update_enabled": False,
                "core_update_enabled": False,
                "close_to_tray": False,
            },
            "servers": [
                {
                    "name": "A",
                    "link": (
                        f"vless://{UUID}@{EXIT_A}:443?type=tcp&security=reality"
                        f"&sni={REALITY_SNI}&pbk={keys['public']}&sid={SHORT_ID}&fp=chrome"
                        "&flow=xtls-rprx-vision#A"
                    ),
                },
                {
                    "name": "B",
                    "link": f"vless://{UUID}@b.veblock.test:8080?type=tcp&security=none#B",
                },
                {
                    "name": "V",
                    "link": f"vless://{UUID}@{EXIT_B}:8080?type=tcp&security=none#V",
                    "vpn": VPN_NAME,
                },
            ],
        }
        result = subprocess.run(
            self._as_user(
                "PYTHONPATH=/usr/lib/tenga-proxy",
                "python3",
                "-B",
                str(HERE / "lab_seed.py"),
                json.dumps(spec),
            ),
            check=False,
            capture_output=True,
            text=True,
            cwd="/",
        )
        assert result.returncode == 0, f"Засев настроек: {result.stderr}"
        self.ids = json.loads(result.stdout.splitlines()[-1])

    def start(self) -> None:
        output = (RESULTS / "app-stdout.log").open("a")
        self.process = subprocess.Popen(
            self._as_user("/usr/bin/tenga-proxy"),
            stdout=output,
            stderr=subprocess.STDOUT,
            cwd="/",
        )
        wait_until(self.tooltip, "приложение на шине сессии", timeout=45, interval=0.5)

    def pid(self) -> int | None:
        result = sh("pgrep", "-f", "^/usr/bin/python3 /usr/lib/tenga-proxy/gui.py", check=False)
        pids = result.stdout.split()
        return int(pids[0]) if pids else None

    def _gdbus(self, *arguments: str, timeout: float = 15):
        return subprocess.run(
            self._as_user("gdbus", "call", "--session", "--dest", "ru.tenga.Proxy", *arguments),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd="/",
            check=False,
        )

    def action(self, name: str, parameter: str = "[]") -> None:
        result = self._gdbus(
            "--object-path", "/ru/tenga/Proxy",
            "--method", "org.gtk.Actions.Activate", name, parameter, "{}",
        )  # fmt: skip
        assert result.returncode == 0, f"Действие {name}: {result.stderr}"

    def tooltip(self) -> str | None:
        try:
            result = self._gdbus(
                "--object-path", "/StatusNotifierItem",
                "--method", "org.freedesktop.DBus.Properties.Get",
                "org.kde.StatusNotifierItem", "ToolTip",
            )  # fmt: skip
        except subprocess.TimeoutExpired:
            return None
        if result.returncode != 0:
            return None
        match = re.search(r"'Veblock: ([^']*)'", result.stdout)
        return match.group(1) if match else None

    def wait_state(self, expected: str, timeout: float = 30) -> None:
        last: list[str | None] = [None]

        def reached() -> bool:
            last[0] = self.tooltip()
            return last[0] == expected

        try:
            wait_until(reached, f"состояние «{expected}»", timeout=timeout)
        except AssertionError as error:
            raise AssertionError(f"Состояние трея: «{last[0]}»\n{error}") from None

    def connect(self, server: str, exit_address: str) -> None:
        finished = self.log_text().count(SESSION_READY)
        self.action("connect-profile", f"[<int32 {self.ids[server]}>]")
        # Сначала состояние: запрос до подключения законно ушёл бы напрямую и попал в счёт утечек
        self.wait_state(server)
        self.wait_for_exit(exit_address)
        # Трафик идёт раньше, чем заканчивается поток подключения, а пока он работает,
        # приложение отклоняет новые действия: «Подключение уже выполняется».
        wait_until(lambda: self.log_text().count(SESSION_READY) > finished, "конец подключения")
        time.sleep(0.5)

    def wait_for_exit(self, exit_address: str, timeout: float = 45) -> None:
        wait_until(
            lambda: try_get(SITE, timeout=1.5) == exit_address,
            f"трафик через {exit_address}",
            timeout=timeout,
        )

    def kill(self) -> None:
        pid = self.pid()
        if pid:
            os.kill(pid, signal.SIGKILL)
        if self.process is not None:
            try:
                self.process.wait(10)
            except subprocess.TimeoutExpired:
                pass
        wait_until(lambda: self.pid() is None, "процесс приложения завершён", timeout=10)

    def terminate(self, sig: signal.Signals = signal.SIGTERM) -> None:
        pid = self.pid()
        assert pid, "Приложение не запущено"
        os.kill(pid, sig)
        wait_until(lambda: self.pid() is None, "приложение вышло", timeout=30)

    def log_text(self) -> str:
        logs = CONFIG / "logs"
        if not logs.exists():
            return ""
        return "\n".join(
            path.read_text(encoding="utf-8", errors="replace") for path in logs.glob("*.log*")
        )


# --- подготовка один раз на всю виртуалку ---


def _write_xray_config(name: str, inbound: dict, send_through: str) -> Path:
    config = {
        "log": {"loglevel": "info"},
        # Имена сайтов (адрес пробы задержки) разрешает DNS лаборатории: системного
        # резолвера в пространстве лаборатории нет.
        "dns": {"servers": [DNS_SERVER]},
        "inbounds": [inbound],
        "outbounds": [
            {
                "protocol": "freedom",
                "sendThrough": send_through,
                # По умолчанию ядро не выпускает на служебные адреса, а TEST-NET — как раз они
                "settings": {"finalRules": [{"action": "allow"}]},
                "streamSettings": {"sockopt": {"domainStrategy": "UseIPv4"}},
            }
        ],
    }
    path = LAB / f"{name}.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def _reality_keys(xray: str) -> dict:
    # Подписи ключей зависят от версии ядра, порядок — нет: закрытый, затем открытый.
    output = sh(xray, "x25519").stdout
    values = [line.partition(":")[2].strip() for line in output.splitlines() if ":" in line]
    keys = {"private": values[0], "public": values[1]}
    (LAB / "reality.json").write_text(json.dumps(keys), encoding="utf-8")
    return keys


def _start_server_xrays(xray: str, keys: dict) -> None:
    reality = _write_xray_config(
        "server-a",
        {
            "listen": EXIT_A,
            "port": 443,
            "protocol": "vless",
            "settings": {
                "clients": [{"id": UUID, "flow": "xtls-rprx-vision"}],
                "decryption": "none",
            },
            "streamSettings": {
                "network": "tcp",
                "security": "reality",
                "realitySettings": {
                    "dest": "127.0.0.1:8443",
                    "serverNames": [REALITY_SNI],
                    "privateKey": keys["private"],
                    "shortIds": [SHORT_ID],
                },
            },
        },
        EXIT_A,
    )
    plain = _write_xray_config(
        "server-b",
        {
            "listen": EXIT_B,
            "port": 8080,
            "protocol": "vless",
            "settings": {"clients": [{"id": UUID}], "decryption": "none"},
            "streamSettings": {"network": "tcp", "security": "none"},
        },
        EXIT_B,
    )
    for config, log in ((reality, "server-a.log"), (plain, "server-b.log")):
        _spawn_in_inet(str(LAB / "lab-xray"), "run", "-c", str(config), log=log)


def _spawn_in_inet(*command: str, log: str) -> None:
    output = (RESULTS / log).open("a")
    subprocess.Popen(
        ["ip", "netns", "exec", "inet", *command],
        stdout=output,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def _build_namespace() -> None:
    sh("ip", "netns", "add", "inet")
    sh("ip", "link", "add", "uplink0", "type", "veth", "peer", "name", "lab0")
    sh("ip", "link", "set", "lab0", "netns", "inet")
    in_inet("ip", "link", "set", "lo", "up")
    for address in (EXIT_A, EXIT_B, VPN_SERVER, DNS_SERVER, SITE, PUBLIC_DNS):
        in_inet("ip", "addr", "add", f"{address}/32", "dev", "lo")
    in_inet("ip", "-6", "addr", "add", f"{SITE6}/128", "dev", "lo")
    in_inet("ip", "link", "set", "lab0", "up")
    in_inet("ip", "addr", "add", f"{GATEWAY}/24", "dev", "lab0")
    in_inet("ip", "addr", "add", f"{LAN_PEER}/24", "dev", "lab0")
    in_inet("ip", "-6", "addr", "add", "2001:db8:1::1/64", "dev", "lab0", "nodad")


def _leave_qemu_nic_for_ssh_only() -> None:
    routes = sh("ip", "-o", "-4", "route", "show", "default").stdout.split()
    if "dev" not in routes:
        return
    device = routes[routes.index("dev") + 1]
    profile = sh("nmcli", "-g", "GENERAL.CONNECTION", "device", "show", device).stdout.strip()
    assert profile, f"{device} не под NetworkManager: приложению нужен именно он"
    sh(
        "nmcli", "connection", "modify", profile,
        "ipv4.never-default", "yes", "ipv4.ignore-auto-dns", "yes", "ipv6.method", "disabled",
    )  # fmt: skip
    sh("nmcli", "connection", "up", profile)
    wait_until(lambda: not default_route().strip(), "маршрут по умолчанию QEMU убран")


def _manage_uplink() -> None:
    wait_until(
        lambda: sh("nmcli", "device", "set", "uplink0", "managed", "yes", check=False).returncode
        == 0,
        "NetworkManager увидел uplink0",
    )
    sh(
        "nmcli", "connection", "add", "type", "ethernet",
        "con-name", UPLINK_PROFILE, "ifname", "uplink0",
        "ipv4.method", "manual",
        "ipv4.addresses", f"{DIRECT}/24,{LAN_SELF}/24",
        "ipv4.gateway", GATEWAY,
        # DNS сети — роутер, как дома: в локальную сеть окно DNS пускает
        "ipv4.dns", LAN_PEER,
        "ipv4.route-metric", "600",
        "ipv6.method", "manual",
        "ipv6.addresses", f"{DIRECT6}/64",
        "ipv6.gateway", "2001:db8:1::1",
    )  # fmt: skip
    sh("nmcli", "connection", "up", UPLINK_PROFILE)


def _prepare_openvpn() -> None:
    key = LAB / "vpn.key"
    sh("openvpn", "--genkey", "secret", str(key))
    key.chmod(0o644)
    _spawn_in_inet(
        "openvpn", "--dev", "tunlab", "--dev-type", "tun",
        "--local", VPN_SERVER, "--port", "1194", "--proto", "udp",
        "--ifconfig", VPN_PEER, VPN_SELF,
        "--secret", str(key), "0", "--cipher", "AES-256-CBC",
        "--keepalive", "5", "30",
        # Новый запуск клиента приходит с другого порта; без --float сервер ждал бы старый адрес
        "--float",
        log="openvpn-server.log",
    )  # fmt: skip
    data = {
        "connection-type": "static-key",
        "remote": VPN_SERVER,
        "port": "1194",
        "static-key": str(key),
        "static-key-direction": "1",
        "local-ip": VPN_SELF,
        "remote-ip": VPN_PEER,
        "cipher": "AES-256-CBC",
    }
    sh(
        "nmcli", "connection", "add", "type", "vpn", "vpn-type", "openvpn",
        "con-name", VPN_NAME, "ifname", "*", "connection.autoconnect", "no",
        "ipv4.never-default", "yes",
        "vpn.data", ", ".join(f"{name}={value}" for name, value in data.items()),
    )  # fmt: skip


def _prepare_docker_image() -> None:
    """Образ из busybox пакета: реестр из лаборатории недоступен и не нужен."""
    rootfs = LAB / "rootfs"
    (rootfs / "bin").mkdir(parents=True, exist_ok=True)
    shutil.copy("/bin/busybox", rootfs / "bin/busybox")
    archive = subprocess.run(
        ["tar", "-C", str(rootfs), "-c", "."], check=True, capture_output=True
    ).stdout
    subprocess.run(
        ["docker", "import", "-", "lab-busybox"], input=archive, check=True, capture_output=True
    )


def _start_desktop() -> None:
    uid = pwd.getpwnam(USER).pw_uid
    runtime = Path(f"/run/user/{uid}")
    runtime.mkdir(parents=True, exist_ok=True)
    os.chown(runtime, uid, uid)
    runtime.chmod(0o700)
    for command, log in (
        (["Xvfb", DISPLAY, "-screen", "0", "1280x800x24", "-nolisten", "tcp"], "xvfb.log"),
        (["dbus-daemon", "--session", f"--address={BUS}", "--nofork"], "session-bus.log"),
    ):
        subprocess.Popen(
            ["runuser", "-u", USER, "--", *command],
            stdout=(RESULTS / log).open("a"),
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    wait_until(lambda: Path(BUS.removeprefix("unix:path=")).exists(), "шина сессии")


def set_up_once() -> None:
    LAB.mkdir(parents=True, exist_ok=True)
    (LAB / "logs").mkdir(exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    RUN.mkdir(parents=True, exist_ok=True)
    os.chmod(HERE, 0o755)
    os.chmod(HERE.parent, 0o755)

    _prepare_docker_image()
    _leave_qemu_nic_for_ssh_only()
    _build_namespace()
    _manage_uplink()

    # Своя копия ядра: `pgrep -x xray` в проверках видит только ядро приложения.
    shutil.copy(PACKAGE_XRAY, LAB / "lab-xray")
    keys = _reality_keys(str(LAB / "lab-xray"))
    cert, key = LAB / "tls.crt", LAB / "tls.key"
    sh(
        "openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
        "-nodes", "-days", "2", "-subj", f"/CN={REALITY_SNI}",
        "-keyout", str(key), "-out", str(cert),
    )  # fmt: skip
    _spawn_in_inet(
        "python3", "-B", str(HERE / "lab_servers.py"), str(LAB / "logs"), str(cert), str(key),
        log="lab-servers.log",
    )  # fmt: skip
    wait_until(lambda: try_get(SITE) == DIRECT, "сайт лаборатории напрямую", timeout=20)
    wait_until(lambda: try_get(SITE6) == DIRECT6, "сайт лаборатории по IPv6", timeout=20)
    _start_server_xrays(str(LAB / "lab-xray"), keys)
    _prepare_openvpn()
    _start_desktop()


def reset_network() -> None:
    """Вернуть машину к началу проверки, что бы ни оставила предыдущая."""
    for pid in core_pids():
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    sh("nmcli", "connection", "down", VPN_NAME, check=False, timeout=45)
    sh("nft", "delete", "table", "inet", "veblock", check=False)
    for address in (EXIT_A, EXIT_B):
        sh("ip", "route", "del", f"{address}/32", check=False)
    sh("nmcli", "connection", "up", UPLINK_PROFILE, check=False, timeout=45)
    wait_until(uplink_is_default, "маршрут по умолчанию через uplink0")
    wait_until(lambda: try_get(SITE) == DIRECT, "сайт напрямую после сброса")
    # Поднятие профиля заново запускает проверку адреса IPv6: пока она идёт, адреса ещё нет
    wait_until(lambda: try_get(SITE6) == DIRECT6, "сайт по IPv6 после сброса")
    shutil.rmtree(CONFIG, ignore_errors=True)
    clear_logs()


def save_logs(test_name: str) -> None:
    target = RESULTS / re.sub(r"[^\w.-]+", "_", test_name)
    target.mkdir(parents=True, exist_ok=True)
    source = CONFIG / "logs"
    if source.exists():
        shutil.copytree(source, target / "app", dirs_exist_ok=True)
    for name in ("echo.jsonl", "dns.jsonl"):
        path = LAB / "logs" / name
        if path.exists():
            shutil.copy(path, target / name)
    (target / "network.txt").write_text(diagnostics(), encoding="utf-8")
