# GUI

Veblock's graphical interface provides convenient management of proxy connections through the system tray and main application window.

## Running GUI

```bash
python gui.py
```

## Main Window

The main application window contains the following elements:

- **System tray** with quick connect/disconnect
- **Server management** - view, add, edit, and delete servers
- **DNS, VPN, and routing settings** - flexible connection configuration
- **Connection statistics and latency** - performance monitoring

## "Servers" Tab

On the "Servers" tab you can:

- Browse server lists grouped by categories
- Add new servers from share links
- Edit existing servers
- Delete unwanted servers
- Test server latency
- Connect to selected server

## "Subscriptions" Tab

On the "Subscriptions" tab you can:

- Add new subscriptions
- Update existing subscriptions
- Edit subscription parameters
- Delete subscriptions

## "Diagnostics" Tab

The "Diagnostics" tab displays:

- Proxy connection status
- VPN connection status (if used)
- Last check time
- Manual connection check capability

The proxy status is not "the core process is running" but the result of a
request through the server itself: the application reaches the test URL via
a service inbound of the core on `127.0.0.1`, protected by a one-time password.
Routing rules do not apply to this request, so "server does not respond" means
the server itself, even when the test URL is on your direct list.

### Failover

Settings → Monitoring has an automatic failover switch (off by default). After
the configured number of failed checks in a row the application connects
another server of the same group — the one with the lowest measured latency
first — and tells you with a notification. It does not return to a server that
has just stopped responding for 15 minutes. When no suitable server is left
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

- Quickly connect/disconnect from the current server
- Select a server to connect to
- Add new servers
- Open the main application window
- Open settings
- Exit the application

## Application Settings

In settings you can:

- Configure proxy port
- Block traffic on connection loss (TUN mode on Linux only, see [routing](routing.md))
- Configure DNS servers
- Configure routing parameters
- Configure monitoring parameters
- Configure VPN integration parameters

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Return` | Connect or disconnect |
| `Ctrl+T` | Test latency |
| `Ctrl+N` | Add server |
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


## Windows window (Qt)

The connection panel stays on the left. Click the monolith to connect or
disconnect; it is disabled during an operation. Teal indicates a running session,
orange an operation, and red an error. The separate health message reports whether
connectivity has actually been checked.

The right side contains search, add and sorting menus, groups and two-line server
rows. The active server has a teal marker and a Connected label. Selecting another
row does not switch the session: use the explicit switch action below the list,
where the target name is displayed. Enter and double-click retain their connection
action.

Diagnostics replaces the right pane with connection status, routing and the log.
Back to Servers restores search, selection and scrolling. Log refresh runs only
while visible; export masks secrets, and clearing requires confirmation. Network
diagnostics remains a separate action.

Settings opens a separate window with the six existing sections and automatic
saving. Its footer distinguishes pending changes, a successful write and errors.
Invalid values are not written. Runtime changes need an explicit reconnect; theme
changes apply immediately. TUN fields are hidden in system proxy mode while their
values are preserved. Light, dark and system themes remain available.

[Synthetic main window](../design/windows-ui/main-dark-1180.png),
[diagnostics](../design/windows-ui/diagnostics.png),
[settings](../design/windows-ui/settings.png).
The tab navigation described above applies to GTK on Linux.
