from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from src.core.config import (
    DEFAULT_STATS_API_ADDR,
    DEFAULT_STATS_API_TOKEN,
    XRAY_LOG_FILE,
    find_xray_binary,
)
from src.core.geo import ASSET_ENV, asset_dir_for_core
from src.core.logging_utils import daily_file_handler
from src.core.performance import measure_time

logger = logging.getLogger("tenga.xray_manager")


def _pump_core_output(stream: IO[bytes] | None, sink: logging.Logger) -> None:
    """Copy the core's output into its log line by line until the core exits."""
    if stream is None:
        return
    with stream:
        for raw in iter(stream.readline, b""):
            sink.info(raw.decode("utf-8", errors="replace").rstrip("\n"))


@dataclass
class TrafficStats:
    """Traffic statistics."""

    upload: int = 0
    download: int = 0


class XrayManager:
    """
    Management of xray-core via subprocess + Stats API.

    Provides:
    - Start/stop xray-core as subprocess
    - Monitoring via Stats API
    - Traffic statistics retrieval
    """

    # Служебные каналы в счёт трафика не идут: direct — мимо прокси, vpn —
    # через туннель, block — в никуда, dns-out — перехваченные DNS-запросы, api —
    # сам опрос статистики, остальные три — резолвинг DNS.
    # Список отражает теги, которые заводит `src/core/config_builder.py`.
    _SERVICE_TAGS = frozenset(
        {"direct", "vpn", "block", "dns-out", "api", "main-dns", "local-dns", "vpn-dns"}
    )

    def __init__(
        self,
        binary_path: str | None = None,
        stats_api_addr: str = DEFAULT_STATS_API_ADDR,
        stats_api_token: str = DEFAULT_STATS_API_TOKEN,
    ):
        """
        Initialize manager.

        Args:
            binary_path: Path to xray binary. If None, automatic search will be performed
                        (first core/bin/xray, then system)
            stats_api_addr: Stats API address (host:port for HTTP or host:port for gRPC)
            stats_api_token: Token for Stats API authentication
        """
        if binary_path is None:
            binary_path = find_xray_binary()
            if binary_path is None:
                raise RuntimeError(
                    "xray-core not found. Install xray-core and ensure "
                    "it is available in PATH or in core/bin/ directory"
                )

        self._binary_path = binary_path
        self._stats_api_addr = stats_api_addr
        self._stats_api_token = stats_api_token
        self._process: subprocess.Popen | None = None
        self._config_file: Path | None = None
        self._on_stop_callback: Callable[[], None] | None = None
        self._core_log: logging.Logger | None = None
        self._log_pump: threading.Thread | None = None

        # Cache xray version on initialization
        self._version_cache = self._fetch_version()

    def _core_env(self) -> dict[str, str] | None:
        """Окружение процесса ядра; None — унаследовать как есть.

        Геобазы ядро ищет рядом с собой. Если их там нет (установка, сделанная до
        появления баз в комплекте), называем каталог комплекта: правила с
        `geosite:`/`geoip:` иначе уронили бы запуск.
        """
        asset_dir = asset_dir_for_core(self._binary_path)
        if asset_dir is None:
            return None
        return {**os.environ, ASSET_ENV: str(asset_dir)}

    def _wait_for_process_ready(self, timeout: float = 2.0) -> bool:
        """Wait for xray process to be ready.

        Uses active polling instead of blocking sleep.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            True if process is ready, False if it failed
        """
        start = time.time()
        while time.time() - start < timeout:
            if self._process is None:
                return False

            # Check if process exited
            if self._process.poll() is not None:
                return False

            # Small sleep to avoid busy waiting
            time.sleep(0.1)

        # Process is still running after timeout
        return True

    @property
    def binary_path(self) -> str:
        """Path to xray binary."""
        return self._binary_path

    @property
    def is_running(self) -> bool:
        """Check if process is running."""
        if self._process is None:
            return False
        return self._process.poll() is None

    def set_on_stop_callback(self, callback: Callable[[], None] | None) -> None:
        """Set callback for process stop."""
        self._on_stop_callback = callback

    def _inject_stats_api(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        Add stats and api sections to configuration.

        Args:
            config: Original xray-core configuration

        Returns:
            Configuration with added stats and api
        """
        config = config.copy()

        # Enable stats
        if "stats" not in config:
            config["stats"] = {}

        # Без счётчиков в policy ядро не ведёт статистику вовсе: секции stats и
        # api сами по себе лишь открывают доступ к тому, что уже посчитано.
        # Вложенные словари копируются явно: config.copy() поверхностный, и
        # правка на месте протекла бы в конфигурацию вызывающего.
        policy = dict(config.get("policy") or {})
        system = dict(policy.get("system") or {})
        system["statsOutboundUplink"] = True
        system["statsOutboundDownlink"] = True
        policy["system"] = system
        config["policy"] = policy

        # Enable API service
        if "api" not in config:
            config["api"] = {
                "tag": "api",
                "services": ["StatsService"],
            }

        # Add API inbound if not present
        api_inbound_exists = False
        if "inbounds" in config:
            for inbound in config["inbounds"]:
                if inbound.get("tag") == "api":
                    api_inbound_exists = True
                    break

        if not api_inbound_exists:
            if "inbounds" not in config:
                config["inbounds"] = []

            # Parse address and port from stats_api_addr
            addr_parts = self._stats_api_addr.split(":")
            api_host = addr_parts[0] if len(addr_parts) > 0 else "127.0.0.1"
            api_port = int(addr_parts[1]) if len(addr_parts) > 1 else 10085

            config["inbounds"].append(
                {
                    "tag": "api",
                    "listen": api_host,
                    "port": api_port,
                    "protocol": "dokodemo-door",
                    "settings": {
                        "address": "127.0.0.1",
                    },
                }
            )

        # Add API outbound if not present
        api_outbound_exists = False
        if "outbounds" in config:
            for outbound in config["outbounds"]:
                if outbound.get("tag") == "api":
                    api_outbound_exists = True
                    break

        if not api_outbound_exists:
            if "outbounds" not in config:
                config["outbounds"] = []

            config["outbounds"].append(
                {
                    "protocol": "freedom",
                    "tag": "api",
                }
            )

        # Add routing rule for API if not present
        if "routing" not in config:
            config["routing"] = {"rules": []}

        api_rule_exists = False
        for rule in config["routing"]["rules"]:
            if rule.get("inboundTag") == ["api"]:
                api_rule_exists = True
                break

        if not api_rule_exists:
            config["routing"]["rules"].insert(
                0,
                {
                    "type": "field",
                    "inboundTag": ["api"],
                    "outboundTag": "api",
                },
            )

        return config

    @measure_time("XrayManager.start")
    def start(self, config: dict[str, Any]) -> tuple[bool, str]:
        """
        Start xray-core with configuration.

        Args:
            config: xray-core configuration (dict)

        Returns:
            (success, error_message)
        """
        if self.is_running:
            self.stop()

        config = self._inject_stats_api(config)

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".json",
                delete=False,
                encoding="utf-8",
            ) as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
                self._config_file = Path(f.name)
        except Exception as e:
            return False, f"Error writing configuration: {e}"

        # Start process
        try:
            # Ядро пишет в pipe, а не в файл: файл, открытый работающим
            # процессом, нельзя повернуть в полночь, и лог рос бы без предела.
            self._process = subprocess.Popen(
                [self._binary_path, "-config", str(self._config_file)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=self._core_env(),
            )
            self._log_pump = threading.Thread(
                target=_pump_core_output,
                args=(self._process.stdout, self._core_logger()),
                name="xray-log",
                daemon=True,
            )
            self._log_pump.start()

            if not self._wait_for_process_ready(timeout=2.0):
                self._cleanup()
                return False, f"xray-core exited with error: see log file: {XRAY_LOG_FILE}"

            # Check that Stats API is available (optional - xray may not have HTTP API enabled)
            # We'll just check if process is running
            logger.info("xray-core запущен, PID: %s", self._process.pid)
            return True, ""

        except FileNotFoundError:
            self._cleanup()
            return False, f"Binary not found: {self._binary_path}"
        except Exception as e:
            self._cleanup()
            return False, f"Startup error: {e}"

    def _core_logger(self) -> logging.Logger:
        """Logger for the core's own output, written as is to the daily xray log.

        Логгер не регистрируется в `logging.getLogger`: `setup_logging`
        включает распространение всем зарегистрированным, и вывод ядра
        продублировался бы в лог приложения.
        """
        if self._core_log is None:
            handler = daily_file_handler(XRAY_LOG_FILE)
            # Строки ядра уже несут своё время и уровень.
            handler.setFormatter(logging.Formatter("%(message)s"))
            core_log = logging.Logger("tenga.xray.core", logging.INFO)
            core_log.propagate = False
            core_log.addHandler(handler)
            self._core_log = core_log
        return self._core_log

    def reload_config(self, config: dict[str, Any]) -> tuple[bool, str]:
        """
        Reload xray-core configuration without stopping the process.

        Args:
            config: New xray-core configuration

        Returns:
            (success, error_message)
        """
        if not self.is_running:
            return self.start(config)

        stop_success, stop_error = self.stop()
        if not stop_success:
            logger.warning("Error stopping xray-core during reload: %s", stop_error)

        return self.start(config)

    def stop(self) -> tuple[bool, str]:
        """
        Stop xray-core.

        Returns:
            (success, error_message)
        """
        if self._process is None:
            return True, ""

        try:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)

            logger.info("xray-core stopped")

        except Exception as e:
            logger.warning("Error stopping xray-core: %s", e)

        self._cleanup()

        if self._on_stop_callback:
            try:
                self._on_stop_callback()
            except Exception as e:
                logger.warning("Error in on_stop callback: %s", e)

        return True, ""

    def _cleanup(self) -> None:
        """Clean up resources."""
        self._process = None

        if self._log_pump is not None:
            # Ядро уже завершилось: дожидаемся последних строк, среди них
            # бывает причина отказа.
            self._log_pump.join(timeout=1)
            self._log_pump = None

        if self._config_file and self._config_file.exists():
            try:
                self._config_file.unlink()
            except Exception:
                pass
            self._config_file = None

    def _fetch_version(self) -> dict[str, Any] | None:
        """Fetch xray-core version information.

        Returns:
            Version dict or None if failed
        """
        try:
            result = subprocess.run(
                [self._binary_path, "version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                version_str = result.stdout.strip()
                parts = version_str.split()
                version = parts[1] if len(parts) > 1 else version_str
                return {"version": version, "full": version_str}
        except Exception as e:
            logger.debug("_fetch_version error: %s", e)
        return None

    def get_version(self) -> dict[str, Any] | None:
        """Get xray-core version (cached)."""
        return self._version_cache

    def _check_process_alive(self) -> bool:
        """Check if xray-core process is alive.

        Faster alternative to get_version() for status checks.

        Returns:
            True if process is running
        """
        return self._process is not None and self._process.poll() is None

    def _query_stats(self) -> dict[str, int]:
        """Read every counter the core keeps.

        Статистика снимается вызовом самого бинарника: Stats API ядра работает
        только по gRPC, а генерировать protobuf-стабы ради двух чисел
        избыточно — вызов укладывается в 25 мс.

        Опрос идёт по таймеру, поэтому любая неудача — это пустой ответ, а не
        исключение: ядро могло остановиться между двумя тиками.
        """
        try:
            result = subprocess.run(
                [
                    self._binary_path,
                    "api",
                    "statsquery",
                    f"--server={self._stats_api_addr}",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as e:
            logger.debug("Stats query failed: %s", e)
            return {}

        if result.returncode != 0:
            logger.debug("Stats query returned %s: %s", result.returncode, result.stderr)
            return {}

        try:
            answer = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as e:
            logger.debug("Could not parse the stats answer: %s", e)
            return {}

        # У обнулённого счётчика ключа value нет вовсе.
        return {
            item["name"]: int(item.get("value", 0))
            for item in answer.get("stat", [])
            if isinstance(item, dict) and "name" in item
        }

    def get_traffic(self) -> TrafficStats:
        """Traffic totals of every proxy outbound.

        Счётчик именуется по тегу outbound, а тегом служит имя профиля, а не
        строка `proxy`: её `config_builder` подставляет только безымянному
        профилю. Поэтому складываются все каналы, кроме служебных, — имя
        профиля заранее неизвестно, а служебные теги известны наперечёт.
        """
        upload = download = 0
        for name, value in self._query_stats().items():
            parts = name.split(">>>")
            if len(parts) != 4 or parts[0] != "outbound":
                continue
            if parts[1] in self._SERVICE_TAGS:
                continue
            if parts[3] == "uplink":
                upload += value
            elif parts[3] == "downlink":
                download += value
        return TrafficStats(upload=upload, download=download)

    def __enter__(self) -> XrayManager:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.stop()
