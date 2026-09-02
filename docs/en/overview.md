# Project Overview

Tenga Proxy is a modern Linux proxy client with [xray-core](https://github.com/XTLS/Xray-core) backend that provides a convenient interface for working with various proxy protocols.

## Project Purpose

The project is created for:

- **Simplifying proxy server work** - provides a convenient interface for various protocols
- **Ensuring anonymity** - allows hiding the real IP address
- **Bypassing blocks** - provides access to blocked resources
- **Traffic management** - flexible network traffic routing
- **VPN integration** - comprehensive network connection management

## Architecture

### General Architecture

Tenga Proxy uses an architecture with separation into:

- **Interface** - CLI and GUI for user interaction
- **Application core** - management logic and coordination
- **Formatting modules** - link parsing and formatting
- **Data manager** - profile storage and management
- **Backend** - xray-core for network traffic processing

### Main Components

- **AppContext** - central application context
- **ProfileManager** - profile and group management
- **XrayManager** - xray-core management
- **ProxyState** - proxy state tracking
- **ConnectionMonitor** - connection monitoring

## Functional Capabilities

### Protocol Support

- **VLESS** - modern protocol with Reality and XTLS support
- **Trojan** - high-security protocol
- **VMess** - V2Ray compatibility
- **Shadowsocks** - classic protocol with modern methods
- **SOCKS** - standard SOCKS4/4a/5 protocols
- **HTTP/HTTPS** - HTTP proxies

### Profile Management

- **Profile creation** from share links
- **Profile grouping** by categories
- **Subscription import** in various formats
- **Server latency testing** 
- **Connection parameter editing**

### Traffic Routing

- **Flexible routing rules** for different traffic types
- **VPN integration** for comprehensive management
- **DNS configuration** for different routes
- **Local network exclusion** from proxy

### System Integration

- **System tray** for quick access
- **Automatic system proxy setup** for GNOME/KDE
- **Notifications** about connection status
- **Monitoring** via Stats API

## Advantages

### For Users

- **Ease of use** - intuitive interface
- **Multifunctionality** - support for various protocols
- **Flexibility** - configurable routing rules
- **Reliability** - stable operation with xray-core

### For Developers

- **Modular architecture** - easy feature extension
- **Clean code** - following Python standards
- **Testing** - coverage of main scenarios
- **Documentation** - detailed API and architecture description

## Technologies

### Backend

- **xray-core** - main traffic processing engine
- **Python 3.11+** - implementation language
- **GTK 4 + libadwaita 1.5** - graphical interface following the GNOME HIG

### Development Tools

- **uv** - package manager
- **ruff** - linter and formatter
- **pytest** - testing framework
- **pyinstaller** - AppImage building

## Community

- **Open source** - MIT license
- **Contributions welcome** - Pull Requests and Issues
- **Documentation** - in Russian and English
- **Support** - via GitHub Issues

