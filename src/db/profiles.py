from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.db.config import ConfigBase, RoutingSettings, VpnSettings

if TYPE_CHECKING:
    from src.fmt.base import ProxyBean


def _get_protocol_classes() -> dict[str, type[ProxyBean]]:
    """Lazy loading of protocol classes to avoid circular imports."""
    from src.fmt.protocols import (
        HttpBean,
        ShadowsocksBean,
        SocksBean,
        TrojanBean,
        VLESSBean,
        VMessBean,
    )

    return {
        "vless": VLESSBean,
        "trojan": TrojanBean,
        "vmess": VMessBean,
        "shadowsocks": ShadowsocksBean,
        "ss": ShadowsocksBean,
        "socks": SocksBean,
        "socks4": SocksBean,
        "socks4a": SocksBean,
        "socks5": SocksBean,
        "http": HttpBean,
    }


@dataclass
class ProfileGroup(ConfigBase):
    """Profile group."""

    id: int = 0
    name: str = "Default"
    is_subscription: bool = False
    subscription_url: str = ""
    last_updated: int = 0  # timestamp
    sub_user_info: str = ""


@dataclass
class ProfileEntry:
    """Profile entry in manager."""

    id: int
    group_id: int
    bean: ProxyBean
    latency_ms: int = -1
    last_used: int = 0  # timestamp
    vpn_settings: VpnSettings | None = None
    routing_settings: RoutingSettings | None = None

    @property
    def name(self) -> str:
        return self.bean.display_name

    @property
    def proxy_type(self) -> str:
        return self.bean.proxy_type

    def to_dict(self) -> dict[str, Any]:
        """Serialization."""
        result = {
            "id": self.id,
            "group_id": self.group_id,
            "type": self.proxy_type,
            "bean": self.bean.to_dict(),
            "latency_ms": self.latency_ms,
            "last_used": self.last_used,
        }
        if self.vpn_settings is not None:
            result["vpn_settings"] = self.vpn_settings.to_dict()
        if self.routing_settings is not None:
            result["routing_settings"] = self.routing_settings.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProfileEntry | None:
        """Deserialization."""
        try:
            proxy_type = data.get("type", "")
            bean_class = _get_protocol_classes().get(proxy_type)
            if not bean_class:
                print(f"Unknown protocol type: {proxy_type}")
                return None

            bean = bean_class.from_dict(data.get("bean", {}))

            vpn_settings = None
            if "vpn_settings" in data:
                vpn_settings = VpnSettings.from_dict(data["vpn_settings"])

            routing_settings = None
            if "routing_settings" in data:
                routing_settings = RoutingSettings.from_dict(data["routing_settings"])

            return cls(
                id=data.get("id", 0),
                group_id=data.get("group_id", 0),
                bean=bean,
                latency_ms=data.get("latency_ms", -1),
                last_used=data.get("last_used", 0),
                vpn_settings=vpn_settings,
                routing_settings=routing_settings,
            )
        except Exception as e:
            print(f"Error deserializing profile: {e}")
            return None


