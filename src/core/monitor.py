from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.core.performance import measure_time

if TYPE_CHECKING:
    from src.core.context import AppContext

logger = logging.getLogger("tenga.core.monitor")


@dataclass
class ConnectionStatus:
    """Connection status information."""

    proxy_ok: bool = False
    vpn_ok: bool = False
    last_check_time: float = 0.0
    proxy_error: str = ""
    vpn_error: str = ""


class ConnectionMonitor:
    """
    Monitor proxy and VPN connection status.

    Periodically checks:
    - Proxy: xray-core process status + version check
    - VPN: NetworkManager connection status (if VPN integration enabled)
    """

    def __init__(self, context: AppContext):
        """
        Initialize monitor.

        Args:
            context: Application context
        """
        self._context = context
        self._timer_id: int | None = None
        self._traffic_timer_id: int | None = None
        self._traffic_in_progress = False
        self._check_in_progress = False
        self._check_generation = 0
        self._status = ConnectionStatus()
        self._previous_status = ConnectionStatus()
        self._on_status_changed: Callable[[ConnectionStatus, ConnectionStatus], None] | None = None

    def set_on_status_changed(
        self, callback: Callable[[ConnectionStatus, ConnectionStatus], None] | None
    ) -> None:
        """Set callback for status changes."""
        self._on_status_changed = callback

    def start(self) -> None:
        """Start monitoring."""
        if self._timer_id is not None:
            logger.debug("Monitoring already started")
            return

        if not self._context.config.monitoring.enabled:
            logger.info("Monitoring is disabled in settings, not starting")
            return

        logger.info(
            "Starting connection monitoring (interval: %d seconds)",
            self._context.config.monitoring.check_interval_seconds,
        )
        # Do initial check
        self._check_connections()

        # Schedule periodic checks
        interval_ms = self._context.config.monitoring.check_interval_seconds * 1000
        from gi.repository import GLib

        self._timer_id = GLib.timeout_add(interval_ms, self._check_connections)
        logger.info("Monitoring timer started (ID: %s)", self._timer_id)

        # Счётчик трафика идёт своим таймером: у проверки доступности интервал
        # в десять секунд, для растущих байтов это слишком редко.
        traffic_interval_ms = max(200, int(self._context.config.traffic_loop_interval))
        self._traffic_timer_id = GLib.timeout_add(traffic_interval_ms, self._tick_traffic)
        logger.info(
            "Traffic timer started (ID: %s, interval: %d ms)",
            self._traffic_timer_id,
            traffic_interval_ms,
        )

    def stop(self) -> None:
        """Stop monitoring."""
        # Cleared before the early return: a check may be in flight even when no
        # timer is armed, and leaving the flag set would make every later tick
        # skip forever.
        self._check_in_progress = False
        self._traffic_in_progress = False

        # Таймер трафика снимается до раннего возврата: он заводится вместе с
        # основным, но пережил бы его, если выйти раньше.
        if self._traffic_timer_id is not None:
            from gi.repository import GLib

            GLib.source_remove(self._traffic_timer_id)
            self._traffic_timer_id = None

        if self._timer_id is None:
            return

        logger.info("Stopping connection monitoring")
        from gi.repository import GLib

        GLib.source_remove(self._timer_id)
        self._timer_id = None

        # Reset status
        self._status = ConnectionStatus()
        self._previous_status = ConnectionStatus()

    @measure_time("ConnectionMonitor._check_connections")
    def _check_connections(self) -> bool:
        """
        Check proxy and VPN connections asynchronously.

        Returns:
            True to continue timer, False to stop
        """
        if self._timer_id is None:
            return False

        if not self._context.config.monitoring.enabled:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Monitoring disabled, stopping checks")
            self.stop()
            return False

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Checking connections...")

        if self._check_in_progress:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Previous connection check still running, skipping tick")
            return True

        # Run checks in background thread
        self._check_in_progress = True
        self._check_generation += 1
        generation = self._check_generation
        threading.Thread(target=self._do_check_async, args=(generation,), daemon=True).start()

        return True

    def refresh_traffic(self) -> None:
        """Pull the traffic counters into the shared state.

        Молча ничего не делает у остановленного ядра: опрос идёт по таймеру,
        а спрашивать статистику у несуществующего процесса незачем. Ошибку
        ядра тоже глотает — тик не вправе обрывать наблюдение.
        """
        state = self._context.proxy_state
        if not state.is_running:
            return

        try:
            stats = self._context.xray_manager.get_traffic()
        except Exception as e:
            logger.debug("Could not read the traffic counters: %s", e)
            return

        # Неизменившиеся цифры не поднимают перерисовку карточки каждую секунду.
        if stats.upload == state.upload_bytes and stats.download == state.download_bytes:
            return

        state.upload_bytes = stats.upload
        state.download_bytes = stats.download
        state.notify_listeners()

    def _tick_traffic(self) -> bool:
        """Timer tick: read the counters off the main thread.

        Вызов ядра занимает около 25 мс, и на слабой машине этого хватит,
        чтобы интерфейс дёрнулся, поэтому опрос уходит в фоновый поток.
        """
        if self._traffic_timer_id is None:
            return False

        if self._traffic_in_progress:
            return True

        self._traffic_in_progress = True
        threading.Thread(target=self._do_traffic_async, daemon=True).start()
        return True

    def _do_traffic_async(self) -> None:
        """Read the counters, then apply them on the main thread."""
        try:
            state = self._context.proxy_state
            if not state.is_running:
                return
            stats = self._context.xray_manager.get_traffic()
        except Exception as e:
            logger.debug("Could not read the traffic counters: %s", e)
            return
        finally:
            self._traffic_in_progress = False

        # Состояние правится и слушатели зовутся только из главного потока:
        # по их цепочке идёт перерисовка виджетов.
        from gi.repository import GLib

        GLib.idle_add(self._apply_traffic, stats.upload, stats.download)

    def _apply_traffic(self, upload: int, download: int) -> bool:
        """Store the counters and repaint, if anything actually changed."""
        state = self._context.proxy_state
        if not state.is_running:
            return False
        if upload == state.upload_bytes and download == state.download_bytes:
            return False

        state.upload_bytes = upload
        state.download_bytes = download
        state.notify_listeners()
        return False

    @measure_time("ConnectionMonitor._check_proxy_status")
    def _check_proxy_status(self) -> tuple[bool, str]:
        """
        Check proxy connection status.

        Returns:
            (is_ok, error_message)
        """
        if not self._context.proxy_state.is_running:
            logger.info("Proxy check: proxy is not running")
            return False, "Прокси не запущен"

        manager = self._context.xray_manager

        if not manager._check_process_alive():
            logger.warning("Proxy check: xray-core process is not running")
            return False, "Процесс xray-core не запущен"

        # Use cached version instead of fetching
        version_info = manager.get_version()
        if not version_info:
            logger.warning("Proxy check: xray-core version not available")
            return False, "Не удалось получить версию xray-core"

        logger.debug(
            "Proxy check: xray-core OK, version: %s", version_info.get("version", "unknown")
        )

        logger.info("Proxy check: SUCCESS (xray-core running)")
        return True, ""

    def _check_vpn_status(self) -> tuple[bool, str]:
        """
        Check VPN connection status.

        Returns:
            (is_ok, error_message)
        """
        from src.sys.vpn import is_vpn_active

        connection_name = self._get_effective_vpn_connection_name()
        if not connection_name:
            return True, ""

        try:
            if is_vpn_active(connection_name):
                return True, ""
            return False, f"VPN '{connection_name}' не активен"
        except Exception as e:
            logger.debug("VPN check error: %s", e)
            return False, f"Ошибка проверки VPN: {e}"

    def _get_effective_vpn_connection_name(self) -> str:
        """Resolve VPN connection name from active profile first, then global config."""
        profile_id = self._context.proxy_state.started_profile_id
        if self._context.proxy_state.is_running and profile_id >= 0:
            try:
                profile = self._context.profiles.get_profile(profile_id)
            except Exception:
                profile = None

            if profile and getattr(profile, "vpn_settings", None):
                vpn_settings = profile.vpn_settings
                if getattr(vpn_settings, "enabled", False):
                    profile_name = (getattr(vpn_settings, "connection_name", "") or "").strip()
                    if profile_name:
                        return profile_name

        return (self._context.config.vpn.connection_name or "").strip()

    def _should_check_vpn(self) -> bool:
        """Return True when VPN should be checked in monitoring."""
        return bool(self._get_effective_vpn_connection_name()) or self._context.config.vpn.enabled

    def _do_check_async(self, generation: int = 0) -> None:
        """Perform connection checks asynchronously.

        Runs in background thread to avoid blocking GTK main loop.
        """
        try:
            self._run_check()
        finally:
            from gi.repository import GLib

            GLib.idle_add(self._finish_check, generation)

    def _finish_check(self, generation: int = 0) -> bool:
        """Allow the next tick to start a check (runs on the main loop).

        A stale callback from a check that was superseded by stop()/start() must
        not clear the flag of the check running now, so it is ignored unless it
        belongs to the current generation.
        """
        if generation and generation != self._check_generation:
            logger.debug("Ignoring stale check completion (generation %s)", generation)
            return False

        self._check_in_progress = False
        return False

    def _run_check(self) -> None:
        """Collect connection status and hand the result to the main loop."""
        # Save previous status
        previous_status = ConnectionStatus(
            proxy_ok=self._status.proxy_ok,
            vpn_ok=self._status.vpn_ok,
            last_check_time=self._status.last_check_time,
            proxy_error=self._status.proxy_error,
            vpn_error=self._status.vpn_error,
        )

        proxy_ok, proxy_error = self._check_proxy_status()
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Proxy status: %s (%s)", "OK" if proxy_ok else "FAIL", proxy_error or "no error"
            )

        vpn_ok = True
        vpn_error = ""
        if self._should_check_vpn():
            vpn_ok, vpn_error = self._check_vpn_status()
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "VPN status: %s (%s)", "OK" if vpn_ok else "FAIL", vpn_error or "no error"
                )

        new_status = ConnectionStatus(
            proxy_ok=proxy_ok,
            vpn_ok=vpn_ok,
            last_check_time=time.time(),
            proxy_error=proxy_error,
            vpn_error=vpn_error,
        )

        # Update UI in main thread
        from gi.repository import GLib

        GLib.idle_add(self._update_status_from_async, previous_status, new_status)

    def _update_status_from_async(
        self, previous_status: ConnectionStatus, new_status: ConnectionStatus
    ) -> bool:
        """Update status from async check (runs in GTK main loop).

        Args:
            previous_status: Previous status
            new_status: New status

        Returns:
            False to remove from idle queue
        """
        self._previous_status = previous_status
        self._status = new_status
        self._notify_status_changed()
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Status updated and UI notified")
        return False  # Remove from idle queue

    def _status_changed(self) -> bool:
        """Check if status changed since last check."""
        return (
            self._status.proxy_ok != self._previous_status.proxy_ok
            or self._status.vpn_ok != self._previous_status.vpn_ok
        )

    def _notify_status_changed(self) -> None:
        """Notify about status changes."""
        if not self._on_status_changed:
            return

        try:
            self._on_status_changed(self._previous_status, self._status)
        except Exception as e:
            logger.error("Error in status change callback: %s", e)

    def _notify_ui_update(self) -> None:
        """Notify UI to update (always, not just on change)."""
        if not self._on_status_changed:
            return

        try:
            self._on_status_changed(self._status, self._status)
        except Exception as e:
            logger.error("Error in UI update callback: %s", e)

    @property
    def status(self) -> ConnectionStatus:
        """Get current status."""
        return self._status

    def get_status(self) -> ConnectionStatus:
        """Get current status (alias for property)."""
        return self.status

    def check_now(self) -> None:
        """Force immediate connection check."""
        logger.info("Manual connection check requested")
        was_enabled = self._context.config.monitoring.enabled

        if not was_enabled:
            logger.warning("Monitoring is disabled, enabling temporarily for manual check")
            self._context.config.monitoring.enabled = True

        try:
            self._check_connections()
            self._notify_ui_update()
        finally:
            if not was_enabled:
                self._context.config.monitoring.enabled = False
