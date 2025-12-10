from __future__ import annotations

import base64
import ipaddress
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.db.config import ConfigBase

if TYPE_CHECKING:
    from src.fmt.stream import StreamSettings


def is_ip_address(address: str) -> bool:
    """Check if address is IP."""
    try:
        ipaddress.ip_address(address)
        return True
    except ValueError:
        return False


def format_address(server: str, port: int) -> str:
    """Format server address."""
    return f"{server}:{port}"


@dataclass
class ProxyBean(ConfigBase, ABC):
    """
    Base class for all proxy profile types.
    Replaces AbstractBean.
    """

    name: str = ""
    server_address: str = "127.0.0.1"
    server_port: int = 1080

    custom_config: str = ""
    custom_outbound: str = ""

    id: int = field(default=-1, repr=False)
    group_id: int = field(default=0, repr=False)

    @property
    @abstractmethod
    def proxy_type(self) -> str:
        """Protocol type (vless, vmess, trojan, etc.)."""

    @property
    def display_name(self) -> str:
        """Display name of profile."""
        return self.name if self.name else self.display_address

    @property
    def display_address(self) -> str:
        """Display address."""
        return format_address(self.server_address, self.server_port)

    @property
    def display_type_and_name(self) -> str:
        """Type and name for display."""
        return f"[{self.proxy_type.upper()}] {self.display_name}"

    @property
    def core_type(self) -> str:
        """Core type (sing-box)."""
        return "sing-box"

    @abstractmethod
    def to_share_link(self) -> str:
        """Create share link."""

    @abstractmethod
    def try_parse_link(self, link: str) -> bool:
        """Try to parse share link."""

    @abstractmethod
    def build_outbound(self, skip_cert: bool = False) -> dict[str, Any]:
        """Build outbound configuration for sing-box."""

    def build_core_obj_singbox(self, skip_cert: bool = False) -> dict[str, Any]:
        """
        Build configuration for sing-box.
        Returns dictionary with fields: outbound, error.
        """
        try:
            outbound = self.build_outbound(skip_cert)
            return {"outbound": outbound, "error": ""}
        except Exception as e:
            return {"outbound": {}, "error": str(e)}

    def to_tenga_share_link(self) -> str:
        """Create Tenga share link."""
        data = self.to_dict()
        json_str = json.dumps(data, separators=(",", ":"))
        encoded = base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8").rstrip("=")
        return f"tenga://{self.proxy_type}#{encoded}"

    def get_stream(self) -> StreamSettings | None:
        """Get transport settings (if any)."""
        return getattr(self, "stream", None)

    def needs_external_core(self, is_first_profile: bool = True) -> int:
        """
        Check if external process is needed.
        Returns 0 if not needed, otherwise type code.
        """
        return 0


@dataclass
class ProxyBeanWithStream(ProxyBean, ABC):
    """
    Base class for proxies with transport settings.
    """

    def get_stream(self) -> StreamSettings | None:
        """Get transport settings."""
        return getattr(self, "stream", None)
