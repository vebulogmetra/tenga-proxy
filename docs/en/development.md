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
- **pyinstaller** - AppImage building

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

### Building AppImage

```bash
# Build AppImage
python cli.py build

# Install AppImage
python cli.py install
```

### Version Update

```bash
# Interactive version update
python cli.py bump-version

# With version specification
python cli.py bump-version 1.0.0
```

## Debugging

### Logging

The application uses detailed logging:

- `core/logs/tenga_gui.log` - GUI logs
- `core/logs/tenga_cli.log` - CLI logs
- `core/logs/xray.log` - xray-core logs

### Environment Variables

- `TENGA_CONFIG_DIR` - configuration directory
- `XDG_CONFIG_HOME` - standard XDG configuration directory

## Making Changes

When making changes:

1. **Update tests** if necessary
2. **Check formatting and linting**
3. **Ensure all tests pass**
4. **Update documentation** if necessary