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