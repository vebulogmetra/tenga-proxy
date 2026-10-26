# Development

In this section, you'll find information about project structure, development process, and contributing to the project.

## Project Structure

```
tenga-proxy/
├── cli.py              # CLI interface
├── gui.py              # GUI interface
├── pyproject.toml      # Project dependencies and settings
├── README.md           # Main documentation
├── core/               # Application core
│   ├── __init__.py
│   ├── config.py       # Application configuration
│   ├── context.py      # Application context
│   ├── logging_utils.py # Logging utilities
│   ├── monitor.py      # Connection monitoring
│   └── xray_manager.py # xray-core management
├── src/
│   ├── __init__.py
│   ├── db/             # Data management
│   │   ├── profiles.py # Profile management
│   │   └── data_store.py # Data storage
│   ├── fmt/            # Formatting and parsing
│   │   ├── base.py     # Protocol base classes
│   │   ├── protocols/  # Protocol implementations
│   │   └── stream.py   # Transport settings
│   ├── sys/            # System utilities
│   └── ui/             # GUI components
│       ├── app.py      # Main application
│       ├── main_window.py # Main window
│       └── tray.py     # Tray icon
├── docs/               # Documentation
└── tests/              # Tests
```

## Development Setup

To start development:

```bash
# Clone repository
git clone https://github.com/vebulogmetra/tenga-proxy.git
cd tenga-proxy

# Install development dependencies
python cli.py setup-dev

# Or manually
uv sync --all-extras
```

## Development Dependencies

The project uses the following development tools:

- **uv** - package manager
- **ruff** - linter and formatter
- **pytest** - testing framework
- **pyinstaller** - Windows installer building

## Code Style

### Python

- Use **Black** formatting via **ruff**
- Follow **PEP 8** standards
- Use type annotations
- Write documentation for functions and classes

### Code Checking

```bash
# Check code with linter
python cli.py lint

# Fix automatically fixable issues
python cli.py lint --fix

# Format code
python cli.py format

# Run all checks
python cli.py lint-all
```

## Testing

### Running Tests

```bash
# Run all tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=src

# Run specific test
uv run pytest tests/test_specific.py
```

### Writing Tests

- Tests are located in the `tests/` directory
- Use `pytest` for writing tests

## Contributing to Project

### Creating New Features

1. **Fork the repository**
2. **Create a branch** for the new feature: `feature/feature-name`
3. **Implement the feature** with appropriate tests
4. **Update documentation** if necessary
5. **Create a Pull Request**


## Application Architecture

### Application Context

The `AppContext` class manages all main dependencies and application state:

- `config` - application settings
- `profiles` - profile manager
- `xray_manager` - xray-core management
- `proxy_state` - proxy state
- `monitor` - connection monitoring

### Profile Management

The `src.db.profiles` module manages profiles and groups:

- `ProfileManager` - main management class
- `ProfileEntry` - individual profile
- `ProfileGroup` - profile group

### Formatting and Parsing

The `src.fmt` module handles link parsing and formatting:

- `ProxyBean` - base class for all protocols
- `protocols/` - specific protocol implementations
- `stream.py` - transport settings

## Building Project

### Building the deb package

```bash
# Build dist/tenga-proxy_<version>_<arch>.deb
python cli.py build

# Install it through apt
python cli.py install
```

The build is `core/scripts/build_deb.sh`: sources and xray-core go to
`/usr/lib/tenga-proxy` and run on the system Python. The launcher, sudoers
rule and postinst/prerm scripts live in `packaging/linux/`. The package uses
the system requests and urllib3 (2.31 and 2.0 on Ubuntu 24.04), so CI also
runs the tests against those versions.

### Version Update

```bash
# Interactive version update
python cli.py bump-version

# With version specification
python cli.py bump-version 1.0.0
```

## Windows

### Environment

MSYS2 UCRT64 is used instead of `uv`: PyGObject and GTK come from MSYS2
packages, pip cannot build them. In the "MSYS2 UCRT64" shell:

