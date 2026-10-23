# Installation

## Requirements

Tenga Proxy requires:

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

## Installing xray-core

CLI and GUI require the `xray` binary. It can be:

1. **In project directory:** `core/bin/xray`
2. **In system PATH:** installed system-wide
3. **In AppImage:** built into the image

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

## Quick Installation

To build and install/update AppImage in the system:

```bash
python cli.py setup
```

- Builds AppImage
- Installs it in the system
- Creates a shortcut in the applications menu

After this, the application will be available in the menu.

## Development Environment Setup

For development and running from sources:

```bash
python cli.py setup-dev
```

- System dependencies
- Python venv
- Python dependencies from `pyproject.toml`
- xray-core binary

## Building AppImage

To create a portable AppImage file:

### Build Requirements

- System dependencies (installed via `python cli.py setup-dev`)
- `xray` binary in `core/bin/xray`

### Build

```bash
python cli.py build
```

Result will be in `dist/tenga-proxy-x.AppImage`.

### Install AppImage in system

```bash
python cli.py install
```

After installation "Tenga Proxy" will be available in the applications menu.

### Uninstall AppImage

```bash
python cli.py install --uninstall
```

## System Dependencies (Ubuntu/Debian)

The interface needs libadwaita 1.5 or newer: Ubuntu 24.04, Fedora 40,
Debian 13 and later ship it out of the box.

```bash
sudo apt update
sudo apt install -y \
    python3 \
    python3-gi \
    python3-pip \
    gir1.2-gtk-4.0 \
    gir1.2-adw-1 \
    libfuse2t64
```
## Windows

### Installation

Download `tenga-proxy-<version>-windows-x64-setup.exe` from the
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
| Application | `C:\Program Files\Tenga Proxy` |
| Settings and profiles | `%APPDATA%\tenga-proxy` |
| Application logs | `%LOCALAPPDATA%\tenga-proxy\logs` |
| Service logs and journal | `%ProgramData%\tenga-proxy` (read-only for users) |

### TUN mode and the "Tenga Proxy" service

Creating a network interface and changing routes requires administrator
rights, so the installer registers the `TengaProxySvc` service (display name
"Tenga Proxy", delayed automatic start). The app hands the TUN configuration
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

"Settings → Apps → Tenga Proxy → Uninstall". The service stops, rolls the
network back and is removed. Settings in `%APPDATA%\tenga-proxy` are kept;
delete the folder manually if you do not need them.
