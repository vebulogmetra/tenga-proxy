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

Support for the classic Shadowsocks protocol:

- Modern encryption methods (including 2022)
- Compatibility with original implementation
- AEAD encryption support

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

HTTP/2 transport with multiplexing support:

- Fast connection establishment
- Efficient resource usage
- TLS compatibility

## Protocol Configuration

Each protocol can be configured with various parameters:

- **Security** - TLS, REALITY, none
- **Encryption** - various algorithms
- **Transport** - TCP, WebSocket, gRPC, etc.
- **Additional parameters** - SNI, ALPN, etc.