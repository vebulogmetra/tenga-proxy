"""Пакетный замер задержки: один процесс ядра на весь набор профилей.

У каждого профиля свой HTTP-inbound `probe-in-N` на 127.0.0.1 и свой outbound
`proxy-N`; правило по `inboundTag` связывает пару. Рабочий билдер конфигурации
здесь не участвует: замеру не нужны ни пользовательские правила, ни DNS, ни TUN.
"""

from __future__ import annotations

import copy
import json
import logging
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
    measure_latency,
)
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

ResultFn = Callable[[int, int], None]


@dataclass(frozen=True)
class ProbeTarget:
    """Профиль, готовый к замеру: его id и собранный outbound."""

    profile_id: int
    outbound: dict[str, Any]


def build_probe_outbound(profile: ProfileEntry, settings: DataStore) -> dict[str, Any] | None:
    """Outbound профиля с теми же надстройками транспорта, что и в рабочей сессии.

    None — профиль собрать нельзя: в пакет он не попадает и сразу получает -1.
    """
    try:
        result = profile.bean.build_core_obj_xray()
    except Exception as e:
        logger.warning("Profile %s cannot be built for probing: %s", profile.id, e)
        return None

    if result.get("error") or not result.get("outbound"):
        logger.info("Profile %s skipped by probe: %s", profile.id, result.get("error"))
        return None

    outbound = result["outbound"]
    apply_transport_tweaks(outbound, settings)
    return outbound


def build_batch_probe_config(
    targets: Sequence[ProbeTarget],
    ports: Sequence[int],
    credentials: ProbeCredentials,
    *,
    log_level: str = "warning",
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
        outbounds.append(outbound)

        rules.append({"type": "field", "inboundTag": [inbound_tag], "outboundTag": outbound_tag})

    return {
        "log": {"loglevel": log_level},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": {"rules": rules},
    }


def _write_config(config: dict[str, Any]) -> Path:
    # NamedTemporaryFile создаёт файл с правами 0600: в конфиге лежат ключи
    # профилей и учётные данные inbound'ов.
    with tempfile.NamedTemporaryFile(
        mode="w", prefix="tenga-probe-", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(config, f, ensure_ascii=False)
        return Path(f.name)


def core_accepts(binary_path: str, config: dict[str, Any]) -> bool:
    """Спросить у ядра, примет ли оно конфиг (`xray -test`). Портов не занимает."""
    path = _write_config(config)
    try:
        result = subprocess.run(
            [binary_path, "-test", "-config", str(path)],
            capture_output=True,
            timeout=CORE_TEST_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("Core could not check the probe config: %s", e)
        return False
    finally:
        path.unlink(missing_ok=True)

    return result.returncode == 0


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
    timeout: float = 3.0,
    probes: int = 3,
) -> None:
    """Замерить профили параллельно, отдавая каждый результат сразу по готовности."""

    def measure(port: int) -> int:
        endpoint = ProbeEndpoint(port, credentials)
        return measure_latency(endpoint, url, timeout=timeout, probes=probes)

    workers = max(1, min(max_workers, len(targets)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tenga-probe") as pool:
        futures = {
            pool.submit(measure, port): target.profile_id
            for target, port in zip(targets, ports, strict=True)
        }
        for future in as_completed(futures):
            try:
                latency = int(future.result())
            except Exception as e:
                logger.warning("Probe of profile %s failed: %s", futures[future], e)
                latency = -1
            on_result(futures[future], latency)


def _probe_batch(
    targets: Sequence[ProbeTarget],
    *,
    binary_path: str,
    on_result: ResultFn,
    url: str,
    max_workers: int,
    timeout: float,
    probes: int,
) -> None:
    credentials = ProbeCredentials.generate()

    def accepts(chunk: Sequence[ProbeTarget]) -> bool:
        # `-test` портов не открывает, поэтому настоящие здесь не нужны.
        ports = range(1024, 1024 + len(chunk))
        return core_accepts(binary_path, build_batch_probe_config(chunk, ports, credentials))

    accepted, rejected = split_accepted(targets, accepts)
    for target in rejected:
        logger.info("Profile %s rejected by the core, not probed", target.profile_id)
        on_result(target.profile_id, -1)
    if not accepted:
        return

    for attempt in range(1, START_ATTEMPTS + 1):
        ports = reserve_ports(len(accepted))
        config = build_batch_probe_config(accepted, ports, credentials)
        with BatchCore(binary_path, config) as core:
            if not core.wait_ready(ports):
                logger.warning("Probe core did not start (attempt %d/%d)", attempt, START_ATTEMPTS)
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

    for target in accepted:
        on_result(target.profile_id, -1)


def probe_targets(
    targets: Sequence[ProbeTarget],
    *,
    binary_path: str,
    on_result: ResultFn,
    url: str = LATENCY_TEST_URL,
    max_workers: int = DEFAULT_MAX_WORKERS,
    timeout: float = 3.0,
    probes: int = 3,
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
        )


def probe_profiles(
    profiles: Iterable[ProfileEntry],
    *,
    settings: DataStore,
    binary_path: str,
    on_result: ResultFn,
    **options: Any,
) -> None:
    """Замерить задержку профилей одним процессом ядра.

    `on_result(profile_id, latency_ms)` вызывается по мере готовности, из
    потока вызывающего; -1 — профиль не собрался, отвергнут ядром или не ответил.
    """
    targets: list[ProbeTarget] = []
    for profile in profiles:
        outbound = build_probe_outbound(profile, settings)
        if outbound is None:
            on_result(profile.id, -1)
            continue
        targets.append(ProbeTarget(profile.id, outbound))

    if targets:
        probe_targets(targets, binary_path=binary_path, on_result=on_result, **options)
