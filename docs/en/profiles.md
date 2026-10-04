# Profiles

Profile management in Tenga Proxy allows you to efficiently organize and use various proxy connection settings.

## Basic Concepts

**Profile** - a saved configuration for connecting to a proxy server, containing:

- Connection parameters (server, port, credentials)
- Transport settings
- Security parameters
- Name and description

**Group** - a collection of profiles united by some characteristic (e.g., by provider or usage type).

## Creating Profiles

### From Share Links

Profiles can be created from share links of various protocols:

```bash
# CLI
python cli.py add "vless://..."

# GUI
# Use the "Add" button in the main window
```

### From Subscriptions

Profiles can be automatically created from subscriptions:

- Subscriptions can be base64, plain text or a ready xray config (JSON)
- Profiles are grouped into special subscription groups
- Subscriptions are updated manually only: the button in the subscription row or `F5`

#### What an update does

- A profile still present in the provider's response (same name, type, server
  and port) is updated in place: its latency, per-profile routing and VPN
  settings are kept, and a connected profile stays connected. Profiles missing
  from the response are removed. An empty response changes nothing.
- When a profile is connected in system proxy mode, the subscription is fetched
  through it first and directly on failure. In TUN mode application requests
  already go through the tunnel. Requests through the local proxy follow
  the application's routing rules.
- The subscription name is optional: the host of the address is used, and the
  provider may replace it with its own (`profile-title`). A name typed by the
  user is never replaced.

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

#### Settings → Subscriptions

- **User-Agent.** `v2rayNG/1.8.23` by default for compatibility with providers.
- **Send device information.** Off. When enabled, the provider receives a random
  installation identifier (`x-hwid`), the OS name and version and the computer
  model. Needed by providers that enforce a device limit: without it they
  answer 403.

## Profile Management

### Viewing Profiles

In GUI, profiles are displayed as a tree with groups:

- Groups are displayed as folders
- Profiles within groups
- Information about type, address, and latency

### Editing Profiles

Profiles can be edited:

- Changing profile name
- Adjusting connection parameters
- Changing transport settings
- Configuring VPN and routing

### Deleting Profiles

Profiles can be deleted:

- Deleting individual profiles
- Deleting entire groups
- Deleting profiles from subscriptions

## Profile Groups

### Regular Groups

Regular groups allow you to:

- Organize profiles by category
- Quickly switch between groups
- Manage profiles within a group

### Subscription Groups

Groups created from subscriptions:

- Automatically updated
- Synchronized with source
- Cannot be renamed manually

## Latency Testing

For each profile, you can test latency:

- Measuring server response time
- Comparing profile performance
- Automatic result updates

A group is measured by one temporary core process: every profile gets its own
inbound on `127.0.0.1` with a one-time password, and results appear as they
arrive. Latency is the median of three requests to the test URL through the
profile's server. A dash instead of a number means one of three things: the
profile could not be built, the core rejected its settings, or the server did
not respond.

## Profile Settings

Each profile can have individual settings:

- **VPN integration** - VPN connection settings
- **Routing** - traffic routing rules
- **Security parameters** - TLS and encryption settings
- **Additional parameters** - custom settings