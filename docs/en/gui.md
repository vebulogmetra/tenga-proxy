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
