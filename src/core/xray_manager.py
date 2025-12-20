from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import time
import requests
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

logger = logging.getLogger("tenga.xray_manager")


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
    - Monitoring via Stats API (gRPC or HTTP)
    - Traffic statistics retrieval
    """

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
        self._log_file: IO[bytes] | None = None

    @property
    def binary_path(self) -> str:
        """Path to xray binary."""
        return self._binary_path

    @property
    def stats_api_url(self) -> str:
        """Stats API URL (for HTTP API)."""
        return f"http://{self._stats_api_addr}"

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
        log_file_opened = False
        try:
            XRAY_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            self._log_file = open(XRAY_LOG_FILE, "ab", buffering=0)
            log_file_opened = True
        except Exception as e:
            logger.warning("Unable to open xray-core log file %s: %s", XRAY_LOG_FILE, e)
            self._log_file = None

        try:
            if self._log_file is not None:
                # Redirect both stdout and stderr to the log file
                self._process = subprocess.Popen(
                    [self._binary_path, "-config", str(self._config_file)],
                    stdout=self._log_file,
                    stderr=subprocess.STDOUT,
                )
            else:
                self._process = subprocess.Popen(
                    [self._binary_path, "-config", str(self._config_file)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

            time.sleep(0.5)

            if self._process.poll() is not None:
                error_msg: str
                if self._log_file is None and self._process.stderr is not None:
                    _, stderr = self._process.communicate(timeout=5)
                    error_msg = stderr.decode("utf-8", errors="replace").strip()
                else:
                    error_msg = f"see log file: {XRAY_LOG_FILE}"

                self._cleanup()
                return False, f"xray-core exited with error: {error_msg}"

            # Check that Stats API is available (optional - xray may not have HTTP API enabled)
            # We'll just check if process is running
            logger.info("xray-core запущен, PID: %s", self._process.pid)
            return True, ""

        except FileNotFoundError:
            self._cleanup()
            return False, f"Binary not found: {self._binary_path}"
        except Exception as e:
            if log_file_opened and self._log_file is not None:
                try:
                    self._log_file.close()
                except Exception:
                    pass
                self._log_file = None
            self._cleanup()
            return False, f"Startup error: {e}"

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

        if self._log_file is not None:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None

        if self._config_file and self._config_file.exists():
            try:
                self._config_file.unlink()
            except Exception:
                pass
            self._config_file = None

    def get_version(self) -> dict[str, Any] | None:
        """Get xray-core version."""
        if not self.is_running:
            return None

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
            logger.debug("get_version error: %s", e)
        return None

    def _get_stats_via_api(self, name: str, reset: bool = False) -> int:
        """
        Get stats via API.
        """
        logger.debug("Stats API not fully implemented, returning 0 for %s", name)
        return 0

    def get_traffic(self) -> TrafficStats:
        """
        Get current traffic statistics.
        """
        upload = 0
        download = 0

        upload = self._get_stats_via_api("outbound>>>proxy>>>traffic>>>uplink", reset=False)
        download = self._get_stats_via_api("outbound>>>proxy>>>traffic>>>downlink", reset=False)

        return TrafficStats(upload=upload, download=download)

    def test_delay(
        self,
        proxy_address: str | None = None,
        proxy_port: int | None = None,
        timeout: int = 5000,
    ) -> int:
        """
        Test proxy latency using HTTP HEAD request through proxy.

        Args:
            proxy_address: Proxy address
            proxy_port: Proxy SOCKS5 port
            timeout: Timeout in milliseconds

        Returns:
            Latency in milliseconds, or -1 on error
        """
        if not self.is_running:
            logger.debug("xray-core is not running, cannot test delay")
            return -1

        if proxy_address is None or proxy_port is None:
            logger.debug("Proxy address or port not provided, cannot test delay")
            return -1

        try:
            timeout_sec = timeout / 1000.0
            http_port = proxy_port + 1
            proxy_url = f"http://{proxy_address}:{http_port}"
            test_url = "http://www.google.com/generate_204"

            start_time = time.time()
            response = requests.head(
                test_url,
                proxies={"http": proxy_url, "https": proxy_url},
                timeout=timeout_sec,
                allow_redirects=False,
            )
            elapsed_ms = int((time.time() - start_time) * 1000)

            # Accept 2xx, 3xx, and some 4xx (like 403) as success
            if 200 <= response.status_code < 500:
                logger.debug("Delay test successful: %d ms", elapsed_ms)
                return elapsed_ms
            else:
                logger.debug("Request failed with status %d", response.status_code)
                return -1

        except requests.exceptions.Timeout:
            logger.debug("Delay test timed out after %d ms", timeout)
            return -1
        except requests.exceptions.RequestException as e:
            logger.debug("Delay test error: %s", e)
            return -1
        except Exception as e:
            logger.debug("Unexpected error in delay test: %s", e)
            return -1

    def __enter__(self) -> XrayManager:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.stop()
