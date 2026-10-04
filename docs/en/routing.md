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

One entry per line. An entry the core would not understand is skipped: a single
bad rule would otherwise break the whole connection.

### Domains

| Entry | Matches |
|---|---|
| `example.com` | the domain and all its subdomains |
| `*.example.com`, `.example.com` | the same |
| `full:example.com` | the domain itself only |
| `google` | any name containing the word (no dot means substring) |
| `keyword:video` | the same, explicitly |
| `regexp:^ads\d+\.example\.com$` | regular expression |
| `geosite:category-ru` | a category from geosite.dat |

### Addresses and Networks

| Entry | Matches |
|---|---|
| `192.168.1.1`, `2001:db8::1` | a single address |
| `192.168.1.0/24`, `fc00::/7` | a subnet |
| `geoip:ru` | a country from geoip.dat |

`geoip:private` is allowed in the Direct list only; private networks have a
ready-made rule (see below).

A category missing from the geo databases is skipped with a warning in the log.
The state of the databases is shown in Settings → About, next to the Update
button.

## Blocking

The Block list drops connections and makes names unresolvable (NXDOMAIN). It is
applied before all other lists, whatever the group order.

## Ready-made Rules

They come after the user lists: an explicit entry always wins.

- **Local networks direct** — `127.0.0.0/8`, `10.0.0.0/8`, `192.168.0.0/16` and
  other private ranges. On by default, works in both modes.
- **Russian sites and IPs direct** — `geosite:category-ru`,
  `geosite:category-gov-ru`, `geoip:ru`. Off by default, works in the lists
  mode. Requires geo databases.

## DNS

A name is resolved by the DNS of the network its traffic will use:

- Direct-list domains and Russian sites of the ready-made rule — your network's DNS;
- VPN-list domains — the VPN DNS server (queried through the VPN);
- Proxy-list domains and everything else — the DNS from settings (DoH through
  the proxy by default).

If the configured DNS is unreachable, names do not leak to the provider: the
system resolver serves its own domains only.

In TUN mode application queries are intercepted and handled by the same rules
(Settings → DNS → Intercept application DNS). On systems with systemd-resolved
this needs the installed route helper (`python cli.py install`); query types
other than A and AAAA are forwarded to your network's DNS unchanged.

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
DIRECT: geosite:category-ru, geoip:ru, domain:local
PROXY: geosite:google, blocked.example
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