```bash
pacman -S --needed git unzip \
  mingw-w64-ucrt-x86_64-python mingw-w64-ucrt-x86_64-python-pip \
  mingw-w64-ucrt-x86_64-python-gobject mingw-w64-ucrt-x86_64-gtk4 \
  mingw-w64-ucrt-x86_64-libadwaita mingw-w64-ucrt-x86_64-python-requests \
  mingw-w64-ucrt-x86_64-python-pytest mingw-w64-ucrt-x86_64-python-pytest-cov \
  mingw-w64-ucrt-x86_64-python-pywin32

# MSYS2 Python reads files as cp1252 by default
export PYTHONUTF8=1

bash core/scripts/install_dev.sh     # xray.exe, wintun.dll, geo databases
python gui.py
python -m pytest -q --no-cov
```

### Building the installer

Inno Setup 6 is required (`ISCC.exe`; the `ISCC` variable overrides the path):

```bash
python -m venv --system-site-packages .venv-win
. .venv-win/bin/activate
pip install pyinstaller pyinstaller-hooks-contrib
bash core/scripts/build_windows.sh
# → dist/windows/veblock-<version>-windows-x64-setup.exe
```

The build folder holds two executables: `tenga-proxy.exe` (GUI) and
`tenga-proxy-svc.exe` (the service; arguments `install`, `remove`, `cleanup`,
`debug`).

### Layout

- `src/sys/*.py` are facades: `IS_WINDOWS` from `src/core/platform_info.py`
  picks the implementation when the facade is imported, Linux code lives in
  `src/sys/linux/`, Windows code in `src/sys/windows/`. Both implementations
  must export the same names and signatures; `tests/test_sys_facades.py`
  checks it.
- UI differences: texts in `src/ui/logic/platform_texts.py`, layout in
  `src/ui/logic/platform_layout.py`. Widgets do not check the OS themselves.
- The network rollback journal (`src/core/net_journal.py`) is shared: the
  Windows service and the Linux TUN routes both write it. If the app crashes
  on Linux, the default route is restored on the next start.
- `src/sys/tun_access.py` reports what TUN mode is missing: `cap_net_admin`
  on xray and a sudo rule for the route helper on Linux, the installed
  service on Windows.
- `src/winsvc/` is the service: pipe protocol, configuration policy, rollback
  journal, `netsh`/PowerShell commands, state and the pipe server.
- On Windows `AppContext.xray_manager` is a `WindowsXrayManager`: a config with
  a TUN inbound is started by the service, everything else by the GUI itself.
- `src/ui/tray/win32/` is the tray on top of `Shell_NotifyIcon`.
- `packaging/windows/` holds the PyInstaller spec and the Inno Setup script.

### Tests

Windows modules import on Linux too: system calls are injected or imported
lazily, so most of their tests run in the regular suite. Tests that need real
Windows carry the `windows` marker and are skipped elsewhere.

`tests/integration/` checks the service on a live system (TUN, routes, NRPT,
rollback). It needs the installed service and administrator rights and is
enabled with `TENGA_SERVICE_TESTS=1`. Run it in CI or on a test machine, not
on your workstation: the routes capture the network during the test.

### CI

`.github/workflows/linux.yml` on `ubuntu-24.04`: lint, the test suite,
`make test-gtk`, `make test-tray`, tests on Ubuntu's requests, the deb build
and its installation on the runner; on a `v*` tag the package is attached to
the release.

`.github/workflows/windows.yml` on `windows-latest`: Windows-code tests, the
full suite (informational), the installer build, installing the service from
the build and the integration tests. On a `v*` tag the installer is attached
to the release; the tag must match the version in `src/__init__.py`.

## Debugging

### Logging

Logs live in `logs/` (development mode), in `~/.config/tenga-proxy/logs/`
(deb package) or in `%LOCALAPPDATA%\tenga-proxy\logs` (Windows):

- `tenga_gui.log` - GUI logs
- `tenga_cli.log` - CLI logs
- `xray.log` - xray-core output

At midnight a file is archived with the date in its name (`xray.log.2026-10-08`).
Logs are kept for three days: today's file and two archives; anything older
is removed on rotation and on application start.

### Environment Variables

- `TENGA_CONFIG_DIR` - configuration directory
- `XDG_CONFIG_HOME` - standard XDG configuration directory

## Making Changes

When making changes:

1. **Update tests** if necessary
2. **Check formatting and linting**
3. **Ensure all tests pass**
4. **Update documentation** if necessary