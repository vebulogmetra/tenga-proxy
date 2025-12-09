from __future__ import annotations

import json
import logging
import signal
from pathlib import Path
from typing import Optional

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk

from src.core.config import GUI_LOG_FILE
from src.core.context import AppContext, get_context, init_context
from src.core.logging_utils import setup_logging as setup_core_logging
from src.core.monitor import ConnectionMonitor, ConnectionStatus
from src.db.config import RoutingMode
from src.db.profiles import ProfileEntry
from src.sys.proxy import clear_system_proxy, set_system_proxy
from src.sys.vpn import get_vpn_interface, is_vpn_active, connect_vpn, disconnect_vpn, get_default_interface, get_vpn_dns_servers
from src.ui.main_window import MainWindow
from src.ui.dialogs import show_add_profile_dialog, show_settings_dialog
from src.ui.tray import TrayIcon


logger = logging.getLogger("tenga.ui.app")


def setup_logging(context: AppContext) -> None:
    """Initialize logging for GUI."""
    setup_core_logging(GUI_LOG_FILE, level=logging.INFO)
    logger.info("GUI logging initialized, file: %s", GUI_LOG_FILE)


class TengaApp:
    """Main Tenga application."""
    
    def __init__(self, context: Optional[AppContext] = None, lock=None):
        self._context = context or get_context()
        self._lock = lock
        
        self._tray: Optional[TrayIcon] = None
        self._window: Optional[MainWindow] = None
        
        # Last selected profile
        self._last_profile_id: Optional[int] = None
        
        # Connection monitor
        self._monitor: Optional[ConnectionMonitor] = None
        self._setup_monitor()
        
        self._setup_signal_handlers()
    
    def _setup_monitor(self) -> None:
        """Setup connection monitor."""
        self._monitor = ConnectionMonitor(self._context)
        self._monitor.set_on_status_changed(self._on_monitoring_status_changed)
        self._context.set_monitor(self._monitor)
    
    def _on_monitoring_status_changed(
        self,
        previous: ConnectionStatus,
        current: ConnectionStatus,
    ) -> None:
        """Handle monitoring status changes."""
        if self._window:
            from gi.repository import GLib
            GLib.idle_add(
                self._window.update_monitoring_status,
                current.proxy_ok,
                current.vpn_ok,
                current.last_check_time,
                current.proxy_error,
                current.vpn_error,
            )
    
    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers."""
        signal.signal(signal.SIGINT, self._on_signal)
        signal.signal(signal.SIGTERM, self._on_signal)
    
    def _on_signal(self, signum: int, frame) -> None:
        """Signal handler."""
        logger.info("Received signal %s, terminating application", signum)
        if self._lock:
            self._lock.release()
        self.quit()
    
    def run(self) -> int:
        """Run application."""
        try:
            # Check sing-box
            singbox_path = self._context.find_singbox_binary()
            if not singbox_path:
                error_msg = (
                    "sing-box not found!\n\n"
                    "Solutions:\n"
                    "1. Install sing-box globally (see README.md)\n"
                    "2. Place sing-box binary in core/bin/\n"
                    "3. Run ./install.sh for automatic installation"
                )
                
                # Show error dialog
                dialog = Gtk.MessageDialog(
                    flags=0,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.OK,
                    text="sing-box не найден"
                )
                dialog.set_wmclass("tenga-proxy", "tenga-proxy")
                from gi.repository import Gdk
                dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
                dialog.set_skip_taskbar_hint(True)
                dialog.format_secondary_text(error_msg)
                dialog.run()
                dialog.destroy()
                
                logger.error("sing-box not found")
                return 1
            
            # Create tray
            self._tray = TrayIcon(self._context)
            self._tray.set_on_connect(self._on_tray_connect)
            self._tray.set_on_disconnect(self._on_disconnect)
            self._tray.set_on_select_profile(self._on_select_profile)
            self._tray.set_on_add_profile(self._on_add_profile)
            self._tray.set_on_show_window(self._on_show_window)
            self._tray.set_on_settings(self._on_settings)
            self._tray.set_on_quit(self.quit)
            # Create main window
            self._window = MainWindow(self._context)
            self._window.set_on_connect(self._on_connect)
            self._window.set_on_disconnect(self._on_disconnect)
            self._window.set_on_config_reload(self._reload_config)
            # Show window on startup
            self._window.show_all()
            # Start GTK main loop
            logger.info("Starting GTK main loop")
            Gtk.main()
            
            logger.info("GTK main loop finished")
            return 0
            
        except Exception as e:
            logger.exception("Unhandled exception in TengaApp.run: %s", e)
            return 1
        finally:
            if self._lock:
                self._lock.release()
    
    def quit(self) -> None:
        """Quit application."""
        # Disconnect proxy
        if self._context.proxy_state.is_running:
            self._disconnect()
        # Save configuration
        self._context.save_all()
        # Cleanup resources
        if self._tray:
            self._tray.cleanup()
        if self._window:
            pass
        # Quit GTK
        Gtk.main_quit()
    
    def _on_tray_connect(self) -> None:
        """Connect from tray (uses last profile)."""
        profile_id = self._last_profile_id
        
        if profile_id is None:
            # Take first profile
            profiles = self._context.profiles.get_current_group_profiles()
            if profiles:
                profile_id = profiles[0].id
        
        if profile_id is not None:
            self._connect(profile_id)
        else:
            self._tray.show_notification("Tenga", "No available profiles")
    
    def _on_connect(self, profile_id: int) -> None:
        """Connect to profile."""
        self._connect(profile_id)
    
    def _on_disconnect(self) -> None:
        """Disconnect."""
        self._disconnect()
    
    def _on_select_profile(self, profile_id: int) -> None:
        """Select profile and connect."""
        self._connect(profile_id)
    
    def _on_add_profile(self) -> None:
        """Add profile via dialog."""
        profile = show_add_profile_dialog(self._window)

        if profile:
            entry = self._context.profiles.add_profile(profile)
            self._context.profiles.save()
            # Update UI
            if self._tray:
                self._tray.refresh_profiles()
            if self._window:
                self._window.refresh()
            
            self._tray.show_notification(
                "Profile added",
                f"{entry.name}\n{profile.display_address}"
            )
    
    def _on_show_window(self) -> None:
        """Show main window."""
        if self._window:
            self._window.show_all()
            self._window.present()
    
    def _on_settings(self) -> None:
        """Open settings."""
        show_settings_dialog(self._context, self._window, on_config_reload=self._reload_config)
    
    def _connect(self, profile_id: int) -> bool:
        """Connect to profile."""
        # If connected - disconnect
        if self._context.proxy_state.is_running:
            self._disconnect()
        
        profile = self._context.profiles.get_profile(profile_id)
        if not profile:
            logger.error("Profile %s not found", profile_id)
            return False

        try:
            self._context.proxy_state.vpn_auto_connected = False
        except Exception:
            pass

        if profile.vpn_settings and profile.vpn_settings.enabled and getattr(profile.vpn_settings, "auto_connect", False):
            was_active_before = is_vpn_active(profile.vpn_settings.connection_name)
            if not was_active_before:
                logger.info(
                    "Auto-connecting VPN '%s' before starting profile %s",
                    profile.vpn_settings.connection_name,
                    profile_id,
                )
                if not connect_vpn(profile.vpn_settings.connection_name):
                    logger.warning(
                        "Failed to auto-connect VPN '%s', continuing without VPN",
                        profile.vpn_settings.connection_name,
                    )
                else:
                    try:
                        self._context.proxy_state.vpn_auto_connected = True
                    except Exception:
                        pass
        
        self._last_profile_id = profile_id
        config = self._create_config(profile)
        if not config:
            return False
        # Save configuration for debugging
        config_path = self._context.config_dir / "current_config.json"
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        logger.info("Configured profile id=%s, file: %s", profile_id, config_path)
        # Start sing-box
        try:
            success, error = self._context.singbox_manager.start(config)
            if not success:
                logger.error("Error starting sing-box: %s", error)
                if self._tray:
                    self._tray.show_notification("Error", f"Failed to start: {error}")
                return False
            # Set state as running
            self._context.proxy_state.set_running(profile_id)

            # Configure system proxy
            port = self._context.config.inbound_socks_port
            set_system_proxy(http_port=port, socks_port=port)

            profile = self._context.profiles.get_profile(profile_id)
            name = profile.name if profile else "Unknown"
            if self._tray:
                self._tray.show_notification("Connected", f"Profile: {name}")

            if self._monitor:
                self._monitor.start()

            return True

        except Exception as e:
            logger.exception("Error starting sing-box: %s", e)
            if self._tray:
                self._tray.show_notification("Error", f"Failed to start: {e}")
            return False
    
    def _reload_config(self) -> bool:
        """
        Reload configuration.
        
        Returns:
            True if reload was successful, False otherwise
        """
        if not self._context.proxy_state.is_running:
            logger.debug("Proxy is not running, nothing to reload")
            return False
        
        profile_id = self._context.proxy_state.started_profile_id
        profile = self._context.profiles.get_profile(profile_id)
        if not profile:
            logger.error("Profile %s not found for reload", profile_id)
            return False
        
        logger.info("Reloading configuration for profile %s", profile_id)
        config = self._create_config(profile)
        if not config:
            logger.error("Failed to create configuration for reload")
            return False

        config_path = self._context.config_dir / "current_config.json"
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        logger.info("Reloaded configuration for profile id=%s, file: %s", profile_id, config_path)
        
        # Reload sing-box
        try:
            success, error = self._context.singbox_manager.reload_config(config)
            if not success:
                logger.error("Error reloading sing-box: %s", error)
                if self._tray:
                    self._tray.show_notification("Ошибка", f"Не удалось перезагрузить: {error}")
                return False
            
            logger.info("Configuration reloaded successfully")
            if self._tray:
                self._tray.show_notification("Конфигурация обновлена", "Настройки применены")
            return True
            
        except Exception as e:
            logger.exception("Error reloading sing-box: %s", e)
            if self._tray:
                self._tray.show_notification("Ошибка", f"Не удалось перезагрузить: {e}")
            return False
    
    def _disconnect(self) -> None:
        """Disconnect proxy."""
        # Stop sing-box
        try:
            success, error = self._context.singbox_manager.stop()
            if not success:
                logger.error("Error stopping sing-box: %s", error)
        except Exception as e:
            logger.exception("Exception when stopping sing-box: %s", e)

        try:
            profile_id = getattr(self._context.proxy_state, "started_profile_id", None)
            if profile_id:
                profile = self._context.profiles.get_profile(profile_id)
                if profile and profile.vpn_settings:
                    vpn_settings = profile.vpn_settings
                    auto_flag = getattr(self._context.proxy_state, "vpn_auto_connected", False)
                    if vpn_settings.enabled and getattr(vpn_settings, "auto_connect", False) and auto_flag:
                        if disconnect_vpn(vpn_settings.connection_name):
                            logger.info(
                                "Auto-disconnected VPN '%s' after stopping profile",
                                vpn_settings.connection_name,
                            )
                        else:
                            logger.warning(
                                "Failed to auto-disconnect VPN '%s' after stopping profile",
                                vpn_settings.connection_name,
                            )
        except Exception as e:
            logger.exception("Error during VPN auto-disconnect: %s", e)
        finally:
            try:
                self._context.proxy_state.vpn_auto_connected = False
            except Exception:
                pass

        clear_system_proxy()
        # Update state
        self._context.proxy_state.set_stopped()

        if self._monitor:
            self._monitor.stop()

        if self._tray:
            self._tray.show_notification("Disconnected", "Proxy disconnected")
    
    def _create_config(self, profile: ProfileEntry) -> Optional[dict]:
        """Create sing-box configuration for profile."""
        try:
            result = profile.bean.build_core_obj_singbox()
            
            if result.get("error"):
                logger.error(
                    "Error creating profile configuration %s: %s",
                    profile.id,
                    result["error"],
                )
                return None
            
            outbound = result["outbound"]
            if "tag" not in outbound:
                outbound["tag"] = "proxy"
            
            proxy_tag = outbound["tag"]
            port = self._context.config.inbound_socks_port
            routing = self._context.config.routing
            
            # Build routing rules
            route_rules = []

            # Use profile VPN settings only
            vpn_settings = profile.vpn_settings
            vpn_tag = None
            vpn_interface = None
            over_vpn_domains_for_dns = []

            if vpn_settings:
                try:
                    direct_networks = getattr(vpn_settings, "direct_networks", []) or []
                    direct_domains = getattr(vpn_settings, "direct_domains", []) or []
                except Exception:
                    direct_networks = []
                    direct_domains = []

                if direct_networks or direct_domains:
                    all_direct_entries = direct_networks + direct_domains
                    direct_domains_parsed, direct_ips_parsed = routing.parse_entries(all_direct_entries)

                    if direct_ips_parsed:
                        route_rules.append({
                            "ip_cidr": direct_ips_parsed,
                            "outbound": "direct",
                        })
                        logger.debug("Added DIRECT routing for IPs: %s", direct_ips_parsed)

                    if direct_domains_parsed:
                        route_rules.append({
                            "domain_suffix": direct_domains_parsed,
                            "outbound": "direct",
                        })
                        logger.debug("Added DIRECT routing for domains: %s", direct_domains_parsed)

            # Process VPN routing rules (only if VPN is enabled and active)
            if vpn_settings and vpn_settings.enabled:
                if is_vpn_active(vpn_settings.connection_name):
                    if vpn_settings.interface_name:
                        vpn_interface = vpn_settings.interface_name
                    else:
                        vpn_interface = get_vpn_interface(vpn_settings.connection_name)
                    
                    if vpn_interface:
                        vpn_tag = "vpn"
                        logger.info("VPN integration enabled, interface: %s", vpn_interface)
                        over_vpn_ips = []
                        over_vpn_domains = []
                        all_entries = vpn_settings.over_vpn_networks + vpn_settings.over_vpn_domains
                        logger.debug("VPN settings - over_vpn_networks: %s, over_vpn_domains: %s", 
                                   vpn_settings.over_vpn_networks, vpn_settings.over_vpn_domains)
                        if all_entries:
                            over_vpn_domains, over_vpn_ips = routing.parse_entries(all_entries)
                            over_vpn_domains_for_dns = over_vpn_domains
                            logger.debug("Parsed - over_vpn_domains: %s, over_vpn_ips: %s", 
                                       over_vpn_domains, over_vpn_ips)
                        else:
                            logger.warning("No over_vpn entries found in VPN settings for profile %s", profile.id)

                        if over_vpn_ips:
                            route_rules.append({
                                "ip_cidr": over_vpn_ips,
                                "outbound": vpn_tag,
                            })
                            logger.debug("Added VPN routing for IPs: %s", over_vpn_ips)
                        
                        if over_vpn_domains:
                            route_rules.append({
                                "domain_suffix": over_vpn_domains,
                                "outbound": vpn_tag,
                            })
                            logger.debug("Added VPN routing for domains: %s", over_vpn_domains)
                    else:
                        logger.warning("VPN is enabled but interface not found")
                else:
                    logger.warning("VPN integration enabled but connection '%s' is not active", vpn_settings.connection_name)

            if routing.mode != RoutingMode.PROXY_ALL:
                local_networks = {
                    "ip_cidr": [
                        "127.0.0.0/8",
                        "10.0.0.0/8",
                        "172.16.0.0/12",
                        "192.168.0.0/16",
                        "169.254.0.0/16",
                        "::1/128",
                        "fc00::/7",
                        "fe80::/10",
                    ],
                    "outbound": "direct",
                }
                route_rules.append(local_networks)

            final_outbound = proxy_tag
            # Outbounds
            direct_outbound = {"type": "direct", "tag": "direct"}
            if vpn_tag and vpn_interface and vpn_settings:
                direct_interface = getattr(vpn_settings, "direct_interface", "") or ""
                if not direct_interface:
                    direct_interface = get_default_interface(vpn_interface)
                
                if direct_interface:
                    direct_outbound["bind_interface"] = direct_interface
                    logger.info("Direct outbound bound to interface: %s (bypassing VPN %s)", 
                               direct_interface, vpn_interface)
            
            outbounds = [
                direct_outbound,
                outbound,
            ]

            if vpn_tag and vpn_interface:
                vpn_outbound = {
                    "type": "direct",
                    "tag": vpn_tag,
                    "bind_interface": vpn_interface,
                }
                # Use local-dns for VPN outbound to avoid circular dependency
                # VPN DNS server uses detour to this outbound, so we use local-dns here
                vpn_outbound["domain_resolver"] = "local-dns"
                logger.info("Added VPN outbound with interface: %s, domain_resolver: local-dns", vpn_interface)
                outbounds.append(vpn_outbound)

            if vpn_settings:
                if vpn_settings.enabled:
                    if vpn_tag:
                        logger.info("Profile configuration: VPN enabled and active, proxy + VPN routing")
                    else:
                        logger.info("Profile configuration: VPN enabled but not active, proxy only")
                else:
                    logger.info("Profile configuration: VPN disabled, proxy + direct rules (if any)")
            else:
                logger.info("Profile configuration: No VPN settings, proxy only")
            # DNS (sing-box 1.12.0+ new format)
            dns_settings = self._context.config.dns
            dns_url = dns_settings.get_dns_url()
            dns_detour = proxy_tag if dns_settings.use_proxy else "direct"

            vps_server = outbound.get("server", "")
            
            # Build DNS servers list (new format: type + server instead of address)
            dns_servers = []
            
            # Main DNS server
            if dns_url == "local":
                dns_servers.append({
                    "tag": "main-dns",
                    "type": "local",
                    "detour": dns_detour,
                })
            elif dns_url.startswith("https://"):
                # DoH server
                from urllib.parse import urlparse
                parsed = urlparse(dns_url)
                server_host = parsed.netloc.split(":")[0] if ":" in parsed.netloc else parsed.netloc
                server_port = parsed.port if parsed.port else 443
                path = parsed.path if parsed.path else "/dns-query"
                
                dns_servers.append({
                    "tag": "main-dns",
                    "type": "https",
                    "server": server_host,
                    "server_port": server_port,
                    "path": path,
                    "detour": dns_detour,
                })
            elif dns_url.startswith("tls://"):
                # DoT server
                server = dns_url.replace("tls://", "").split(":")[0]
                port = 853
                if ":" in dns_url.replace("tls://", ""):
                    port = int(dns_url.split(":")[-1])
                
                dns_servers.append({
                    "tag": "main-dns",
                    "type": "tls",
                    "server": server,
                    "server_port": port,
                    "detour": dns_detour,
                })
            else:
                # Plain IP or domain - use UDP
                server = dns_url.replace("udp://", "").replace("tcp://", "")
                dns_servers.append({
                    "tag": "main-dns",
                    "type": "udp",
                    "server": server,
                    "detour": dns_detour,
                })
            
            # Local DNS server
            dns_servers.append({
                "tag": "local-dns",
                "type": "local",
                "detour": "direct",
            })

            if vpn_tag and vpn_interface and over_vpn_domains_for_dns:
                # Get DNS servers from VPN connection settings
                vpn_dns_servers = get_vpn_dns_servers(vpn_settings.connection_name)
                
                if vpn_dns_servers:
                    # Use first DNS server from VPN settings
                    vpn_dns_ip = vpn_dns_servers[0]
                    logger.debug("Raw VPN DNS server from NetworkManager: %s", vpn_dns_ip)
                    
                    # Clean up the address: remove protocol prefixes, brackets, etc.
                    clean_ip = vpn_dns_ip.strip()
                    
                    # Remove protocol prefixes
                    for prefix in ["udp://", "tcp://", "tls://", "https://"]:
                        if clean_ip.startswith(prefix):
                            clean_ip = clean_ip[len(prefix):]
                    
                    # Remove brackets if present
                    clean_ip = clean_ip.strip("[]")
                    
                    # Handle NetworkManager format like "IP4.DNS[1]:10.222.0.7:53" or "IP4.DNS[1]:10.222.0.7"
                    # Extract IP address and port using regex-like approach
                    import re
                    # Pattern to match IP address (IPv4 or IPv6) with optional port
                    ip_pattern = r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?::(\d+))?'
                    ipv6_pattern = r'([0-9a-fA-F:]+)(?::(\d+))?'
                    
                    # Try to find IP address in the string
                    match = re.search(ip_pattern, clean_ip)
                    if not match:
                        match = re.search(ipv6_pattern, clean_ip)
                    
                    if match:
                        server_ip = match.group(1)
                        server_port = int(match.group(2)) if match.group(2) else 53
                        logger.debug("Extracted IP: %s, port: %d from: %s", server_ip, server_port, vpn_dns_ip)
                    else:
                        # Fallback: try to extract by splitting on colons
                        # Remove any non-IP prefix (like "IP4.DNS[1]:")
                        parts = clean_ip.split(":")
                        # Find the part that looks like an IP address
                        for part in parts:
                            # Check if part looks like an IP (contains dots or is IPv6)
                            if "." in part or ":" in part:
                                # This might be the IP
                                ip_candidate = part
                                port_candidate = 53
                                # Check if next part is a number (port)
                                part_idx = parts.index(part)
                                if part_idx + 1 < len(parts):
                                    try:
                                        port_candidate = int(parts[part_idx + 1])
                                    except (ValueError, IndexError):
                                        pass
                                
                                # Validate IP format
                                if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip_candidate):
                                    server_ip = ip_candidate
                                    server_port = port_candidate
                                    logger.debug("Extracted IP (fallback): %s, port: %d from: %s", server_ip, server_port, vpn_dns_ip)
                                    break
                        else:
                            # No valid IP found, use fallback
                            logger.error("Could not extract IP address from: %s", vpn_dns_ip)
                            server_ip = "8.8.8.8"
                            server_port = 53
                    
                    # Final validation: server_ip should be a valid IP format
                    if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', server_ip):
                        logger.error("Invalid VPN DNS server IP format: %s (from: %s)", server_ip, vpn_dns_ip)
                        server_ip = "8.8.8.8"  # Fallback
                        server_port = 53
                    
                    logger.info(
                        "Using VPN DNS server %s:%d for over_vpn domains (from connection %s, original: %s, available: %s)",
                        server_ip, server_port, vpn_settings.connection_name, vpn_dns_ip, vpn_dns_servers
                    )
                    # Use detour to VPN outbound for UDP DNS
                    # This routes DNS queries through VPN interface via VPN outbound
                    dns_servers.append({
                        "tag": "vpn-dns",
                        "type": "udp",
                        "server": server_ip,
                        "server_port": server_port,
                        "detour": vpn_tag,
                    })
                else:
                    # Fallback to local DNS through VPN interface
                    logger.warning(
                        "No DNS servers found in VPN connection %s settings, using local DNS through VPN interface",
                        vpn_settings.connection_name
                    )
                    dns_servers.append({
                        "tag": "vpn-dns",
                        "type": "local",
                        "detour": vpn_tag,
                    })
                logger.info("Added VPN DNS server for over_vpn domains")

            dns_rules = []

            # IMPORTANT: DNS rules are evaluated in order, so more specific rules should come first
            # 1. over_vpn domains should use VPN DNS (highest priority)
            if vpn_tag and over_vpn_domains_for_dns:
                # Use domain_suffix for matching subdomains
                dns_rules.append({
                    "domain_suffix": over_vpn_domains_for_dns,
                    "server": "vpn-dns",
                })
                logger.info("Added DNS rule for over_vpn domains (VPN DNS): %s", over_vpn_domains_for_dns)

            # 2. VPS server domain should use local DNS
            if vps_server and not vps_server[0].isdigit():
                dns_rules.append({
                    "domain": [vps_server],
                    "server": "local-dns",
                })

            # Note: Removed deprecated "outbound" rule - use domain_resolver in outbounds instead
            
            dns_config = {
                "servers": dns_servers,
                "rules": dns_rules,
                "final": "main-dns",
            }
            
            # Log DNS configuration for debugging
            logger.info("DNS configuration (sing-box 1.12.0+ format):")
            logger.info("  Servers: %s", [s.get("tag") for s in dns_servers])
            for server in dns_servers:
                server_type = server.get("type", "unknown")
                server_addr = server.get("server", "N/A")
                detour = server.get("detour", "N/A")
                bind_iface = server.get("bind_interface", "N/A")
                logger.info("    - %s: type=%s, server=%s, detour=%s, bind_interface=%s", 
                          server.get("tag"), server_type, server_addr, detour, bind_iface)
            logger.info("  Rules: %s", len(dns_rules))
            for i, rule in enumerate(dns_rules):
                if "domain" in rule:
                    logger.info("    Rule %d: domain=%s -> server=%s", i, rule.get("domain"), rule.get("server"))
                elif "domain_suffix" in rule:
                    logger.info("    Rule %d: domain_suffix=%s -> server=%s", i, rule.get("domain_suffix"), rule.get("server"))
                elif "outbound" in rule:
                    logger.info("    Rule %d: outbound=%s -> server=%s", i, rule.get("outbound"), rule.get("server"))
            logger.info("  Final DNS server: %s", dns_config.get("final"))
            
            config = {
                "log": {
                    "level": self._context.config.log_level,
                    "timestamp": True
                },
                "dns": dns_config,
                "inbounds": [
                    {
                        "type": "mixed",
                        "listen": self._context.config.inbound_address,
                        "listen_port": port,
                        "sniff": True
                    }
                ],
                "outbounds": outbounds,
                "route": {
                    "rules": route_rules,
                    "final": final_outbound,
                    "auto_detect_interface": not (vpn_tag and vpn_interface),
                }
            }
            
            return config
            
        except Exception as e:
            logger.exception(
                "Error creating profile configuration %s: %s",
                getattr(profile, "id", "?"),
                e,
            )
            return None


def run_app(config_dir: Optional[Path] = None, lock=None) -> int:
    """Run application.
    
    Args:
        config_dir: Configuration directory
        lock: SingleInstance lock object
    """
    context = init_context(config_dir=config_dir)
    setup_logging(context)
    app = TengaApp(context, lock=lock)
    return app.run()
