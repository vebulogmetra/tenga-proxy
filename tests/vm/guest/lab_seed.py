"""Настройки и серверы приложения; запускается от tester кодом установленного пакета."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.db.config import VpnSettings
from src.db.profiles import ProfileManager


def main() -> None:
    spec = json.loads(sys.argv[1])
    config_dir = Path(spec["config_dir"])
    (config_dir / "profiles").mkdir(parents=True, exist_ok=True)
    (config_dir / "settings.json").write_text(json.dumps(spec["settings"]), encoding="utf-8")

    store = ProfileManager(config_dir / "profiles")
    ids = {}
    for server in spec["servers"]:
        entry = store.parse_and_add_link(server["link"])
        if server.get("vpn"):
            entry.vpn_settings = VpnSettings(
                enabled=True, connection_name=server["vpn"], auto_connect=True
            )
        ids[server["name"]] = entry.id
    store.save()
    print(json.dumps(ids))


if __name__ == "__main__":
    main()
