# GUI

Tenga Proxy's graphical interface provides convenient management of proxy connections through the system tray and main application window.

## Running GUI

```bash
python gui.py
```

## Main Window

The main application window contains the following elements:

- **System tray** with quick connect/disconnect
- **Profile management** - view, add, edit, and delete profiles
- **DNS, VPN, and routing settings** - flexible connection configuration
- **Connection statistics and latency** - performance monitoring

## "Profiles" Tab

On the "Profiles" tab you can:

- Browse profile lists grouped by categories
- Add new profiles from share links
- Edit existing profiles
- Delete unwanted profiles
- Test server latency
- Connect to selected profile

## "Subscriptions" Tab

On the "Subscriptions" tab you can:

- Add new subscriptions
- Update existing subscriptions
- Edit subscription parameters
- Delete subscriptions

## "Monitoring" Tab

The "Monitoring" tab displays:

- Proxy connection status
- VPN connection status (if used)
- Last check time
- Manual connection check capability

The proxy status is not "the core process is running" but the result of a
request through the profile's server: the application reaches the test URL via
a service inbound of the core on `127.0.0.1`, protected by a one-time password.
Routing rules do not apply to this request, so "server does not respond" means
the server itself, even when the test URL is on your direct list.

### Failover

Settings → Monitoring has an automatic failover switch (off by default). After
the configured number of failed checks in a row the application connects
another profile of the same group — the one with the lowest measured latency
first — and tells you with a notification. It does not return to a profile that
has just stopped responding for 15 minutes. When no suitable profile is left
the connection is kept: traffic must not suddenly go direct.

### Core updates

Settings → About shows the xray core version and a "core update" row. Every
three days, and on the "Check" button, the application asks GitHub for the
release list and tells you when a newer version is out. It never downloads or
replaces the core itself.

## System Tray

The icon shows the connection state with three distinct glyphs: a crossed-out
circle when disconnected, a dashed ring while connecting, and a filled circle
when connected.

The tray uses `StatusNotifierItem`. GNOME needs an extension that displays such
items (AppIndicator/Tray Icons, for example); without one the application runs
as usual, just without a panel icon. Pass `--no-tray` to disable the icon.

The system tray icon allows you to:

- Quickly connect/disconnect from the current profile
- Select a profile to connect to
- Add new profiles
- Open the main application window
- Open settings
- Exit the application

## Application Settings

In settings you can:

- Configure proxy port
- Configure DNS servers
- Configure routing parameters
- Configure monitoring parameters
- Configure VPN integration parameters

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Return` | Connect or disconnect |
| `Ctrl+T` | Test latency |
| `Ctrl+N` | Add profile |
| `Ctrl+Shift+N` | Add subscription |
| `F5` | Refresh subscriptions |
| `Ctrl+F` | Search |
| `Ctrl+,` | Settings |
| `Ctrl+W` | Hide window |
| `Ctrl+Q` | Quit |

The full list is available from the "☰" menu → "Keyboard Shortcuts".

## Appearance

The interface follows the GNOME HIG and uses the system theme: light and dark
come from the desktop settings, there is no separate switch in the application.

The window is adaptive. Below 550 points wide the view switcher moves from the
header bar to the bottom, so the application stays usable in a narrow window.
