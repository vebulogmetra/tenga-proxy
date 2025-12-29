# Routing

Routing in Tenga Proxy allows flexible management of network traffic direction through various connection channels.

## Routing Modes

### Proxy All Traffic (PROXY_ALL)

In this mode, all traffic is routed through the proxy server:

- All connections go through the configured proxy
- Option to exclude local networks
- Suitable for complete traffic anonymization

### Custom Routing (CUSTOM)

Allows manual configuration of routing rules:

- Direct connection list (DIRECT)
- VPN connection list (VPN)
- Proxy connection list (PROXY)
- Option to configure rule priority

## Routing Lists

### Direct Connections (DIRECT)

List of domains and IP addresses whose traffic:

- Does not go through proxy
- Uses direct connection
- Suitable for local resources and internal services

### VPN Connections (VPN)

List of domains and IP addresses whose traffic:

- Is routed through VPN connection
- Uses VPN interface
- Suitable for resources requiring VPN access

### Proxy Connections (PROXY)

List of domains and IP addresses whose traffic:

- Is routed through main proxy
- Uses configured proxy parameters
- Suitable for anonymization and bypassing blocks

## Entry Formats

### Domain Names

- `example.com` - specific domain
- `*.example.com` - domain subdomains
- `domain:example.com` - domain type specification

### IP Addresses and Subnets

- `192.168.1.1` - specific IP address
- `192.168.1.0/24` - subnet
- `geoip:cn` - geographic location (if supported)

### Patterns and Masks

- Support for various formats
- Regular expression support
- Compatibility with popular subscription formats

## Rule Priority

Order of routing rule processing:

1. **More specific rules** - have higher priority
2. **Order in configuration** - rules are processed in definition order
3. **Rule types** - may have different priority depending on settings

## GUI Configuration

### In Profile Settings

In profile settings you can:

- Select routing mode
- Configure lists for each connection type
- Define rule priority
- Test routes

### In Application Settings

In application settings:

- Global routing settings
- Templates for new profiles
- Common exclusion lists

## Configuration Examples

### Simple Example

```
DIRECT: 192.168.0.0/16, 10.0.0.0/8, localhost
PROXY: *.google.com, *.youtube.com
VPN: *.company.com
```

### Complex Example

```
DIRECT: geoip:private, domain:local, domain:localhost
PROXY: geosite:geolocation-!cn
VPN: domain:restricted-site.com, 10.10.10.0/24
```

## Routing Testing

### Built-in Tools

- Domain availability testing
- Traffic direction checking
- Connection monitoring

### External Tools

- Using traceroute
- Checking IP addresses via web services
- Network traffic analysis