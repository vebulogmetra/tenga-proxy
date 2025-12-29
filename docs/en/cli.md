# CLI

Tenga Proxy's command-line interface provides extensive capabilities for managing proxy connections.

## Link Parsing

```bash
# Parse share link with information output
python cli.py parse "vless://..."

# Parse with JSON configuration output for xray-core
python cli.py parse "vless://..." -f json
```

## Working with Subscriptions

```bash
# Download and parse subscription (profile list)
python cli.py sub "https://example.com/subscription"

# Output subscription in JSON format
python cli.py sub "https://example.com/subscription" -f json
```

## Configuration Generation

```bash
# Generate xray-core configuration from share link
python cli.py gen "vless://..." -o config.json

# Generate with specified proxy port
python cli.py gen "vless://..." -p 8080 -o config.json
```

## Profile Management

```bash
# Add profile
python cli.py add "vless://..."

# Show list of saved profiles
python cli.py ls

# Remove profile by ID
python cli.py rm 1
```

## Running Proxy

```bash
# Run proxy from share link
python cli.py run "vless://..."

# Run proxy by number from list (ls)
python cli.py run 1

# Run proxy by profile ID
python cli.py run 123

# Run proxy by profile name
python cli.py run "My Profile"

# Run on specified port (default 2080)
python cli.py run 1 -p 8080

# Run without automatic system proxy setup
python cli.py run 1 --no-system-proxy

# Run from file (path to file with share link)
python cli.py run /path/to/link.txt
```

## Version Information

```bash
# Show application and xray-core version
python cli.py ver
```

## Build and Installation

```bash
# Build and install AppImage
python cli.py setup

# Build AppImage only
python cli.py build

# Install AppImage in system
python cli.py install

# Uninstall AppImage from system
python cli.py install --uninstall

# Install development environment
python cli.py setup-dev

# Update project version
python cli.py bump-version 0.9.0
```

## Code Checking and Formatting

```bash
# Check code with linter
python cli.py lint

# Fix automatically fixable issues
python cli.py lint --fix

# Format code
python cli.py format

# Check formatting without changes
python cli.py format --check

# Run all checks (linting + formatting)
python cli.py lint-all
```

## Help

```bash
# Show general help
python cli.py --help

# Show help for specific command
python cli.py run --help
python cli.py parse --help
python cli.py build --help
python cli.py lint --help
```

## Quick Proxy Start

```bash
# 1. Add profile from share link
python cli.py add "vless://..."

# 2. View profile list
python cli.py ls

# 3. Run proxy (by sequence number from list)
python cli.py run 1

# 4. Check proxy operation
curl -x socks5://127.0.0.1:2080 https://ifconfig.me
curl -x http://127.0.0.1:2080 https://ifconfig.me

# 5. Stop proxy: press Ctrl+C
```

**Note:** By default, CLI automatically configures the system proxy. If you need to run only a local proxy without changing system settings, use the `--no-system-proxy` flag.