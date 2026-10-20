"""In-memory signatures of settings that require a new core session."""

from __future__ import annotations

import hashlib
import json

_RUNTIME_KEYS = (
    "inbound_address",
    "inbound_socks_port",
    "inbound_auth",
    "custom_inbound",
    "proxy_mode",
    "tun_name",
    "tun_mtu",
    "log_level",
    "mux_protocol",
    "mux_padding",
    "mux_concurrency",
    "mux_default_on",
    "skip_cert",
    "utls_fingerprint",
    "routing",
    "dns",
    "vpn",
    "tls_fragment",
    "custom_route_global",
    "fake_dns",
)


def runtime_snapshot(config, profile, *, geo_paths=None, config_dir=None) -> str | None:
    from src.core.config import find_xray_binary
    from src.core.geo import asset_dirs, find_geo_file
    from src.db.data_store import DataStore

    if not isinstance(config, DataStore):
        return None
    if geo_paths is None:
        dirs = asset_dirs(find_xray_binary())
        geo_paths = [find_geo_file(name, dirs) for name in ("geosite.dat", "geoip.dat")]
    geobases = []
    for path in geo_paths:
        try:
            stat = path.stat()
            geobases.append((str(path), stat.st_size, stat.st_mtime_ns, stat.st_ino))
        except (AttributeError, OSError):
            geobases.append(None)
    settings = config.to_dict()
    if config_dir is not None and not config.routing.use_saved_lists:
        import copy

        routing = copy.deepcopy(config.routing)
        routing.load_lists_from_files(config_dir)
        settings["routing"] = routing.to_dict()
    value = {
        "settings": {key: settings.get(key) for key in _RUNTIME_KEYS},
        "profile": profile.bean.to_dict(),
        "id": profile.id,
        "routing": profile.routing_settings.to_dict() if profile.routing_settings else None,
        "vpn": profile.vpn_settings.to_dict() if profile.vpn_settings else None,
        "geo": geobases,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def pending_settings(context) -> bool:
    state = context.proxy_state
    if not state.is_running or state.applied_settings is None:
        return False
    profile = context.profiles.get_profile(state.started_profile_id)
    return (
        profile is not None
        and runtime_snapshot(context.config, profile, config_dir=context.config_dir)
        != state.applied_settings
    )
