from __future__ import annotations

import json
from abc import ABC
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import (
    Any,
    TypeVar,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

T = TypeVar("T", bound="ConfigBase")


def _is_optional(field_type: Any) -> bool:
    """Check if type is Optional[X]"""
    origin = get_origin(field_type)
    if origin is type(None):
        return True
    try:
        from typing import Union

        if origin is Union:
            args = get_args(field_type)
            return type(None) in args
    except:
        pass
    return False


def _get_inner_type(field_type: Any) -> Any:
    """Get inner type from Optional[X] or List[X]"""
    origin = get_origin(field_type)
    if origin is list:
        args = get_args(field_type)
        return args[0] if args else Any
    try:
        if origin is Union:
            args = get_args(field_type)
            for arg in args:
                if arg is not type(None):
                    return arg
    except:
        pass
    return field_type


@dataclass
class ConfigBase(ABC):
    """
    Base class for all configurations.
    Automatic serialization/deserialization to JSON.
    """

    def to_dict(self, exclude_defaults: bool = False, exclude_none: bool = True) -> dict[str, Any]:
        """
        Convert to dictionary.

        Args:
            exclude_defaults: Exclude fields with default values
            exclude_none: Exclude fields with None value
        """
        result = {}

        for f in fields(self):
            value = getattr(self, f.name)

            # Skip None
            if exclude_none and value is None:
                continue

            # Skip default values
            if exclude_defaults:
                if f.default is not field and value == f.default:
                    continue
                if f.default_factory is not field:
                    default_value = f.default_factory()
                    if value == default_value:
                        continue

            if isinstance(value, ConfigBase):
                result[f.name] = value.to_dict(exclude_defaults, exclude_none)
            elif isinstance(value, list):
                result[f.name] = [
                    item.to_dict(exclude_defaults, exclude_none)
                    if isinstance(item, ConfigBase)
                    else item
                    for item in value
                ]
            else:
                result[f.name] = value

        return result

    def to_json(self, indent: int | None = 2, ensure_ascii: bool = False) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=ensure_ascii)

    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any]) -> T:
        """
        Create instance from dictionary.

        Args:
            data: Dictionary with data
        """
        if not data:
            return cls()

        field_types = {}
        try:
            field_types = get_type_hints(cls)
        except:
            pass

        kwargs = {}
        for f in fields(cls):
            if f.name not in data:
                continue

            value = data[f.name]
            field_type = field_types.get(f.name, f.type)

            if _is_optional(field_type):
                if value is None:
                    kwargs[f.name] = None
                    continue
                field_type = _get_inner_type(field_type)

            origin = get_origin(field_type)

            if origin is list:
                inner_type = _get_inner_type(field_type)
                if isinstance(inner_type, type) and issubclass(inner_type, ConfigBase):
                    kwargs[f.name] = [inner_type.from_dict(item) for item in value]
                else:
                    kwargs[f.name] = value
            elif isinstance(field_type, type) and issubclass(field_type, ConfigBase):
                kwargs[f.name] = field_type.from_dict(value) if isinstance(value, dict) else value
            else:
                kwargs[f.name] = value

        return cls(**kwargs)

    @classmethod
    def from_json(cls: type[T], json_str: str) -> T:
        """Create instance from JSON string."""
        try:
            data = json.loads(json_str)
            return cls.from_dict(data)
        except json.JSONDecodeError:
            return cls()

    @classmethod
    def load(cls: type[T], filepath: Path | str) -> T:
        """Load from JSON file."""
        path = Path(filepath)
        if not path.exists():
            return cls()

        try:
            content = path.read_text(encoding="utf-8")
            return cls.from_json(content)
        except Exception as e:
            print(f"Error loading config from {filepath}: {e}")
            return cls()

    def save(self, filepath: Path | str, indent: int = 2) -> bool:
        """Save to JSON file."""
        path = Path(filepath)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.to_json(indent=indent), encoding="utf-8")
            return True
        except Exception as e:
            print(f"Error saving config to {filepath}: {e}")
            return False

    def update(self, **kwargs) -> None:
        """Update fields from kwargs."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def copy(self: T) -> T:
        """Create a copy."""
        return self.__class__.from_dict(self.to_dict())


@dataclass
class InboundAuth(ConfigBase):
    """Authentication for inbound connections."""

    username: str = ""
    password: str = ""

    def is_required(self) -> bool:
        """Check if authentication is required."""
        return bool(self.username.strip() and self.password.strip())


@dataclass
class ExtraCores(ConfigBase):
    """Additional proxy cores."""

    cores: dict[str, str] = field(default_factory=dict)

    def get(self, core_id: str) -> str:
        """Get core path by ID."""
        return self.cores.get(core_id, "")

    def set(self, core_id: str, path: str) -> None:
        """Set core path."""
        self.cores[core_id] = path

    def remove(self, core_id: str) -> None:
        """Remove core."""
        self.cores.pop(core_id, None)


class DnsProvider:
    """Predefined DNS providers."""

    SYSTEM = "system"
    GOOGLE = "google"
    CLOUDFLARE = "cloudflare"
    ADGUARD = "adguard"

    ALL = [SYSTEM, GOOGLE, CLOUDFLARE, ADGUARD]

    LABELS = {
        SYSTEM: "Системный DNS",
        GOOGLE: "Google DNS (DoH)",
        CLOUDFLARE: "Cloudflare DNS (DoH)",
        ADGUARD: "AdGuard DNS (DoH)",
    }

    # URLs for DoH
    URLS = {
        SYSTEM: "local",
        GOOGLE: "https://dns.google/dns-query",
        CLOUDFLARE: "https://cloudflare-dns.com/dns-query",
        ADGUARD: "https://dns.adguard.com/dns-query",
    }


@dataclass
class DnsSettings(ConfigBase):
    """DNS settings."""

    provider: str = DnsProvider.GOOGLE
    custom_url: str = ""
    # DNS via proxy
    use_proxy: bool = True

    def get_dns_url(self) -> str:
        """Get DNS server URL."""
        if self.custom_url:
            return self.custom_url
        return DnsProvider.URLS.get(self.provider, "local")


class RoutingMode:
    """Routing modes."""

    PROXY_ALL = "proxy_all"
    CUSTOM = "custom"  # Manual rules

    ALL = [PROXY_ALL, CUSTOM]

    LABELS = {
        PROXY_ALL: "Весь трафик через прокси",
        CUSTOM: "Пользовательские списки",
    }

    DESCRIPTIONS = {
        PROXY_ALL: "Весь трафик идёт через прокси",
        CUSTOM: "Настраиваемые списки",
    }


ROUTING_GROUPS = ["direct", "vpn", "proxy"]
DEFAULT_ROUTING_ORDER = ["direct", "vpn", "proxy"]


@dataclass
class RoutingSettings(ConfigBase):
    """Traffic routing settings."""

    mode: str = RoutingMode.CUSTOM
    proxy_list: list[str] = field(default_factory=list)
    direct_list: list[str] = field(default_factory=list)
    vpn_list: list[str] = field(default_factory=list)
    bypass_local_networks: bool = False
    # direct/vpn/proxy
    rule_order: list[str] = field(default_factory=lambda: DEFAULT_ROUTING_ORDER.copy())

    def load_list_file(self, filepath: Path) -> list[str]:
        """Load list from file."""
        result = []
        if not filepath.exists():
            return result

        try:
            content = filepath.read_text(encoding="utf-8")
            for line in content.split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    result.append(line)
        except Exception:
            pass

        return result

    def load_lists_from_files(self, config_dir: Path) -> None:
        """Load routing lists from files in config directory."""
        proxy_file = config_dir / "proxy_list.txt"
        direct_file = config_dir / "direct_list.txt"
        vpn_file = config_dir / "vpn_list.txt"

        self.proxy_list = self.load_list_file(proxy_file)
        self.direct_list = self.load_list_file(direct_file)
        self.vpn_list = self.load_list_file(vpn_file)

    def save_lists_to_files(self, config_dir: Path) -> bool:
        """Save routing lists to files in config directory."""
        try:
            config_dir.mkdir(parents=True, exist_ok=True)

            proxy_file = config_dir / "proxy_list.txt"
            direct_file = config_dir / "direct_list.txt"
            vpn_file = config_dir / "vpn_list.txt"

            proxy_file.write_text("\n".join(self.proxy_list), encoding="utf-8")
            direct_file.write_text("\n".join(self.direct_list), encoding="utf-8")
            vpn_file.write_text("\n".join(self.vpn_list), encoding="utf-8")

            return True
        except Exception:
            return False

    def parse_entries(self, entries: list[str]) -> tuple[list[str], list[str]]:
        """
        Split entries into domains and IP/CIDR.

        Returns:
            (domains, ips)
        """
        domains = []
        ips = []

        for entry in entries:
            entry = entry.strip().rstrip(",").strip()
            if not entry:
                continue

            if "," in entry:
                for part in entry.split(","):
                    part = part.strip().rstrip(",").strip()
                    if not part:
                        continue
                    part_domains, part_ips = self.parse_entries([part])
                    domains.extend(part_domains)
                    ips.extend(part_ips)
                continue

            if "/" in entry:
                parts = entry.split("/")
                if len(parts) == 2 and parts[1].isdigit():
                    ips.append(entry)
                    continue

            if entry[0].isdigit() and all(c.isdigit() or c == "." for c in entry):
                ips.append(entry + "/32")
                continue
            domains.append(entry)

        return domains, ips

    def get_rule_order(self) -> list[str]:
        """
        Get effective routing rule order.

        Ensures backward compatibility if the field is missing or empty.
        """
        order = getattr(self, "rule_order", None)
        if not order:
            return DEFAULT_ROUTING_ORDER.copy()

        normalized = [item for item in order if item in ROUTING_GROUPS]
        if not normalized:
            return DEFAULT_ROUTING_ORDER.copy()

        result: list[str] = []
        for group in normalized:
            if group not in result:
                result.append(group)
        for group in ROUTING_GROUPS:
            if group not in result:
                result.append(group)
        return result


@dataclass
class VpnSettings(ConfigBase):
    """VPN integration settings."""

    enabled: bool = False
    connection_name: str = "my-vpn"
    interface_name: str = ""
    direct_interface: str = ""
    auto_connect: bool = False
    over_vpn_networks: list[str] = field(default_factory=list)
    over_vpn_domains: list[str] = field(default_factory=list)
    direct_networks: list[str] = field(default_factory=list)
    direct_domains: list[str] = field(default_factory=list)


@dataclass
class MonitoringSettings(ConfigBase):
    """Connection monitoring settings."""

    enabled: bool = True
    check_interval_seconds: int = 10
    test_url: str = "https://www.google.com/generate_204"
