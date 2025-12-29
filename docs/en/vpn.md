# VPN

Tenga Proxy provides integration with VPN connections for comprehensive network traffic management.

## Key Features

- **Automatic VPN connection** before starting proxy
- **Traffic routing through VPN** for specific domains/IPs
- **NetworkManager integration** for managing VPN connections
- **Automatic VPN disconnection** after stopping proxy

## VPN Integration Settings

### In Profile

Each profile can have individual VPN settings:

- **Enable/disable integration** - global enable/disable VPN integration for profile
- **Connection name** - VPN connection name in NetworkManager
- **Auto-connect** - automatic VPN connection before starting proxy
- **Interface** - specifying specific interface for direct traffic

### In Routing

VPN integration works together with routing system:

- **"Over VPN" list** - domains and IPs whose traffic is routed through VPN
- **Route priority** - proper sequence of rule processing
- **Interface settings** - directing traffic through the required interface

## Supported VPN Types

Tenga Proxy supports VPN connections managed through NetworkManager:

- **OpenVPN** - via .ovpn files
- **WireGuard** - via configuration files
- **IPsec/L2TP** - corporate VPN
- **PPTP** - legacy but still used
- **System VPN** - any VPN configured in NetworkManager

## Auto Connection

### When Starting Proxy

If auto-connection is enabled:

1. VPN connection status is checked
2. If connection is not active, connection is performed
3. After successful connection, proxy is started
4. When stopping proxy, VPN disconnection may be performed

### Status Checking

The system checks VPN connection status:

- **Connection activity** - checking through NetworkManager
- **Connection interface** - determining the used interface
- **VPN DNS servers** - getting DNS servers from VPN settings

## Routing Through VPN

### Routing Rules

Traffic can be directed through VPN based on rules:

- **Domain names** - directing traffic to specific domains through VPN
- **IP addresses** - directing traffic to specific IP addresses through VPN
- **Geolocation** - potential ability to direct traffic by geographic location

### DNS Integration

When using VPN for specific domains:

- **VPN DNS servers** - using DNS servers from VPN connection
- **Name resolution** - proper direction of DNS requests
- **Leak prevention** - preventing DNS request leaks

## GUI Settings

### In Profile Window

In profile settings you can:

- Enable/disable VPN integration
- Select VPN connection from list
- Enable auto-connection
- Specify interface for direct traffic

### In Routing Settings

In routing settings:

- Configure "over VPN" lists
- Define rule priority
- Test routes