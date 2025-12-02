import os
import subprocess
from pathlib import Path
from typing import List, Tuple


def _is_kde() -> bool:
    """Check if KDE is used"""
    session = os.environ.get("XDG_SESSION_DESKTOP", "")
    return session in ("KDE", "plasma")


def _get_config_path() -> Path:
    """Get configuration path"""
    config_home = os.environ.get('XDG_CONFIG_HOME')
    if config_home:
        return Path(config_home)
    return Path.home() / '.config'


def _execute_command(program: str, args: List[str]) -> bool:
    """Execute command"""
    try:
        result = subprocess.run(
            [program] + args,
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except Exception as e:
        print(f"Error executing {program}: {e}")
        return False


def set_system_proxy(http_port: int = 0, socks_port: int = 0, address: str = "127.0.0.1") -> bool:
    """
    Set system proxy
    
    Args:
        http_port: HTTP proxy port (0 = don't use)
        socks_port: SOCKS proxy port (0 = don't use)
        address: Proxy server address
        
    Returns:
        True if successful
    """
    has_http = 0 < http_port < 65536
    has_socks = 0 < socks_port < 65536
    
    if not has_http and not has_socks:
        print("Nothing to set")
        return False
    
    actions: List[Tuple[str, List[str]]] = []
    is_kde = _is_kde()
    config_path = _get_config_path()

    if not is_kde:
        # GNOME
        actions.append(("gsettings", ["set", "org.gnome.system.proxy", "mode", "manual"]))
    else:
        # KDE
        actions.append(("kwriteconfig5", [
            "--file", str(config_path / "kioslaverc"),
            "--group", "Proxy Settings",
            "--key", "ProxyType", "1"
        ]))
    
    # HTTP proxy
    if has_http:
        for protocol in ["http", "ftp", "https"]:
            if not is_kde:
                # GNOME
                actions.append(("gsettings", [
                    "set", f"org.gnome.system.proxy.{protocol}", "host", address
                ]))
                actions.append(("gsettings", [
                    "set", f"org.gnome.system.proxy.{protocol}", "port", str(http_port)
                ]))
            else:
                # KDE
                actions.append(("kwriteconfig5", [
                    "--file", str(config_path / "kioslaverc"),
                    "--group", "Proxy Settings",
                    "--key", f"{protocol}Proxy",
                    f"http://{address} {http_port}"
                ]))
    
    # SOCKS proxy
    if has_socks:
        if not is_kde:
            # GNOME
            actions.append(("gsettings", [
                "set", "org.gnome.system.proxy.socks", "host", address
            ]))
            actions.append(("gsettings", [
                "set", "org.gnome.system.proxy.socks", "port", str(socks_port)
            ]))
        else:
            # KDE
            actions.append(("kwriteconfig5", [
                "--file", str(config_path / "kioslaverc"),
                "--group", "Proxy Settings",
                "--key", "socksProxy",
                f"socks://{address} {socks_port}"
            ]))
    
    # Notify KDE to reload configuration
    if is_kde:
        actions.append(("dbus-send", [
            "--type=signal", "/KIO/Scheduler",
            "org.kde.KIO.Scheduler.reparseSlaveConfiguration",
            "string:''"
        ]))
    
    # Execute all commands
    results = []
    for program, args in actions:
        success = _execute_command(program, args)
        results.append(success)
        if not success:
            print(f"Failed: {program} {' '.join(args)}")
    
    success_count = sum(results)
    if success_count != len(actions):
        print(f"Some commands failed: {success_count}/{len(actions)}")
        return False
    
    return True


def clear_system_proxy() -> bool:
    """
    Clear system proxy
    
    Returns:
        True if successful
    """
    actions: List[Tuple[str, List[str]]] = []
    is_kde = _is_kde()
    config_path = _get_config_path()
    
    # Set proxy mode to none
    if not is_kde:
        # GNOME
        actions.append(("gsettings", ["set", "org.gnome.system.proxy", "mode", "none"]))
    else:
        # KDE
        actions.append(("kwriteconfig5", [
            "--file", str(config_path / "kioslaverc"),
            "--group", "Proxy Settings",
            "--key", "ProxyType", "0"
        ]))
    
    # Notify KDE to reload configuration
    if is_kde:
        actions.append(("dbus-send", [
            "--type=signal", "/KIO/Scheduler",
            "org.kde.KIO.Scheduler.reparseSlaveConfiguration",
            "string:''"
        ]))
    
    # Execute all commands
    results = []
    for program, args in actions:
        success = _execute_command(program, args)
        results.append(success)
    
    return all(results)
