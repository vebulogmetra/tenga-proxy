"""Пакетный замер задержки: один процесс ядра на весь набор профилей.

У каждого профиля свой HTTP-inbound `probe-in-N` на 127.0.0.1 и свой outbound
`proxy-N`; правило по `inboundTag` связывает пару. Рабочий билдер конфигурации
здесь не участвует: замеру не нужны ни пользовательские правила, ни DNS, ни TUN.
При активном TUN пробы получают `ProbeRoute` и выходят мимо туннеля.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import socket
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

from src.core.http_probe import (
    LOOPBACK,
    ProbeCredentials,
    ProbeEndpoint,
    build_probe_inbound,
    probe_latency,
)
from src.core.platform_info import no_window
from src.core.probe_result import PROBE_TIMEOUT_SECONDS, ProbeFailure, ProbeResult, clip_detail
from src.core.sockopt import bind_to_interface, is_ip, is_loopback, mark_socket, resolve_in_core
from src.core.transport_tweaks import apply_transport_tweaks

if TYPE_CHECKING:
    from src.db.data_store import DataStore
    from src.db.profiles import ProfileEntry

logger = logging.getLogger("tenga.core.batch_probe")

PROBE_INBOUND_PREFIX = "probe-in-"
PROBE_OUTBOUND_PREFIX = "proxy-"
CORE_TEST_TIMEOUT_SECONDS = 60

LATENCY_TEST_URL = "http://www.google.com/generate_204"
DEFAULT_MAX_WORKERS = 16
# Ядро поднимает полторы тысячи inbound'ов за доли секунды; предел нужен только
# затем, чтобы свободных портов хватило при любом числе профилей.
MAX_BATCH_SIZE = 500
START_ATTEMPTS = 3
START_TIMEOUT_SECONDS = 5.0

DIRECT_TAG = "direct"
PROBE_DNS_TAG = "probe-dns"

ResultFn = Callable[[int, ProbeResult], None]
# Хвост вывода ядра, из которого берётся причина отказа.
OUTPUT_TAIL_BYTES = 4096


@dataclass(frozen=True)
class ProbeRoute:
    """Путь пробы мимо туннеля: физический интерфейс, метка и DNS сети.

    Без него пробы ушли бы в TUN, то есть через текущий сервер. Метка нужна только на
    Linux: таблица `inet veblock` пропускает лишь помеченные сокеты.
    """

    interface: str
    mark: int | None = None
    dns_servers: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProbeTarget:
    """Профиль, готовый к замеру: его id и собранный outbound."""

    profile_id: int
    outbound: dict[str, Any]
    # Адрес сервера из профиля: в outbound он лежит по-разному у каждого протокола.
    server: str = ""


def _route_past_tunnel(outbound: dict[str, Any], server: str, route: ProbeRoute) -> None:
    loopback = is_loopback(server)
    if not loopback:
        bind_to_interface(outbound, route.interface)
    if route.mark is not None:
        mark_socket(outbound, route.mark)
    if server and not loopback and not is_ip(server):
        resolve_in_core(outbound)


def build_probe_outbound_or_error(
    profile: ProfileEntry, settings: DataStore
) -> tuple[dict[str, Any] | None, str]:
    """Outbound профиля с теми же надстройками транспорта, что и в рабочей сессии.

    Без outbound'а — текст, почему профиль не собрался: в пакет он не попадает
    и сразу получает `INVALID_CONFIG`.
    """
    try:
        result = profile.bean.build_core_obj_xray()
    except Exception as e:
        logger.warning("Profile %s cannot be built for probing: %s", profile.id, e)
        return None, str(e) or type(e).__name__

    if result.get("error") or not result.get("outbound"):
        logger.info("Profile %s skipped by probe: %s", profile.id, result.get("error"))
        return None, str(result.get("error") or "нет outbound")

    outbound = result["outbound"]
    apply_transport_tweaks(outbound, settings)
    return outbound, ""


def build_probe_outbound(profile: ProfileEntry, settings: DataStore) -> dict[str, Any] | None:
    """Outbound профиля для замера; None — профиль собрать нельзя."""
    return build_probe_outbound_or_error(profile, settings)[0]


def build_batch_probe_config(
    targets: Sequence[ProbeTarget],
    ports: Sequence[int],
    credentials: ProbeCredentials,
    *,
    log_level: str = "warning",
    route: ProbeRoute | None = None,
) -> dict[str, Any]:
    """Конфиг ядра для замера: N inbound'ов, N outbound'ов, N правил."""
    if len(ports) != len(targets):
        raise ValueError(f"портов {len(ports)}, а профилей {len(targets)}")

    inbounds: list[dict[str, Any]] = []
    outbounds: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []

    for index, (target, port) in enumerate(zip(targets, ports, strict=True), start=1):
        inbound_tag = f"{PROBE_INBOUND_PREFIX}{index}"
        outbound_tag = f"{PROBE_OUTBOUND_PREFIX}{index}"

        inbounds.append(build_probe_inbound(inbound_tag, ProbeEndpoint(port, credentials)))

        outbound = copy.deepcopy(target.outbound)
        outbound["tag"] = outbound_tag
        if route is not None:
            _route_past_tunnel(outbound, target.server, route)
        outbounds.append(outbound)

        rules.append({"type": "field", "inboundTag": [inbound_tag], "outboundTag": outbound_tag})

    config: dict[str, Any] = {
        "log": {"loglevel": log_level},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": {"rules": rules},
    }
    if route is not None:
        # Запросы DNS-модуля ядра: имена серверов спрашиваются у DNS сети мимо туннеля.
        direct: dict[str, Any] = {"protocol": "freedom", "tag": DIRECT_TAG}
        _route_past_tunnel(direct, "", route)
        outbounds.append(direct)
        if route.dns_servers:
            config["dns"] = {
                "servers": list(route.dns_servers),
                "queryStrategy": "UseIPv4",
                "tag": PROBE_DNS_TAG,
            }
            # Без правила запросы ушли бы в первый outbound, то есть в proxy-1.
            rules.insert(
                0, {"type": "field", "inboundTag": [PROBE_DNS_TAG], "outboundTag": DIRECT_TAG}
            )
    return config


def _write_config(config: dict[str, Any]) -> Path:
    # NamedTemporaryFile создаёт файл с правами 0600: в конфиге лежат ключи
    # профилей и учётные данные inbound'ов.
    with tempfile.NamedTemporaryFile(
        mode="w", prefix="tenga-probe-", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(config, f, ensure_ascii=False)
        return Path(f.name)


# Звенья ошибки ядра, которые говорят о нашем конфиге, а не о сервере.
_NOISE_SEGMENT = re.compile(
    r"Failed to start|failed to load config files|with tag " + PROBE_OUTBOUND_PREFIX
)


def core_error_message(output: str | bytes) -> str:
    """Последняя содержательная строка вывода ядра без пути к конфигу и тега.

    Ядро склеивает причину через « > » от внешнего звена к внутреннему; звенья с
    временным файлом и тегом `proxy-N` пользователю ничего не говорят.
    """
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return ""
    segments = [part for part in lines[-1].split(" > ") if not _NOISE_SEGMENT.search(part)]
    return clip_detail(" > ".join(segments) or lines[-1])


def core_check(binary_path: str, config: dict[str, Any]) -> tuple[bool, str]:
    """Спросить у ядра, примет ли оно конфиг (`xray -test`), и почему нет.

    Портов не занимает.
    """
    path = _write_config(config)
    try:
        result = subprocess.run(
            [binary_path, "-test", "-config", str(path)],
            capture_output=True,
            timeout=CORE_TEST_TIMEOUT_SECONDS,
            check=False,
            **no_window(),
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("Core could not check the probe config: %s", e)
        return False, clip_detail(str(e))
    finally:
        path.unlink(missing_ok=True)

    if result.returncode == 0:
        return True, ""
    return False, core_error_message((result.stdout or b"") + (result.stderr or b""))


def core_accepts(binary_path: str, config: dict[str, Any]) -> bool:
    """Примет ли ядро конфиг (`xray -test`)."""
    return core_check(binary_path, config)[0]


def split_accepted(
    targets: Sequence[ProbeTarget],
    accepts: Callable[[Sequence[ProbeTarget]], bool],
) -> tuple[list[ProbeTarget], list[ProbeTarget]]:
    """Разделить профили на принятые ядром и отвергнутые, сохраняя порядок.

    Ядро отвергает конфиг целиком из-за одного outbound'а, а сборка такие
    профили пропускает: ключ REALITY не той длины, неизвестный fingerprint,
    неверный UUID. Пакет делится пополам, пока виновные не останутся по одному:
    на один плохой профиль уходит около 2·log2(N) проверок вместо N.
    """
    batch = list(targets)
    if not batch:
        return [], []
    if accepts(batch):
        return batch, []
    if len(batch) == 1:
        return [], batch

    middle = len(batch) // 2
    left_accepted, left_rejected = split_accepted(batch[:middle], accepts)
    right_accepted, right_rejected = split_accepted(batch[middle:], accepts)
    return left_accepted + right_accepted, left_rejected + right_rejected


def reserve_ports(count: int, host: str = LOOPBACK) -> list[int]:
    """Свободные TCP-порты, все разные: сокеты закрываются только в конце."""
    sockets: list[socket.socket] = []
    try:
        for _ in range(count):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sockets.append(sock)
            sock.bind((host, 0))
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def _port_open(port: int) -> bool:
    try:
        socket.create_connection((LOOPBACK, port), timeout=0.2).close()
    except OSError:
        return False
    return True


class BatchCore:
    """Временный процесс ядра на один замер.

    Отдельно от `XrayManager`: тот добавляет в конфиг Stats API на общем порту
    10085. Ядро открывает порты с SO_REUSEPORT, поэтому второй процесс молча
    делил бы этот порт с рабочим и перехватывал часть запросов статистики.
    """

    def __init__(self, binary_path: str, config: dict[str, Any]) -> None:
        self._binary_path = binary_path
        self._config = config
        self._config_path: Path | None = None
        self._process: subprocess.Popen | None = None
        self._output: IO[bytes] | None = None

    def __enter__(self) -> BatchCore:
        self._config_path = _write_config(self._config)
        # Вывод уходит в файл, а не в pipe: непрочитанный pipe переполнился бы
        # предупреждениями о мёртвых серверах и остановил бы ядро посреди замера.
        self._output = tempfile.TemporaryFile()
        try:
            self._process = subprocess.Popen(
                [self._binary_path, "run", "-c", str(self._config_path)],
                stdout=self._output,
                stderr=subprocess.STDOUT,
                **no_window(),
            )
        except OSError as e:
            logger.warning("Probe core could not be started: %s", e)
        return self

    def wait_ready(self, ports: Sequence[int], timeout: float = START_TIMEOUT_SECONDS) -> bool:
        """Дождаться, пока ядро откроет inbound'ы. False — не запустилось."""
        if self._process is None or not ports:
            return False

        # Проверяется каждый порт: порядок запуска inbound'ов ядро не обещает,
        # и проба в ещё не открытый порт записала бы живому профилю -1.
        pending = set(ports)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                return False
            pending = {port for port in pending if not _port_open(port)}
            if not pending:
                return True
            time.sleep(0.05)
        return False

    def output_tail(self) -> str:
        """Что ядро успело написать: из этого видно, почему оно не запустилось."""
        if self._output is None:
            return ""
        try:
            self._output.flush()
            size = self._output.seek(0, 2)
            self._output.seek(max(0, size - OUTPUT_TAIL_BYTES))
            return core_error_message(self._output.read())
        except (OSError, ValueError):
            return ""

    def __exit__(self, *_exc: object) -> None:
        if self._process is not None:
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=2)
            self._process = None
        if self._output is not None:
            self._output.close()
            self._output = None
        if self._config_path is not None:
            self._config_path.unlink(missing_ok=True)
            self._config_path = None


