from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from src.db.config import (
    ConfigBase,
    InboundAuth,
    ExtraCores,
    DnsSettings,
    RoutingSettings,
)


@dataclass
class DataStore(ConfigBase):
    """Main application settings storage."""
    # Inbound settings
    inbound_address: str = "127.0.0.1"
    inbound_socks_port: int = 2080
    inbound_auth: InboundAuth = field(default_factory=InboundAuth)
    custom_inbound: str = '{"inbounds": []}'
    # Logging
    log_level: str = "info"
    log_ignore: List[str] = field(default_factory=list)
    max_log_line: int = 200
    # Testing
    test_latency_url: str = "http://cp.cloudflare.com/"
    test_download_url: str = "http://cachefly.cachefly.net/10mb.test"
    test_download_timeout: int = 30
    test_concurrent: int = 5
    # Mux settings
    mux_protocol: str = "h2mux"
    mux_padding: bool = False
    mux_concurrency: int = 8
    mux_default_on: bool = False
    # UI settings
    theme: str = "0"
    language: int = 0
    window_size: str = ""
    splitter_state: str = ""
    start_minimal: bool = False
    # Subscriptions
    user_agent: str = ""
    sub_use_proxy: bool = False
    sub_clear: bool = False
    sub_insecure: bool = False
    sub_auto_update: int = -30
    # Security
    skip_cert: bool = False
    utls_fingerprint: str = ""
    # Remember state
    remember_spmode: List[str] = field(default_factory=list)
    remember_id: int = -1919
    remember_enable: bool = False
    current_group: int = 0
    # Routing
    active_routing: str = "Default"
    custom_route_global: str = '{"rules": []}'
    # VPN settings
    fake_dns: bool = False
    vpn_internal_tun: bool = True
    vpn_implementation: int = 0
    vpn_mtu: int = 9000
    vpn_ipv6: bool = False
    vpn_hide_console: bool = True
    vpn_strict_route: bool = False
    vpn_rule_white: bool = False
    vpn_rule_process: str = ""
    vpn_rule_cidr: str = ""
    # Hotkeys
    hotkey_mainwindow: str = ""
    hotkey_group: str = ""
    hotkey_route: str = ""
    hotkey_system_proxy_menu: str = ""
    # Core settings
    core_box_clash_api: int = -9090
    core_box_clash_api_secret: str = ""
    core_box_underlying_dns: str = ""
    # Additional cores
    extra_cores: ExtraCores = field(default_factory=ExtraCores)
    # Traffic routing
    routing: RoutingSettings = field(default_factory=RoutingSettings)
    # DNS settings
    dns: DnsSettings = field(default_factory=DnsSettings)
    # Misc
    old_share_link_format: bool = True
    traffic_loop_interval: int = 1000
    connection_statistics: bool = False
    check_include_pre: bool = False
    system_proxy_format: str = ""
    # Runtime state (not saved)
    _core_token: str = field(default="", repr=False)
    _core_port: int = field(default=19810, repr=False)
    _started_id: int = field(default=-1919, repr=False)
    _core_running: bool = field(default=False, repr=False)
    
    def to_dict(self, exclude_defaults: bool = False, exclude_none: bool = True) -> dict:
        """Override to exclude runtime fields."""
        result = super().to_dict(exclude_defaults, exclude_none)
        # Remove private runtime fields
        for key in list(result.keys()):
            if key.startswith('_'):
                del result[key]
        return result
    
    def get_user_agent(self, use_default: bool = False) -> str:
        """Get User-Agent."""
        if use_default or not self.user_agent:
            return "Tenga-proxy/1.0 (Prefer ClashMeta Format)"
        return self.user_agent
    
    def update_started_id(self, profile_id: int) -> None:
        """Update started profile ID."""
        self._started_id = profile_id
        if self.remember_enable:
            self.remember_id = profile_id
    
    @property
    def is_running(self) -> bool:
        """Check if proxy is running."""
        return self._core_running
    
    @property
    def started_id(self) -> int:
        """Started profile id."""
        return self._started_id

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "tenga"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "settings.json"


def get_default_config_path() -> Path:
    """Get default configuration path."""
    return DEFAULT_CONFIG_FILE


def load_data_store(config_path: Optional[Path] = None) -> DataStore:
    """Load DataStore from file."""
    path = config_path or DEFAULT_CONFIG_FILE
    return DataStore.load(path)


def save_data_store(store: DataStore, config_path: Optional[Path] = None) -> bool:
    """Save DataStore to file."""
    path = config_path or DEFAULT_CONFIG_FILE
    return store.save(path)