class ProfileManager:
    """Profile and group manager."""

    def __init__(self, profiles_dir: Path | None = None):
        self._profiles_dir = profiles_dir or Path.home() / ".config" / "tenga" / "profiles"
        self._profiles: dict[int, ProfileEntry] = {}
        self._groups: dict[int, ProfileGroup] = {}
        self._next_profile_id = 1
        self._next_group_id = 1
        self._current_group_id = 0
        self._profiles_dir.mkdir(parents=True, exist_ok=True)

    @property
    def profiles(self) -> dict[int, ProfileEntry]:
        """All profiles."""
        return self._profiles

    @property
    def groups(self) -> dict[int, ProfileGroup]:
        """All groups."""
        return self._groups

    @property
    def current_group_id(self) -> int:
        """Current group ID."""
        return self._current_group_id

    @current_group_id.setter
    def current_group_id(self, value: int) -> None:
        """Set current group."""
        self._current_group_id = value

    def get_profile(self, profile_id: int) -> ProfileEntry | None:
        """Get profile by ID."""
        return self._profiles.get(profile_id)

    def get_group(self, group_id: int) -> ProfileGroup | None:
        """Get group by ID."""
        return self._groups.get(group_id)

    def get_profiles_in_group(self, group_id: int) -> list[ProfileEntry]:
        """Get all profiles in group."""
        return [p for p in self._profiles.values() if p.group_id == group_id]

    def get_current_group_profiles(self) -> list[ProfileEntry]:
        """Get profiles of current group."""
        return self.get_profiles_in_group(self._current_group_id)

    def add_profile(
        self,
        bean: ProxyBean,
        group_id: int | None = None,
    ) -> ProfileEntry:
        """Add profile."""
        if group_id is None:
            group_id = self._current_group_id

        profile_id = self._next_profile_id
        self._next_profile_id += 1

        entry = ProfileEntry(
            id=profile_id,
            group_id=group_id,
            bean=bean,
        )

        self._profiles[profile_id] = entry
        return entry

    def remove_profile(self, profile_id: int) -> bool:
        """Remove profile."""
        if profile_id in self._profiles:
            del self._profiles[profile_id]
            return True
        return False

    def add_group(self, name: str, is_subscription: bool = False) -> ProfileGroup:
        """Add group."""
        group_id = self._next_group_id
        self._next_group_id += 1

        group = ProfileGroup(
            id=group_id,
            name=name,
            is_subscription=is_subscription,
        )

        self._groups[group_id] = group
        return group

    def remove_group(self, group_id: int, remove_profiles: bool = True) -> bool:
        """Remove group."""
        if group_id not in self._groups:
            return False

        if remove_profiles:
            profile_ids = [p.id for p in self._profiles.values() if p.group_id == group_id]
            for pid in profile_ids:
                del self._profiles[pid]

        del self._groups[group_id]
        return True

    def parse_and_add_link(self, link: str, group_id: int | None = None) -> ProfileEntry | None:
        """Parse share link and add profile."""
        bean = self.parse_link(link)
        if bean:
            return self.add_profile(bean, group_id)
        return None

    @staticmethod
    def parse_link(link: str) -> ProxyBean | None:
        """Parse share link."""
        from src.fmt.protocols import (
            HttpBean,
            ShadowsocksBean,
            SocksBean,
            TrojanBean,
            VLESSBean,
            VMessBean,
        )

        link = link.strip()

        # type by prefix
        if link.startswith("vless://"):
            bean = VLESSBean()
        elif link.startswith("trojan://"):
            bean = TrojanBean()
        elif link.startswith("vmess://"):
            bean = VMessBean()
        elif link.startswith("ss://"):
            bean = ShadowsocksBean()
        elif link.startswith(("socks://", "socks4://", "socks4a://", "socks5://")):
            bean = SocksBean()
        elif link.startswith(("http://", "https://")):
            bean = HttpBean()
        else:
            return None

        if bean.try_parse_link(link):
            return bean
        return None

    def load(self) -> bool:
        """Load profiles and groups."""
        try:
            meta_file = self._profiles_dir / "meta.json"
            if meta_file.exists():
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                self._next_profile_id = meta.get("next_profile_id", 1)
                self._next_group_id = meta.get("next_group_id", 1)
                self._current_group_id = meta.get("current_group_id", 0)

            groups_file = self._profiles_dir / "groups.json"
            if groups_file.exists():
                groups_data = json.loads(groups_file.read_text(encoding="utf-8"))
                for gdata in groups_data:
                    group = ProfileGroup.from_dict(gdata)
                    self._groups[group.id] = group

            if not self._groups:
                self._groups[0] = ProfileGroup(id=0, name="Default")

            profiles_file = self._profiles_dir / "profiles.json"
            if profiles_file.exists():
                profiles_data = json.loads(profiles_file.read_text(encoding="utf-8"))
                for pdata in profiles_data:
                    entry = ProfileEntry.from_dict(pdata)
                    if entry:
                        self._profiles[entry.id] = entry

            return True
        except Exception as e:
            print(f"Error loading profiles: {e}")
            return False

    def save(self) -> bool:
        """Save profiles and groups."""
        try:
            self._profiles_dir.mkdir(parents=True, exist_ok=True)

            meta = {
                "next_profile_id": self._next_profile_id,
                "next_group_id": self._next_group_id,
                "current_group_id": self._current_group_id,
            }
            meta_file = self._profiles_dir / "meta.json"
            meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")

            groups_data = [g.to_dict() for g in self._groups.values()]
            groups_file = self._profiles_dir / "groups.json"
            groups_file.write_text(json.dumps(groups_data, indent=2), encoding="utf-8")

            profiles_data = [p.to_dict() for p in self._profiles.values()]
            profiles_file = self._profiles_dir / "profiles.json"
            profiles_file.write_text(json.dumps(profiles_data, indent=2), encoding="utf-8")

            return True
        except Exception as e:
            print(f"Error saving profiles: {e}")
            return False

    def clear_group(self, group_id: int) -> int:
        """Clear group (remove all profiles)."""
        profile_ids = [p.id for p in self._profiles.values() if p.group_id == group_id]
        for pid in profile_ids:
            del self._profiles[pid]
        return len(profile_ids)
