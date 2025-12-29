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