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

- Subscriptions can be in base64 or plain text format
- Profiles are grouped into special subscription groups
- Subscriptions can be updated manually or on schedule

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

## Profile Settings

Each profile can have individual settings:

- **VPN integration** - VPN connection settings
- **Routing** - traffic routing rules
- **Security parameters** - TLS and encryption settings
- **Additional parameters** - custom settings