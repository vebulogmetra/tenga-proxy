# Protocols

Tenga Proxy supports a wide range of proxy protocols to ensure compatibility with various servers and services.

## Supported Protocols

### VLESS

VLESS is a next-generation protocol designed for Xray. Supports:

- **Reality** - DPI protection using TLS
- **XTLS** - efficient data transfer
- Various transport protocols (TCP, WebSocket, gRPC, etc.)

### Trojan

The Trojan protocol provides high security:

- TLS support
- HTTP/HTTPS compatibility
- DPI protection

### VMess

The VMess protocol from V2Ray with support for:

- AES and ChaCha20 encryption
- Authentication via UUID
- V2Ray compatibility

### Shadowsocks

SIP002 and legacy links (credentials and server address encoded together in
base64), and percent-encoded Shadowsocks 2022 keys are supported.

- AEAD: `aes-128-gcm`, `aes-256-gcm`, `chacha20-poly1305`,
  `chacha20-ietf-poly1305`, `xchacha20-poly1305`, `xchacha20-ietf-poly1305`.
- Shadowsocks 2022: `2022-blake3-aes-128-gcm`, `2022-blake3-aes-256-gcm`,
  `2022-blake3-chacha20-poly1305`. Key lengths are validated on import.
- Stream ciphers, `none`, `plain`, and SIP003 plugins are unsupported.

### Hysteria2

Hysteria2 (`hysteria2://` and `hy2://`) supports TLS, salamander obfuscation,
and `fm` (finalmask) settings.

- Port hopping: multiple ports or ranges in the address, such as
  `server:443,20000-50000`, or `mport=20000-50000`.
- Interval: `hop-interval=30` (also `hopInterval`), a number or range in
  seconds, at least 5; defaults to 30 seconds.
- Brutal: `upmbps` enables the algorithm and sets upload bandwidth in Mbps;
  `downmbps` sets download bandwidth. Explicit `fm` settings are preserved.

### SOCKS

Support for standard SOCKS protocols:

- **SOCKS4** - basic version
- **SOCKS4a** - with DNS support
- **SOCKS5** - full version with authentication

### HTTP/HTTPS

HTTP proxy support:

- HTTP proxy with authentication
- HTTPS proxy
- Web browser compatibility

## Link Formats

### VLESS

```
vless://UUID@server:port?encryption=none&security=tls&alpn=http/1.1#Name
```

### Trojan

```
trojan://password@server:port#Name
```

### VMess

```
vmess://base64_encoded_json_config
```

### Shadowsocks

```
ss://base64(method:password)@server:port#Name
```

### SOCKS

```
socks://server:port#Name
```

## Transport Protocols

### TCP

Standard TCP transport with HTTP obfuscation support.

### WebSocket

WebSocket transport for bypassing blocks:

- TLS support
- Path configuration
- CDN compatibility

### gRPC

gRPC transport for high performance:

- Multiplexing support
- Efficient connection usage
- HTTP/2 compatibility

### HTTP/2

The standalone `h2` transport was removed from xray-core and is unsupported.
HTTP/2 in gRPC and XHTTP continues to work. For WebSocket and HTTP Upgrade,
`h2` and `h3` are removed from ALPN when building the configuration; the
original share link is preserved.

## Protocol Configuration

Each protocol can be configured with various parameters:

- **Security** - TLS, REALITY, none
- **Encryption** - various algorithms
- **Transport** - TCP, WebSocket, gRPC, etc.
- **Additional parameters** - SNI, ALPN, etc.

`allowInsecure` has no effect: the core rejects this option. TLS certificate
verification remains enabled.

## Bypass settings

TLS fragmentation and mux are available under “Настройки” → “Обход блокировок”
(Settings → Bypass). Settings apply to connections and latency probes. Saving settings restarts an
active connection with the updated configuration.
Both switches are disabled by default.

Fragmentation applies to TLS or REALITY profiles, excluding Hysteria2 and
profiles with their own TCP masks. Defaults: ClientHello (`tlshello`),
`100-200` bytes per fragment, and `10-20` ms delay. Packet numbers (`1-3`),
length, and delay accept a number or range. Invalid values fall back to the
defaults. Effectiveness needs to be tested on your network.

Mux combines streams in one connection for VLESS and Trojan, excluding XHTTP,
SplitHTTP, and VLESS Vision. UDP on port 443 follows the normal protocol path,
bypassing mux.
