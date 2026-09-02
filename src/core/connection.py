"""Starting and stopping the proxy, without any GTK involvement.

Раньше эта последовательность жила прямо в GTK3-приложении вперемешку с
уведомлениями трея, из-за чего её нельзя было ни проверить тестом, ни повторно
использовать в новом интерфейсе. Здесь она сведена к трём методам, а результат
возвращается структурой: причина отказа нужна и карточке состояния, и трею.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.core.config_builder import build_session_config
from src.core.proxy_mode import normalize_proxy_mode, should_manage_system_proxy
from src.db.config import ProxyMode
from src.sys.proxy import clear_system_proxy, set_system_proxy
from src.sys.tun_route import apply_tun_routes, restore_tun_routes
from src.sys.vpn import connect_vpn, disconnect_vpn, is_vpn_active

if TYPE_CHECKING:
    from src.core.context import AppContext
    from src.sys.tun_route import TunRouteState

logger = logging.getLogger("tenga.core.connection")

PROFILE_NOT_FOUND = "Профиль не найден"
NO_CONFIG = "Не удалось построить конфигурацию профиля"
NOT_RUNNING = "Прокси не запущен"


@dataclass(frozen=True)
class ConnectionResult:
    """Outcome of one connect, disconnect or reload."""

    ok: bool
    error: str = ""


class ConnectionService:
    """Owns the proxy lifecycle for one application context."""

    def __init__(self, context: AppContext) -> None:
        self._context = context
        self._tun_route_state: TunRouteState | None = None

    # --- подключение ---

    def connect(self, profile_id: int) -> ConnectionResult:
        """Start xray-core for one profile, preparing VPN and routing first."""
        context = self._context

        if context.proxy_state.is_running:
            self.disconnect()

        profile = context.profiles.get_profile(profile_id)
        if profile is None:
            logger.error("Profile %s not found", profile_id)
            return ConnectionResult(False, PROFILE_NOT_FOUND)

        self._reset_vpn_flag()
        self._auto_connect_vpn(profile, profile_id)

        runtime_mode = normalize_proxy_mode(getattr(context.config, "proxy_mode", None))
        config = build_session_config(context, profile)
        if not config:
            logger.error("Could not build a configuration for profile %s", profile_id)
            return ConnectionResult(False, NO_CONFIG)

        self._write_debug_config(config, profile_id)

        try:
            started, error = context.xray_manager.start(config)
        except Exception as e:
            logger.exception("Error starting xray-core: %s", e)
            return ConnectionResult(False, str(e))

        if not started:
            logger.error("Error starting xray-core: %s", error)
            return ConnectionResult(False, error or "Не удалось запустить xray-core")

        context.proxy_state.set_running(profile_id, mode=runtime_mode)

        routed = self._apply_runtime_mode(runtime_mode, profile)
        if not routed.ok:
            return routed

        if context.monitor is not None:
            context.monitor.start()

        return ConnectionResult(True)

    def _reset_vpn_flag(self) -> None:
        try:
            self._context.proxy_state.vpn_auto_connected = False
        except Exception:
            logger.debug("Proxy state does not track the VPN flag", exc_info=True)

    def _auto_connect_vpn(self, profile, profile_id: int) -> None:
        """Raise the VPN link when the profile asks for it.

        Отказ VPN не срывает подключение: прокси без VPN работоспособен, а
        пользователь увидит состояние на странице мониторинга.
        """
        vpn = getattr(profile, "vpn_settings", None)
        if not vpn or not vpn.enabled or not getattr(vpn, "auto_connect", False):
            return

        if is_vpn_active(vpn.connection_name):
            return

        logger.info(
            "Auto-connecting VPN '%s' before starting profile %s",
            vpn.connection_name,
            profile_id,
        )
        if not connect_vpn(vpn.connection_name):
            logger.warning(
                "Failed to auto-connect VPN '%s', continuing without VPN",
                vpn.connection_name,
            )
            return

        try:
            self._context.proxy_state.vpn_auto_connected = True
        except Exception:
            logger.debug("Proxy state does not track the VPN flag", exc_info=True)

    def _write_debug_config(self, config: dict, profile_id: int) -> None:
        try:
            path = self._context.config_dir / "current_config.json"
            path.write_text(json.dumps(config, indent=2), encoding="utf-8")
            logger.info("Configured profile id=%s, file: %s", profile_id, path)
        except OSError as e:
            # Конфигурация нужна только для разбора проблем: не пишется —
            # подключение всё равно должно состояться.
            logger.warning("Could not write the debug configuration: %s", e)

    def _apply_runtime_mode(self, runtime_mode: str, profile) -> ConnectionResult:
        """Set up the system proxy or the TUN routes for a started core."""
        context = self._context

        if should_manage_system_proxy(runtime_mode):
            port = context.config.inbound_socks_port
            set_system_proxy(http_port=port, socks_port=port)
            return ConnectionResult(True)

        logger.info("Runtime mode '%s': skip system proxy configuration", runtime_mode)
        tun_name = getattr(context.config, "tun_name", "xray0")
        proxy_host = getattr(getattr(profile, "bean", None), "server_address", "")
        ok, state, error = apply_tun_routes(tun_name, proxy_host)
        if not ok:
            # Ядро уже поднято, но трафик через него не пойдёт: откатываем,
            # иначе останется работающий xray без маршрутов.
            logger.error("Failed to apply TUN routes: %s", error)
            try:
                context.xray_manager.stop()
            except Exception:
                logger.debug("Rollback stop failed", exc_info=True)
            context.proxy_state.set_stopped()
            return ConnectionResult(False, error or "Не удалось настроить маршруты TUN")

        self._tun_route_state = state
        return ConnectionResult(True)

    # --- отключение ---

    def disconnect(self) -> ConnectionResult:
        """Stop xray-core and undo everything connect() has set up.

        Каждый шаг изолирован: сбой отключения VPN не должен оставить ядро
        работающим, а сбой ядра — систему с прописанным прокси.
        """
        context = self._context

        try:
            stopped, error = context.xray_manager.stop()
            if not stopped:
                logger.error("Error stopping xray-core: %s", error)
        except Exception as e:
            logger.exception("Exception when stopping xray-core: %s", e)

        self._auto_disconnect_vpn()

        started_mode = getattr(context.proxy_state, "started_mode", ProxyMode.TUN)
        if started_mode == ProxyMode.TUN:
            ok, error = restore_tun_routes(self._tun_route_state)
            if not ok:
                logger.warning("Failed to restore TUN routes: %s", error)
            self._tun_route_state = None

        if should_manage_system_proxy(started_mode):
            clear_system_proxy()

        context.proxy_state.set_stopped()

        if context.monitor is not None:
            context.monitor.stop()

        return ConnectionResult(True)

    def _auto_disconnect_vpn(self) -> None:
        context = self._context
        try:
            profile_id = getattr(context.proxy_state, "started_profile_id", None)
            if not profile_id or profile_id < 0:
                return

            profile = context.profiles.get_profile(profile_id)
            vpn = getattr(profile, "vpn_settings", None) if profile else None
            if not vpn:
                return

            auto_flag = getattr(context.proxy_state, "vpn_auto_connected", False)
            if not (vpn.enabled and getattr(vpn, "auto_connect", False) and auto_flag):
                return

            if disconnect_vpn(vpn.connection_name):
                logger.info("Auto-disconnected VPN '%s'", vpn.connection_name)
            else:
                logger.warning("Failed to auto-disconnect VPN '%s'", vpn.connection_name)
        except Exception as e:
            logger.exception("Error during VPN auto-disconnect: %s", e)
        finally:
            try:
                context.proxy_state.vpn_auto_connected = False
            except Exception:
                logger.debug("Proxy state does not track the VPN flag", exc_info=True)

    # --- перезагрузка конфигурации ---

    def reload_config(self) -> ConnectionResult:
        """Push a freshly built configuration into the running core."""
        context = self._context

        if not context.proxy_state.is_running:
            logger.debug("Proxy is not running, nothing to reload")
            return ConnectionResult(False, NOT_RUNNING)

        profile_id = context.proxy_state.started_profile_id
        profile = context.profiles.get_profile(profile_id)
        if profile is None:
            logger.error("Profile %s not found for reload", profile_id)
            return ConnectionResult(False, PROFILE_NOT_FOUND)

        config = build_session_config(context, profile)
        if not config:
            logger.error("Failed to create configuration for reload")
            return ConnectionResult(False, NO_CONFIG)

        self._write_debug_config(config, profile_id)

        try:
            reloaded, error = context.xray_manager.reload_config(config)
        except Exception as e:
            logger.exception("Error reloading xray-core: %s", e)
            return ConnectionResult(False, str(e))

        if not reloaded:
            logger.error("Error reloading xray-core: %s", error)
            return ConnectionResult(False, error or "Не удалось перезагрузить конфигурацию")

        logger.info("Configuration reloaded successfully")
        return ConnectionResult(True)
