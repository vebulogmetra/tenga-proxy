# Installation

## Moving from Tenga Proxy

The app has been renamed to Veblock. The update installs over the previous
version: profiles, subscriptions and settings are kept. The launch command
(`tenga-proxy`), the deb package name and the settings directory
(`~/.config/tenga-proxy`) are unchanged. On Windows the installer replaces the
"Tenga Proxy" shortcuts with "Veblock"; the service name (`TengaProxySvc`) and
the install directory stay the same.

## Linux: deb package

Download `tenga-proxy_<version>_amd64.deb` from the
[Releases](https://github.com/vebulogmetra/tenga-proxy/releases) page and install it:

```bash
sudo apt install ./tenga-proxy_<version>_amd64.deb
```

apt pulls in the dependencies: Python 3.11+, PyGObject, GTK 4, libadwaita 1.5+
and requests. Ubuntu 24.04, Debian 13 and later work; older distributions lack
libadwaita 1.5 and apt refuses the package.

### Where things live

| What | Where |
|---|---|
| Application | `/usr/lib/tenga-proxy` |
| Launcher | `/usr/bin/tenga-proxy` |
| xray-core and geo databases | `/usr/lib/tenga-proxy/core/bin` |
| TUN route helper | `/usr/libexec/tenga-proxy/tun-route-helper` |
| sudoers rule | `/etc/sudoers.d/tenga-proxy` |
| Settings, profiles, logs | `~/.config/tenga-proxy` |

### TUN mode

On install the package grants xray-core `cap_net_admin,cap_net_raw`: the core
creates the TUN interface itself. The default route is switched by a helper
run through passwordless `sudo`; the package rule allows it for the `sudo`
group, i.e. system administrators. Users outside that group get no TUN until
they are added (`sudo usermod -aG sudo <name>` and sign in again). Settings
and the connection error say what is missing.

### Moving from AppImage

AppImage builds are no longer published. On install the package removes the
`/usr/local/libexec/tenga-proxy` helper and the
`/etc/sudoers.d/tenga-proxy-tun-helper-*` rules; on first start the app removes
`~/.local/share/applications/tenga-proxy.desktop` if it launched an AppImage,
together with its icons. Settings in `~/.config/tenga-proxy` stay. Delete
`~/.local/bin/tenga-proxy.AppImage` and the core copy in
`~/.config/tenga-proxy/bin` yourself.

### Uninstall

```bash
sudo apt remove tenga-proxy   # purge also removes the sudoers rule
```

Settings in `~/.config/tenga-proxy` stay; delete the directory if you no
longer need them.

## Requirements for running from sources

Veblock requires:

- Python 3.11+
- Dependencies from `pyproject.toml`
- `xray` binary (for running proxy)

## Installing Dependencies

### Using uv (recommended)

```bash
uv sync
```

### Using pip

```bash
pip3 install -e .
```

## Installing xray-core for development

When running from sources the `xray` binary is looked up:

1. **In project directory:** `core/bin/xray`
2. **In system PATH:** installed system-wide

### Option 1: Download binary

```bash
# Download from https://github.com/XTLS/Xray-core/releases
# Extract
# Place in core/bin/xray
chmod +x core/bin/xray
```

### Option 2: Install system-wide

```bash
# See official documentation: https://xtls.github.io
```

## Development Environment Setup

For development and running from sources:

```bash
python cli.py setup-dev
```

- System dependencies
- Python venv
- Python dependencies from `pyproject.toml`
- xray-core binary

## Building the deb package

### Build Requirements

- System dependencies (installed via `python cli.py setup-dev`)
- `xray` binary and geo databases in `core/bin/`
- `dpkg-deb` (present on any Debian/Ubuntu system)

### Build and install

```bash
python cli.py build               # dist/tenga-proxy_<version>_<arch>.deb
python cli.py install             # sudo apt install of that file
python cli.py setup               # both in one command
python cli.py install --uninstall # sudo apt remove tenga-proxy
```

## System Dependencies for running from sources (Ubuntu/Debian)

The interface needs libadwaita 1.5 or newer: Ubuntu 24.04, Fedora 40,
Debian 13 and later ship it out of the box.

```bash
sudo apt update
sudo apt install -y \
    python3 \
    python3-gi \
    python3-pip \
    gir1.2-gtk-4.0 \
    gir1.2-adw-1
```
## Windows

### Installation

Download `veblock-<version>-windows-x64-setup.exe` from the
[Releases](https://github.com/vebulogmetra/tenga-proxy/releases) page and run
it. Windows 10 or 11 (x64) is required; the installer asks for administrator
rights (UAC). The wizard can add a desktop shortcut and start the app at sign-in.

GTK, libadwaita, xray-core and the wintun driver are bundled; nothing else
needs to be installed.

Autostart and the `veblock://`, `wingeon://` links are registered under
`HKCU` of the user who ran the installer.

### Where things live

| What | Where |
|---|---|
| Application | `C:\Program Files\Veblock` (after upgrading from Tenga Proxy, the previous `C:\Program Files\Tenga Proxy`) |
| Settings and profiles | `%APPDATA%\tenga-proxy` |
| Application logs | `%LOCALAPPDATA%\tenga-proxy\logs` |
| Service logs and journal | `%ProgramData%\tenga-proxy` (read-only for users) |

### TUN mode and the "Veblock" service

Creating a network interface and changing routes requires administrator
rights, so the installer registers the `TengaProxySvc` service (display name
"Veblock", delayed automatic start). The app hands the TUN configuration
to it over a local pipe, so connecting does not show a UAC prompt. System
proxy mode does not use the service.

The service:

- runs xray-core with the `xray0` TUN interface;
- sends traffic into the tunnel with `0.0.0.0/1` and `128.0.0.0/1` routes and
  keeps the proxy server address on the main interface;
- routes system DNS through the tunnel with an NRPT rule commented
  `tenga-proxy`;
- validates the configuration and accepts loopback inbounds only, so sharing
  the proxy with the local network is not available in TUN mode on Windows.

Every network change is journaled and rolled back on disconnect, when
xray-core crashes, when the app goes away (after 15 seconds), when the service
stops, and when it starts after a crash or reboot.

Limitations: IPv6 is not tunneled (same as on Linux); any locally signed-in
user can control TUN mode through the service.

### Uninstalling

"Settings → Apps → Veblock → Uninstall". The service stops, rolls the
network back and is removed. Settings in `%APPDATA%\tenga-proxy` are kept;
delete the folder manually if you do not need them.