def measure_targets(
    targets: Sequence[ProbeTarget],
    ports: Sequence[int],
    credentials: ProbeCredentials,
    *,
    url: str,
    on_result: ResultFn,
    max_workers: int = DEFAULT_MAX_WORKERS,
    timeout: float = PROBE_TIMEOUT_SECONDS,
    probes: int = 3,
) -> None:
    """Замерить профили параллельно, отдавая каждый результат сразу по готовности."""

    def measure(port: int) -> ProbeResult:
        endpoint = ProbeEndpoint(port, credentials)
        return probe_latency(endpoint, url, timeout=timeout, probes=probes)

    workers = max(1, min(max_workers, len(targets)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tenga-probe") as pool:
        futures = {
            pool.submit(measure, port): target.profile_id
            for target, port in zip(targets, ports, strict=True)
        }
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as e:
                logger.warning("Probe of profile %s failed: %s", futures[future], e)
                result = ProbeResult.failed(ProbeFailure.UNREACHABLE, f"{type(e).__name__}: {e}")
            on_result(futures[future], result)


def _probe_batch(
    targets: Sequence[ProbeTarget],
    *,
    binary_path: str,
    on_result: ResultFn,
    url: str,
    max_workers: int,
    timeout: float,
    probes: int,
    route: ProbeRoute | None,
) -> None:
    credentials = ProbeCredentials.generate()
    # Причина отказа одиночного профиля: после деления пополам она его собственная.
    reasons: dict[int, str] = {}

    def accepts(chunk: Sequence[ProbeTarget]) -> bool:
        # `-test` портов не открывает, поэтому настоящие здесь не нужны.
        ports = range(1024, 1024 + len(chunk))
        ok, message = core_check(
            binary_path, build_batch_probe_config(chunk, ports, credentials, route=route)
        )
        if not ok and len(chunk) == 1:
            reasons[chunk[0].profile_id] = message
        return ok

    accepted, rejected = split_accepted(targets, accepts)
    for target in rejected:
        logger.info("Profile %s rejected by the core, not probed", target.profile_id)
        on_result(
            target.profile_id,
            ProbeResult.failed(ProbeFailure.REJECTED, reasons.get(target.profile_id, "")),
        )
    if not accepted:
        return

    core_output = ""
    for attempt in range(1, START_ATTEMPTS + 1):
        ports = reserve_ports(len(accepted))
        config = build_batch_probe_config(accepted, ports, credentials, route=route)
        with BatchCore(binary_path, config) as core:
            if not core.wait_ready(ports):
                logger.warning("Probe core did not start (attempt %d/%d)", attempt, START_ATTEMPTS)
                core_output = core.output_tail() or core_output
                continue
            measure_targets(
                accepted,
                ports,
                credentials,
                url=url,
                on_result=on_result,
                max_workers=max_workers,
                timeout=timeout,
                probes=probes,
            )
            return

    failure = ProbeResult.failed(ProbeFailure.CORE_FAILED, core_output)
    for target in accepted:
        on_result(target.profile_id, failure)


def probe_targets(
    targets: Sequence[ProbeTarget],
    *,
    binary_path: str,
    on_result: ResultFn,
    url: str = LATENCY_TEST_URL,
    max_workers: int = DEFAULT_MAX_WORKERS,
    timeout: float = PROBE_TIMEOUT_SECONDS,
    probes: int = 3,
    route: ProbeRoute | None = None,
) -> None:
    """Замерить готовые outbound'ы. Каждый профиль получает ровно один результат."""
    for start in range(0, len(targets), MAX_BATCH_SIZE):
        _probe_batch(
            targets[start : start + MAX_BATCH_SIZE],
            binary_path=binary_path,
            on_result=on_result,
            url=url,
            max_workers=max_workers,
            timeout=timeout,
            probes=probes,
            route=route,
        )


def probe_profiles(
    profiles: Iterable[ProfileEntry],
    *,
    settings: DataStore,
    binary_path: str,
    on_result: ResultFn,
    route: ProbeRoute | None = None,
    **options: Any,
) -> None:
    """Замерить задержку профилей одним процессом ядра.

    `on_result(profile_id, result)` вызывается по мере готовности, из потока
    вызывающего; у отказа в `ProbeResult` названа причина.
    """
    targets: list[ProbeTarget] = []
    for profile in profiles:
        outbound, error = build_probe_outbound_or_error(profile, settings)
        if outbound is None:
            on_result(profile.id, ProbeResult.failed(ProbeFailure.INVALID_CONFIG, error))
            continue
        targets.append(ProbeTarget(profile.id, outbound, server=profile.bean.server_address))

    if targets:
        probe_targets(targets, binary_path=binary_path, on_result=on_result, route=route, **options)
