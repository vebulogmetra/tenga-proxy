# Servers

Server management in Veblock allows you to efficiently organize and use various proxy connection settings.

## Basic Concepts

**Server** - a saved configuration for connecting to a proxy server, containing:

- Connection parameters (address, port, credentials)
- Transport settings
- Security parameters
- Name and description

**Group** - a collection of servers united by some characteristic (e.g., by provider or usage type).

## Creating Servers

### From Share Links

Servers can be created from share links of various protocols:

```bash
# CLI
python cli.py add "vless://..."

# GUI
# Use the "Add" button in the main window
```

### From Subscriptions

Servers can be automatically created from subscriptions:

- Subscriptions can be base64, plain text or a ready xray config (JSON)
- Servers are grouped into special subscription groups
- Subscriptions are updated manually only: the button in the subscription row or `F5`

#### What an update does

- A server still present in the provider's response (same name, type, server
  and port) is updated in place: its latency, per-profile routing and VPN
  settings are kept, and a connected server stays connected. Servers missing
  from the response are removed. An empty response changes nothing.
- When a server is connected in system proxy mode, the subscription is fetched
  through it first and directly on failure. In TUN mode application requests
  already go through the tunnel. Requests through the local proxy follow
  the application's routing rules.
- The subscription name is optional: the host of the address is used, and the
  provider may replace it with its own (`profile-title`) and keep updating it.
  A name typed or changed by the user is never replaced.

#### Provider information

Read from response headers and from `#key: value` lines in the body:

| Key | What is shown |
|---|---|
| `subscription-userinfo` | used traffic, limit and expiry date |
| `announce` | provider announcement (the "i" button in the subscription row) |
| `support-url` | "Support" menu item (http, https or tg) |
| `profile-web-page-url` | "Subscription page" menu item (https only) |
| `profile-title` | subscription name, unless the user set one |
| `new-url`, `fallback-url` | an offer to change the address, applied only after confirmation |

A value may be encoded with the `base64:` prefix. Keys that would let the
provider control client settings are not recognised.

A successful response sets the announcement and links as a whole: if the
provider removes them, they disappear from the app as well. A failed update
changes nothing. If the subscription answers with no servers at all (as the
panel does for an expired user), the saved servers are kept and the
subscription row shows "Пустой список серверов" (empty server list); the
announcement and renewal link from that response are still available.

#### Settings → Subscriptions

- **User-Agent.** `v2rayNG/1.8.23` by default for compatibility with providers.
- **Send device information.** Off. When enabled, the provider receives a random
  installation identifier (`x-hwid`), the OS name and version and the computer
  model. Needed by providers that enforce a device limit: without it they
  answer 403.

## Server Management

### Viewing Servers

In GUI, servers are displayed as a tree with groups:

- Groups are displayed as folders
- Servers within groups
- Information about type, address, and latency

### Editing Servers

Servers can be edited:

- Changing server name
- Adjusting connection parameters
- Changing transport settings
- Configuring VPN and routing

### Deleting Servers

Servers can be deleted:

- Deleting individual servers
- Deleting entire groups
- Deleting servers from subscriptions

## Server Groups

### Regular Groups

Regular groups allow you to:

- Organize servers by category
- Quickly switch between groups
- Manage servers within a group

### Subscription Groups

Groups created from subscriptions:

- Automatically updated
- Synchronized with source
- Cannot be renamed manually

## Latency Testing

For each server, you can test latency:

- Measuring server response time
- Comparing server performance
- Automatic result updates

A group is measured by one temporary core process: every server gets its own
inbound on `127.0.0.1` with a one-time password, and results appear as they
arrive. Latency is the median of three requests to the test URL through the
server itself. A dash instead of a number means one of three things: the
server could not be built, the core rejected its settings, or the server did
not respond.

## Server Settings

Each server can have individual settings:

- **VPN integration** - VPN connection settings
- **Routing** - traffic routing rules
- **Security parameters** - TLS and encryption settings
- **Additional parameters** - custom settings