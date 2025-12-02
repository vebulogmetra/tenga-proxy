from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

from src.core.config import (
    DEFAULT_CLASH_API_ADDR,
    DEFAULT_CLASH_API_SECRET,
    find_singbox_binary,
)

logger = logging.getLogger("tenga.singbox_manager")


@dataclass
class TrafficStats:
    """Traffic statistics."""
    upload: int = 0
    download: int = 0


@dataclass
class Connection:
    """Connection information."""
    id: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    upload: int = 0
    download: int = 0
    start: str = ""
    chains: List[str] = field(default_factory=list)
    rule: str = ""
    rule_payload: str = ""


class SingBoxManager:
    """
    Management of sing-box via subprocess + Clash API.
    
    Provides:
    - Start/stop sing-box as subprocess
    - Monitoring via built-in Clash API
    - Traffic statistics retrieval
    - Connection management
    """
    def __init__(
        self,
        binary_path: Optional[str] = None,
        clash_api_addr: str = DEFAULT_CLASH_API_ADDR,
        clash_api_secret: str = DEFAULT_CLASH_API_SECRET,
    ):
        """
        Initialize manager.
        
        Args:
            binary_path: Path to sing-box binary. If None, automatic search will be performed
                        (first core/bin/sing-box, then system)
            clash_api_addr: Clash API address (host:port)
            clash_api_secret: Secret for Clash API authentication
        """
        if binary_path is None:
            binary_path = find_singbox_binary()
            if binary_path is None:
                raise RuntimeError(
                    "sing-box not found. Install sing-box and ensure "
                    "it is available in PATH or in core/bin/ directory"
                )
        
        self._binary_path = binary_path
        self._clash_api_addr = clash_api_addr
        self._clash_api_secret = clash_api_secret
        self._process: Optional[subprocess.Popen] = None
        self._config_file: Optional[Path] = None
        self._on_stop_callback: Optional[Callable[[], None]] = None
        
    @property
    def binary_path(self) -> str:
        """Path to sing-box binary."""
        return self._binary_path
    
    @property
    def clash_api_url(self) -> str:
        """Clash API URL."""
        return f"http://{self._clash_api_addr}"
    
    @property
    def is_running(self) -> bool:
        """Check if process is running."""
        if self._process is None:
            return False
        return self._process.poll() is None
    
    def set_on_stop_callback(self, callback: Optional[Callable[[], None]]) -> None:
        """Set callback for process stop."""
        self._on_stop_callback = callback
    
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for Clash API."""
        headers = {"Content-Type": "application/json"}
        if self._clash_api_secret:
            headers["Authorization"] = f"Bearer {self._clash_api_secret}"
        return headers
    
    def _inject_clash_api(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add clash_api section to configuration.
        
        Args:
            config: Original sing-box configuration
            
        Returns:
            Configuration with added clash_api
        """
        config = config.copy()

        if "experimental" not in config:
            config["experimental"] = {}

        # Enable clash_api
        config["experimental"]["clash_api"] = {
            "external_controller": self._clash_api_addr,
            "secret": self._clash_api_secret,
        }
        
        return config
    
    def start(self, config: Dict[str, Any]) -> tuple[bool, str]:
        """
        Start sing-box with configuration.
        
        Args:
            config: sing-box configuration (dict)
            
        Returns:
            (success, error_message)
        """
        if self.is_running:
            self.stop()

        config = self._inject_clash_api(config)

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
            self._process = subprocess.Popen(
                [self._binary_path, "run", "-c", str(self._config_file)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            time.sleep(0.5)

            if self._process.poll() is not None:
                _, stderr = self._process.communicate(timeout=5)
                error_msg = stderr.decode("utf-8", errors="replace").strip()
                self._cleanup()
                return False, f"sing-box exited with error: {error_msg}"
            
            # Check that Clash API is available
            if not self._wait_for_api(timeout=5):
                self.stop()
                return False, "Clash API не запустился"
            
            logger.info("sing-box запущен, PID: %s", self._process.pid)
            return True, ""
            
        except FileNotFoundError:
            self._cleanup()
            return False, f"Binary not found: {self._binary_path}"
        except Exception as e:
            self._cleanup()
            return False, f"Startup error: {e}"
    
    def _wait_for_api(self, timeout: float = 5.0) -> bool:
        """Wait for Clash API to become available."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                r = requests.get(
                    f"{self.clash_api_url}/version",
                    headers=self._get_headers(),
                    timeout=1,
                )
                if r.status_code == 200:
                    return True
            except requests.RequestException:
                pass
            time.sleep(0.2)
        return False
    
    def stop(self) -> tuple[bool, str]:
        """
        Stop sing-box.
        
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
            
            logger.info("sing-box stopped")
            
        except Exception as e:
            logger.warning("Error stopping sing-box: %s", e)
        
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

        if self._config_file and self._config_file.exists():
            try:
                self._config_file.unlink()
            except Exception:
                pass
            self._config_file = None

    # Clash API methods   
    def get_version(self) -> Optional[Dict[str, Any]]:
        """Get sing-box version."""
        try:
            r = requests.get(
                f"{self.clash_api_url}/version",
                headers=self._get_headers(),
                timeout=5,
            )
            if r.status_code == 200:
                return r.json()
        except requests.RequestException as e:
            logger.debug("get_version error: %s", e)
        return None
    
    def get_traffic(self) -> TrafficStats:
        """
        Get current traffic statistics.
        
        Note: For real-time statistics use get_traffic_stream()
        """
        # Clash API returns current traffic via /traffic WebSocket
        # For one-time request we use /connections
        try:
            r = requests.get(
                f"{self.clash_api_url}/connections",
                headers=self._get_headers(),
                timeout=5,
            )
            if r.status_code == 200:
                data = r.json()
                return TrafficStats(
                    upload=data.get("uploadTotal", 0),
                    download=data.get("downloadTotal", 0),
                )
        except requests.RequestException as e:
            logger.debug("get_traffic error: %s", e)
        return TrafficStats()
    
    def get_connections(self) -> List[Connection]:
        """Get list of active connections."""
        try:
            r = requests.get(
                f"{self.clash_api_url}/connections",
                headers=self._get_headers(),
                timeout=5,
            )
            if r.status_code == 200:
                data = r.json()
                connections = []
                for conn in data.get("connections", []):
                    connections.append(Connection(
                        id=conn.get("id", ""),
                        metadata=conn.get("metadata", {}),
                        upload=conn.get("upload", 0),
                        download=conn.get("download", 0),
                        start=conn.get("start", ""),
                        chains=conn.get("chains", []),
                        rule=conn.get("rule", ""),
                        rule_payload=conn.get("rulePayload", ""),
                    ))
                return connections
        except requests.RequestException as e:
            logger.debug("get_connections error: %s", e)
        return []
    
    def close_connection(self, connection_id: str) -> bool:
        """Close connection by ID."""
        try:
            r = requests.delete(
                f"{self.clash_api_url}/connections/{connection_id}",
                headers=self._get_headers(),
                timeout=5,
            )
            return r.status_code == 204
        except requests.RequestException as e:
            logger.debug("close_connection error: %s", e)
        return False
    
    def close_all_connections(self) -> bool:
        """Close all connections."""
        try:
            r = requests.delete(
                f"{self.clash_api_url}/connections",
                headers=self._get_headers(),
                timeout=5,
            )
            return r.status_code == 204
        except requests.RequestException as e:
            logger.debug("close_all_connections error: %s", e)
        return False
    
    def get_proxies(self) -> Dict[str, Any]:
        """Get list of proxies (outbounds)."""
        try:
            r = requests.get(
                f"{self.clash_api_url}/proxies",
                headers=self._get_headers(),
                timeout=5,
            )
            if r.status_code == 200:
                return r.json()
        except requests.RequestException as e:
            logger.debug("get_proxies error: %s", e)
        return {}
    
    def test_delay(
        self,
        proxy_name: str,
        url: str = "https://www.google.com/generate_204",
        timeout: int = 5000,
    ) -> int:
        """
        Test proxy latency.
        
        Args:
            proxy_name: Proxy name (outbound tag)
            url: URL for testing
            timeout: Timeout in milliseconds
            
        Returns:
            Latency in ms or -1 on error
        """
        try:
            r = requests.get(
                f"{self.clash_api_url}/proxies/{proxy_name}/delay",
                params={"url": url, "timeout": timeout},
                headers=self._get_headers(),
                timeout=timeout / 1000 + 2,
            )
            if r.status_code == 200:
                return r.json().get("delay", -1)
        except requests.RequestException as e:
            logger.debug("test_delay error: %s", e)
        return -1
    
    def get_logs(self, level: str = "info") -> Optional[requests.Response]:
        """
        Get log stream (for use in iterator).
        
        Args:
            level: Log level (debug, info, warning, error)
            
        Returns:
            Response object for streaming or None
            
        Usage:
            response = manager.get_logs()
            if response:
                for line in response.iter_lines():
                    print(json.loads(line))
        """
        try:
            return requests.get(
                f"{self.clash_api_url}/logs",
                params={"level": level},
                headers=self._get_headers(),
                stream=True,
                timeout=None,
            )
        except requests.RequestException as e:
            logger.debug("get_logs error: %s", e)
        return None
    
    def get_config(self) -> Dict[str, Any]:
        """Get current configuration."""
        try:
            r = requests.get(
                f"{self.clash_api_url}/configs",
                headers=self._get_headers(),
                timeout=5,
            )
            if r.status_code == 200:
                return r.json()
        except requests.RequestException as e:
            logger.debug("get_config error: %s", e)
        return {}
    
    def __enter__(self) -> "SingBoxManager":
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.stop()
