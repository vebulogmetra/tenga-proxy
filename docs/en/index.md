# Tenga Proxy

**Tenga Proxy** is a Linux proxy client with [xray-core](https://github.com/XTLS/Xray-core) backend that provides a convenient interface for working with various proxy protocols.

## Key Features

- Support for various protocols: VLESS, Trojan, VMess, Shadowsocks, SOCKS, HTTP
- Share links parsing (vless://, trojan://, vmess://, ss://, socks://)
- Subscription import (base64, plain text)
- xray-core configuration generation
- Automatic system proxy setup (GNOME/KDE)
- Flexible traffic routing (through VLESS, VPN, or directly)
- Profile management
- System tray with notifications (GTK)
- Monitoring via Stats API (statistics)

## Quick Start

For quick installation and launch:

```bash
# Install and build AppImage
python cli.py setup

# Run GUI
python gui.py

# Or run CLI
python cli.py --help
```

## Supported Protocols

- **VLESS** — including Reality, XTLS support
- **Trojan** — with and without TLS
- **VMess** — V2Ray compatible
- **Shadowsocks** — including 2022 methods
- **SOCKS4/4a/5** — standard proxies
- **HTTP/HTTPS** — HTTP proxies