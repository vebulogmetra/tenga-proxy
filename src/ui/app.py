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
from src.db.config import RoutingMode
from src.db.profiles import ProfileEntry
from src.sys.proxy import clear_system_proxy, set_system_proxy
from src.sys.vpn import get_vpn_interface, is_vpn_active
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
    
    def __init__(self, context: Optional[AppContext] = None):
        self._context = context or get_context()
        
        self._tray: Optional[TrayIcon] = None
        self._window: Optional[MainWindow] = None
        
        # Last selected profile
        self._last_profile_id: Optional[int] = None
        
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers."""
        signal.signal(signal.SIGINT, self._on_signal)
        signal.signal(signal.SIGTERM, self._on_signal)
    
    def _on_signal(self, signum: int, frame) -> None:
        """Signal handler."""
        logger.info("Received signal %s, terminating application", signum)
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
    
    def quit(self) -> None:
        """Quit application."""
        # Disconnect proxy
        if self._context.proxy_state.is_running:
            self._disconnect()
        # Save configuration
        self._context.save_all()
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
        show_settings_dialog(self._context, self._window)
    
    def _connect(self, profile_id: int) -> bool:
        """Connect to profile."""
        # If connected - disconnect
        if self._context.proxy_state.is_running:
            self._disconnect()

        profile = self._context.profiles.get_profile(profile_id)
        if not profile:
            logger.error("Profile %s not found", profile_id)
            return False

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

            return True

        except Exception as e:
            logger.exception("Error starting sing-box: %s", e)
            if self._tray:
                self._tray.show_notification("Error", f"Failed to start: {e}")
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

        # Clear system proxy
        clear_system_proxy()
        # Update state
        self._context.proxy_state.set_stopped()

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
            vpn_settings = self._context.config.vpn
            
            # Build routing rules
            route_rules = []

            vpn_tag = None
            vpn_interface = None
            if vpn_settings.enabled:
                if is_vpn_active(vpn_settings.connection_name):
                    if vpn_settings.interface_name:
                        vpn_interface = vpn_settings.interface_name
                    else:
                        vpn_interface = get_vpn_interface(vpn_settings.connection_name)
                    
                    if vpn_interface:
                        vpn_tag = "vpn"
                        logger.info("VPN integration enabled, interface: %s", vpn_interface)
                        corporate_ips = []
                        corporate_domains = []
                        
                        # Combine networks and domains from settings
                        all_entries = vpn_settings.corporate_networks + vpn_settings.corporate_domains
                        if all_entries:
                            corporate_domains, corporate_ips = routing.parse_entries(all_entries)
                        
                        # Add routing rules for VPN
                        if corporate_ips:
                            route_rules.append({
                                "ip_cidr": corporate_ips,
                                "outbound": vpn_tag,
                            })
                            logger.debug("Added VPN routing for IPs: %s", corporate_ips)
                        
                        if corporate_domains:
                            route_rules.append({
                                "domain_suffix": corporate_domains,
                                "outbound": vpn_tag,
                            })
                            logger.debug("Added VPN routing for domains: %s", corporate_domains)
                    else:
                        logger.warning("VPN is enabled but interface not found")
                else:
                    logger.warning("VPN integration enabled but connection '%s' is not active", vpn_settings.connection_name)
            
            # Local networks always direct (except PROXY_ALL mode)
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
            
            # In CUSTOM mode load rules from files
            if routing.mode == RoutingMode.CUSTOM:
                proxy_file = self._context.config_dir / "proxy_list.txt"
                direct_file = self._context.config_dir / "direct_list.txt"

                proxy_entries = routing.load_list_file(proxy_file)
                if proxy_entries:
                    proxy_domains, proxy_ips = routing.parse_entries(proxy_entries)
                    if proxy_domains:
                        route_rules.append({
                            "domain_suffix": proxy_domains,
                            "outbound": proxy_tag,
                        })
                    if proxy_ips:
                        route_rules.append({
                            "ip_cidr": proxy_ips,
                            "outbound": proxy_tag,
                        })

                direct_entries = routing.load_list_file(direct_file)
                if direct_entries:
                    direct_domains, direct_ips = routing.parse_entries(direct_entries)
                    if direct_domains:
                        route_rules.append({
                            "domain_suffix": direct_domains,
                            "outbound": "direct",
                        })
                    if direct_ips:
                        route_rules.append({
                            "ip_cidr": direct_ips,
                            "outbound": "direct",
                        })

            final_outbound = proxy_tag
            # Outbounds
            outbounds = [
                {"type": "direct", "tag": "direct"},
                outbound,
            ]
            
            # Add VPN outbound
            if vpn_tag and vpn_interface:
                vpn_outbound = {
                    "type": "direct",
                    "tag": vpn_tag,
                    "bind_interface": vpn_interface,
                }
                outbounds.append(vpn_outbound)
                logger.info("Added VPN outbound with interface: %s", vpn_interface)
            # DNS
            dns_settings = self._context.config.dns
            dns_url = dns_settings.get_dns_url()
            dns_detour = proxy_tag if dns_settings.use_proxy else "direct"

            vps_server = outbound.get("server", "")
            
            dns_config = {
                "servers": [
                    {
                        "tag": "main-dns",
                        "address": dns_url,
                        "detour": dns_detour,
                    },
                    {
                        "tag": "local-dns",
                        "address": "local",
                        "detour": "direct",
                    }
                ],
                "rules": [
                    {
                        "domain": [vps_server] if vps_server and not vps_server[0].isdigit() else [],
                        "server": "local-dns",
                    },
                    {
                        "outbound": "direct",
                        "server": "local-dns",
                    }
                ],
                "final": "main-dns",
            }

            # Remove empty rules
            dns_config["rules"] = [r for r in dns_config["rules"] if r.get("domain") or r.get("outbound")]
            
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
                    "auto_detect_interface": True,
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


def run_app(config_dir: Optional[Path] = None) -> int:
    """Run application."""
    context = init_context(config_dir=config_dir)
    setup_logging(context)
    app = TengaApp(context)
    return app.run()
