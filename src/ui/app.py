from __future__ import annotations

import logging
import signal
import socket
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk

from src.core.config import GUI_LOG_FILE
from src.core.config_builder import (
    build_session_config,
    reserve_latency_port_pair,
)
from src.core.connection import ConnectionService
from src.core.context import AppContext, get_context, init_context
from src.core.logging_utils import setup_logging as setup_core_logging
from src.core.monitor import ConnectionMonitor, ConnectionStatus
from src.core.proxy_mode import build_inbounds_for_mode
from src.db.config import ProxyMode
from src.db.profiles import ProfileEntry
from src.ui.dialogs import show_add_profile_dialog, show_settings_dialog
from src.ui.main_window import MainWindow
from src.ui.tray import TrayIcon


logger = logging.getLogger("tenga.ui.app")


def setup_logging(context: AppContext) -> None:
    """Initialize logging for GUI."""
    setup_core_logging(GUI_LOG_FILE, level=logging.INFO)
    logger.info("GUI logging initialized, file: %s", GUI_LOG_FILE)


class TengaApp:
    """Main Tenga application."""

    def __init__(self, context: AppContext | None = None, lock=None):
        self._context = context or get_context()
        self._lock = lock

        self._tray: TrayIcon | None = None
        self._window: MainWindow | None = None

        # Last selected profile
        self._last_profile_id: int | None = None

        # Connection monitor
        self._monitor: ConnectionMonitor | None = None
        self._setup_monitor()
        # Запуск и остановка живут в общем сервисе: GTK3-окно и новое
        # GTK4-приложение должны вести себя одинаково.
        self._connection = ConnectionService(self._context)

        # Initialize socket listener stop flag
        self._stop_socket_listener = False

        self._signal_source_ids: list[int] = []
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
        """Deliver SIGINT/SIGTERM through the GLib main loop (safe for GTK)."""
        self._signal_source_ids = [
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, self._on_signal, signum)
            for signum in (signal.SIGINT, signal.SIGTERM)
        ]

    def _on_signal(self, signum: int) -> bool:
        """Signal handler running on the main loop."""
        logger.info("Received signal %s, terminating application", signum)
        if self._lock:
            self._lock.release()
        self.quit()
        return GLib.SOURCE_REMOVE

    def _start_socket_listener(self) -> None:
        """Start socket listener thread to handle activation signals."""
        if not self._lock or not hasattr(self._lock, "_server_socket"):
            logger.warning("Socket server not available")
            return

        def socket_listener():
            """Listen for activation signals on the Unix socket."""
            server_socket = self._lock._server_socket
            logger.info("Socket listener started")

            while not getattr(self, "_stop_socket_listener", False):
                try:
                    # Use socket timeout to allow checking _stop_socket_listener periodically
                    server_socket.settimeout(1.0)  # 1 second timeout
                    conn, addr = server_socket.accept()

                    try:
                        # Receive activation message
                        data = conn.recv(1024)
                        if data and data.decode("utf-8").strip() == "ACTIVATE":
                            logger.info("Received activation signal, bringing window to foreground")
                            # Use GLib.idle_add to safely call GUI methods from another thread
                            GLib.idle_add(self._activate_window)
                    except Exception as e:
                        logger.error("Error processing activation signal: %s", e)
                    finally:
                        try:
                            conn.close()
                        except:
                            pass
                except socket.timeout:
                    # This is expected, just continue the loop to check _stop_socket_listener
                    continue
                except Exception as e:
                    if not getattr(self, "_stop_socket_listener", False):
                        logger.error("Socket listener error: %s", e)
                    break

            logger.info("Socket listener stopped")

        # Start the socket listener in a background thread
        self._socket_thread = threading.Thread(target=socket_listener, daemon=True)
        self._socket_thread.start()

    def _activate_window(self) -> None:
        """Activate the main window (bring to foreground)."""
        if self._window:
            try:
                logger.info("Activating main window")
                self._window.present()
            except Exception as e:
                logger.error("Error activating window: %s", e)

    def run(self) -> int:
        """Run application."""
        try:
            # Check xray-core
            xray_path = self._context.find_xray_binary()
            if not xray_path:
                error_msg = (
                    "xray-core not found!\n\n"
                    "Solutions:\n"
                    "1. Install xray-core globally (see README.md)\n"
                    "2. Place xray binary in core/bin/\n"
                    "3. Run ./install.sh for automatic installation"
                )

                # Show error dialog
                dialog = Gtk.MessageDialog(
                    flags=0,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.OK,
                    text="xray-core не найден",
                )
                dialog.set_wmclass("tenga-proxy", "tenga-proxy")
                from gi.repository import Gdk

                dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
                dialog.set_skip_taskbar_hint(True)
                dialog.format_secondary_text(error_msg)
                dialog.run()
                dialog.destroy()

                logger.error("xray-core not found")
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
            self._window.set_on_test_latency(self.test_profile_latency)
            # Show window on startup
            self._window.show_all()

            # Start socket listener for activation signals
            self._start_socket_listener()

            # Start GTK main loop
            logger.info("Starting GTK main loop")
            Gtk.main()

            logger.info("GTK main loop finished")
            return 0

        except Exception as e:
            logger.exception("Unhandled exception in TengaApp.run: %s", e)
            return 1
        finally:
            # Set flag to stop socket listener
            self._stop_socket_listener = True
            if hasattr(self, "_socket_thread") and self._socket_thread.is_alive():
                self._socket_thread.join(timeout=1.0)  # Wait up to 1 second for thread to finish
            if self._lock:
                self._lock.release()

    def quit(self) -> None:
        """Quit application."""
        # Disconnect proxy
        if self._context.proxy_state.is_running:
            self._disconnect()
        # Save configuration
        self._context.save_all()
        # Set flag to stop socket listener
        self._stop_socket_listener = True
        if hasattr(self, "_socket_thread") and self._socket_thread.is_alive():
            self._socket_thread.join(timeout=1.0)  # Wait up to 1 second for thread to finish
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
                "Profile added", f"{entry.name}\n{profile.display_address}"
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
        profile = self._context.profiles.get_profile(profile_id)
        if profile is None:
            logger.error("Profile %s not found", profile_id)
            return False

        self._last_profile_id = profile_id
        result = self._connection.connect(profile_id)

        if not result.ok:
            if self._tray:
                self._tray.show_notification("Error", f"Failed to start: {result.error}")
            return False

        if self._tray:
            self._tray.show_notification("Connected", f"Profile: {profile.name}")
        return True

    def _reload_config(self) -> bool:
        """Reload configuration into the running core.

        Returns:
            True if reload was successful, False otherwise
        """
        result = self._connection.reload_config()

        if not result.ok:
            if self._tray and self._context.proxy_state.is_running:
                self._tray.show_notification("Ошибка", f"Не удалось перезагрузить: {result.error}")
            return False

        if self._tray:
            self._tray.show_notification("Конфигурация обновлена", "Настройки применены")
        return True

    def _disconnect(self) -> None:
        """Disconnect proxy."""
        self._connection.disconnect()

        if self._tray:
            self._tray.show_notification("Disconnected", "Proxy disconnected")

    def _create_config(self, profile: ProfileEntry) -> dict | None:
        """Create xray-core configuration for profile."""
        return build_session_config(self._context, profile)

    def _reserve_latency_port_pair(self, host: str) -> int:
        """Reserve a free consecutive TCP port pair (socks, http=socks+1)."""
        return reserve_latency_port_pair(host)

    def _create_latency_test_config(self, profile: ProfileEntry) -> tuple[dict, int] | None:
        """Create temporary xray config for latency test."""
        config = self._create_config(profile)
        if not config:
            return None

        listen_host = self._context.config.inbound_address
        socks_port = self._reserve_latency_port_pair(listen_host)
        config["inbounds"] = build_inbounds_for_mode(
            mode=ProxyMode.SYSTEM_PROXY,
            address=listen_host,
            socks_port=socks_port,
            tun_name=getattr(self._context.config, "tun_name", "xray0"),
            tun_mtu=getattr(self._context.config, "tun_mtu", 1500),
        )
        return config, socks_port

    def test_profile_latency(self, profile_id: int, timeout_ms: int = 3000, probes: int = 3) -> int:
        """Run realistic latency test for profile through temporary xray instance."""
        profile = self._context.profiles.get_profile(profile_id)
        if not profile:
            logger.error("Latency test: profile %s not found", profile_id)
            return -1

        config_with_port = self._create_latency_test_config(profile)
        if not config_with_port:
            logger.error("Latency test: failed to build config for profile %s", profile_id)
            return -1

        config, socks_port = config_with_port
        probe_manager = None
        try:
            from src.core.xray_manager import XrayManager

            probe_manager = XrayManager(binary_path=self._context.xray_manager.binary_path)
            success, error = probe_manager.start(config)
            if not success:
                logger.error(
                    "Latency test: temp xray start failed for profile %s: %s", profile_id, error
                )
                return -1

            return probe_manager.test_delay_realistic(
                proxy_address=self._context.config.inbound_address,
                proxy_port=socks_port,
                timeout=timeout_ms,
                probes=probes,
            )
        except Exception as e:
            logger.exception("Latency test failed for profile %s: %s", profile_id, e)
            return -1
        finally:
            if probe_manager is not None:
                try:
                    probe_manager.stop()
                except Exception:
                    pass


def run_app(config_dir: Path | None = None, lock=None) -> int:
    """Run application.

    Args:
        config_dir: Configuration directory
        lock: SingleInstance lock object
    """
    context = init_context(config_dir=config_dir)
    setup_logging(context)
    app = TengaApp(context, lock=lock)
    return app.run()
