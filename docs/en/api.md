# API Documentation

## API Overview

Tenga Proxy provides a modular architecture with well-defined interfaces between components. This section describes the main classes and modules that may be useful for extending functionality or integrating with the application.

## Main Modules

### Core (src/core/)

#### AppContext

The central application class managing all main dependencies and state:

```python
from src.core import AppContext, init_context, get_context

# Initialize context
context = init_context()

# Get global context
context = get_context()
```

**Main properties:**
- `config` - application settings
- `profiles` - profile manager
- `xray_manager` - xray-core management
- `proxy_state` - proxy state
- `monitor` - connection monitoring

#### XrayManager

Class for managing xray-core:

```python
from src.core.xray_manager import XrayManager

manager = XrayManager(binary_path=None)
success, error = manager.start(config)
```

### Profiles (src/db/)

#### ProfileManager

Profile and group manager:

```python
from src.db.profiles import ProfileManager

profiles = context.profiles  # from application context
profile = profiles.add_profile(bean)
```

#### ProfileEntry

Individual profile:

```python
from src.db.profiles import ProfileEntry

# Profile properties
profile.id
profile.name
profile.proxy_type
profile.bean  # connection settings object
```

### Formatting (src/fmt/)

#### ProxyBean

Base class for all protocols:

```python
from src.fmt.base import ProxyBean

class MyProtocolBean(ProxyBean):
    @property
    def proxy_type(self):
        return "myprotocol"
    
    def build_outbound(self, skip_cert=False):
        # Build xray-core configuration
        pass
```

### GUI (src/ui/)

#### TengaApp

Main GUI application:

```python
from src.ui.app import TengaApp

app = TengaApp(context)
app.run()
```

## Key Classes and Methods

### AppContext

Application state management class:

- `init_context()` - initialize global context
- `get_context()` - get global context
- `config_dir` - configuration directory
- `profiles` - profile manager
- `xray_manager` - xray-core manager
- `proxy_state` - proxy state
- `find_xray_binary()` - find xray-core binary

### ProfileManager

Profile management class:

- `add_profile(bean, group_id=None)` - add profile
- `get_profile(profile_id)` - get profile by ID
- `get_profiles_in_group(group_id)` - get profiles in group
- `remove_profile(profile_id)` - remove profile
- `load()` - load profiles from files
- `save()` - save profiles to files

### ProxyBean

Base class for all protocols:

- `proxy_type` - protocol type
- `display_name` - display name
- `display_address` - display address
- `to_share_link()` - create share link
- `try_parse_link(link)` - try to parse link
- `build_outbound(skip_cert=False)` - build outbound configuration
- `build_core_obj_xray(skip_cert=False)` - build full xray-core configuration

## Extending Functionality

### Adding New Protocol

To add a new protocol:

1. Create a class inheriting from `ProxyBean`
2. Implement abstract methods
3. Add support to parsers
4. Update documentation

### Integration with External Systems

The application provides API for integration:

- Through `AppContext` you can access all main components
- The `src.sys` module contains system utilities
- The `src.sub` module contains subscription functions

## API Usage Examples

### Creating Profile Programmatically

```python
from src import init_context
from src.fmt.protocols import VLESSBean

context = init_context()

# Create VLESS profile
bean = VLESSBean()
bean.try_parse_link("vless://...")

# Add to profiles
profile = context.profiles.add_profile(bean)
context.profiles.save()
```

### Running Proxy Programmatically

```python
from src import init_context

context = init_context()

# Create configuration
config = bean.build_core_obj_xray()["outbound"]

# Start xray-core
success, error = context.xray_manager.start(config)
```

## System Utilities

### System Proxy Management

```python
from src.sys.proxy import set_system_proxy, clear_system_proxy

# Set system proxy
set_system_proxy(http_port=2080, socks_port=2080)

# Clear system proxy
clear_system_proxy()
```

### VPN Management

```python
from src.sys.vpn import connect_vpn, disconnect_vpn, is_vpn_active

# Connect to VPN
connect_vpn("connection_name")

# Check VPN status
active = is_vpn_active("connection_name")

# Disconnect from VPN
disconnect_vpn("connection_name")
```