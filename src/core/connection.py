"""Starting and stopping the proxy, without any GTK involvement.

Раньше эта последовательность жила прямо в GTK3-приложении вперемешку с
уведомлениями трея, из-за чего её нельзя было ни проверить тестом, ни повторно
использовать в новом интерфейсе. Здесь она сведена к трём методам, а результат
возвращается структурой: причина отказа нужна и карточке состояния, и трею.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.core import core_pid
from src.core.config_builder import UnsafeConfigError, build_session_config, intercepts_dns
from src.core.health_probe import (
    attach_health_inbound,
    new_health_endpoint,
    redact_health_credentials,
)
from src.core.proxy_mode import normalize_proxy_mode, should_manage_system_proxy
from src.db.config import ProxyMode
from src.sys.firewall_policy import FirewallPolicy, Level
from src.sys.proxy import clear_system_proxy, set_system_proxy
from src.sys.tun_access import tun_problems
from src.sys.tun_dns import route_system_dns_to_tun
from src.sys.tun_firewall import apply_firewall, remove_firewall
from src.sys.tun_route import apply_tun_routes, restore_tun_routes
from src.sys.vpn import connect_vpn, disconnect_vpn, is_vpn_active
from src.ui.logic.settings_state import runtime_snapshot

if TYPE_CHECKING:
    from src.core.context import AppContext
    from src.sys.tun_route import TunRouteState

logger = logging.getLogger("tenga.core.connection")

PROFILE_NOT_FOUND = "Сервер не найден"
NO_CONFIG = "Не удалось построить конфигурацию сервера"
UNSAFE_CONFIG = "Конфигурация отклонена"
IPV6_BLOCK_WARNING = "IPv6 не заблокирован, трафик по нему может идти мимо прокси: {error}"

# Сколько выход ждёт начатое подключение: VPN и маршруты укладываются в
# секунды, а дольше держать закрывающееся приложение незачем.
SHUTDOWN_TIMEOUT = 10.0


@dataclass(frozen=True)
class ConnectionResult:
    """Outcome of one connect or disconnect."""

    ok: bool
    error: str = ""
    # Подключение состоялось, но с оговоркой, которую пользователю надо показать.
    warning: str = ""


class ConnectionService:
    """Owns the proxy lifecycle for one application context."""

    def __init__(self, context: AppContext) -> None:
        self._context = context
        self._tun_route_state: TunRouteState | None = None
        # Стоит ли наша таблица nftables: переживает сеанс, если ядро упало.
        self._block_held = False
        # Сервер сеанса, упавшего вместе с ядром: ему принадлежит поднятый VPN.
        self._crashed_profile_id = -1

    def _session_inputs(self, profile):
        from src.db.data_store import DataStore

        context = self._context
        if not isinstance(context.config, DataStore):
            return context, profile
        frozen = copy.copy(context)
        settings = copy.deepcopy(context.config)
        if isinstance(getattr(type(context), "config", None), property):
            frozen._config = settings
        else:
            frozen.config = settings
        return frozen, copy.deepcopy(profile)

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

        build_context, profile = self._session_inputs(profile)
        settings = build_context.config
        self._auto_connect_vpn(profile, profile_id)

        runtime_mode = normalize_proxy_mode(getattr(settings, "proxy_mode", None))
        try:
            config = build_session_config(build_context, profile)
        except UnsafeConfigError as e:
            return ConnectionResult(False, f"{UNSAFE_CONFIG}: {e}")
        if not config:
            logger.error("Could not build a configuration for profile %s", profile_id)
            return ConnectionResult(False, NO_CONFIG)

        applied_settings = runtime_snapshot(settings, profile)
        health_endpoint = new_health_endpoint()
        attach_health_inbound(config, health_endpoint)
        self._write_debug_config(config, profile_id)

        warning = ""
        if runtime_mode == ProxyMode.TUN:
            warning = self._block_traffic(settings)
        self._crashed_profile_id = -1

        try:
            started, error = context.xray_manager.start(config)
        except Exception as e:
            logger.exception("Error starting xray-core: %s", e)
            self._release_table()
            return ConnectionResult(False, str(e))

        if not started:
            logger.error("Error starting xray-core: %s", error)
            self._release_table()
            message = error or "Не удалось запустить xray-core"
            if runtime_mode == ProxyMode.TUN:
                message = self._explain_tun_failure(message)
            return ConnectionResult(False, message)

        self._remember_core()
        context.proxy_state.applied_settings = applied_settings
        context.proxy_state.health_endpoint = health_endpoint
        context.proxy_state.set_running(profile_id, mode=runtime_mode)

        routed = self._apply_runtime_mode(runtime_mode, profile, settings=settings)
        if not routed.ok:
            return routed

        if runtime_mode == ProxyMode.TUN and intercepts_dns(config):
            self._route_system_dns(getattr(settings, "tun_name", "xray0"))

        if context.monitor is not None:
            context.monitor.start()

        return ConnectionResult(True, warning=warning)

    def _block_traffic(self, settings) -> str:
        """Таблица nftables до запуска ядра: окна, когда трафик идёт мимо, нет.

        Возвращает предупреждение, если уровень ipv6_only поставить не удалось:
        блокировку пользователь не включал, срывать подключение нельзя.
        """
        tun_name = getattr(settings, "tun_name", "xray0")
        ok, error = apply_firewall(FirewallPolicy(Level.IPV6_ONLY, tun_name))
        if ok:
            self._block_held = True
            return ""
        logger.warning("IPv6 block not applied: %s", error)
        return IPV6_BLOCK_WARNING.format(error=error)

    def _release_table(self) -> None:
        if not self._block_held:
            return
        ok, error = remove_firewall()
        if ok:
            self._block_held = False
        else:
            logger.warning("Failed to remove the firewall table: %s", error)

    def _remember_core(self) -> None:
        manager = self._context.xray_manager
        if manager.pid is not None:
            core_pid.remember(manager.pid, manager.binary_path)

    def _explain_tun_failure(self, error: str) -> str:
        """Заменить ошибку ядра или sudo тем, чего не хватает системе для TUN.

        Исходная ошибка уже в журнале; пользователю нужнее причина и команда,
        которая её исправит.
        """
        try:
            problems = tun_problems(self._context.xray_manager.binary_path)
        except Exception:
            logger.debug("TUN access check failed", exc_info=True)
            return error
        return "\n".join(problems) if problems else error

    def _route_system_dns(self, tun_name=None) -> None:
        """Направить системный DNS в TUN; отказ не срывает подключение."""
        tun_name = tun_name or getattr(self._context.config, "tun_name", "xray0")
        ok, error = route_system_dns_to_tun(tun_name)
        if not ok:
            logger.warning("Системный DNS не направлен в %s: %s", tun_name, error)

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
            self._reset_vpn_flag()
            return

        if is_vpn_active(vpn.connection_name):
            # Флаг не трогаем: VPN мог поднять прошлый сеанс, упавший вместе с
            # ядром, и погасить его при отключении всё ещё нам.
            return

        self._reset_vpn_flag()
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
            # Учётные данные служебного inbound'а на диск не пишутся.
            safe_config = redact_health_credentials(config)
            path.write_text(json.dumps(safe_config, indent=2), encoding="utf-8")
            logger.info("Configured profile id=%s, file: %s", profile_id, path)
        except OSError as e:
            # Конфигурация нужна только для разбора проблем: не пишется —
            # подключение всё равно должно состояться.
            logger.warning("Could not write the debug configuration: %s", e)

    def _apply_runtime_mode(self, runtime_mode: str, profile, *, settings=None) -> ConnectionResult:
        """Set up the system proxy or the TUN routes for a started core."""
        context = self._context
        settings = settings if settings is not None else context.config

        if should_manage_system_proxy(runtime_mode):
            port = settings.inbound_socks_port
            set_system_proxy(http_port=port, socks_port=port)
            return ConnectionResult(True)

        logger.info("Runtime mode '%s': skip system proxy configuration", runtime_mode)
        tun_name = getattr(settings, "tun_name", "xray0")
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
            core_pid.forget()
            self._release_table()
            context.proxy_state.set_stopped()
            return ConnectionResult(
                False, self._explain_tun_failure(error or "Не удалось настроить маршруты TUN")
            )

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

        # Сразу за ядром: VPN гасится до 30 с, а systemd при завершении сеанса
        # столько не ждёт и оставил бы систему закрытой.
        self._release_table()
        profile_id = self._context.proxy_state.started_profile_id
        self._finish_session()
        self._auto_disconnect_vpn(profile_id)
        return ConnectionResult(True)

    def handle_core_exit(self) -> int:
        """Ядро вышло само: убрать маршруты и прокси, VPN оставить.

        VPN держится ради перезапуска: гасить и поднимать его заново — десятки
        секунд `nmcli`. Возвращает профиль упавшего сеанса, а -1 — если сеанса
        уже нет и отключение успело раньше сигнала.
        """
        context = self._context
        if not context.proxy_state.is_running:
            return -1
        profile_id = context.proxy_state.started_profile_id
        try:
            context.xray_manager.stop()
        except Exception:
            logger.debug("Cleanup after core exit failed", exc_info=True)
        self._finish_session()
        self._crashed_profile_id = profile_id
        return profile_id

    def release_block(self) -> ConnectionResult:
        """Сеанса больше нет: снять таблицу и погасить поднятый им VPN."""
        self._release_table()
        self._auto_disconnect_vpn(self._crashed_profile_id)
        self._crashed_profile_id = -1
        return ConnectionResult(True)

    def _finish_session(self) -> None:
        context = self._context
        core_pid.forget()
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

    def shutdown(
        self, pending: threading.Thread | None = None, timeout: float = SHUTDOWN_TIMEOUT
    ) -> None:
        """Stop the proxy before the process exits.

        Поток подключения — демон: при выходе он погибает на полуслове, а
        запущенный им xray остаётся сиротой и держит TUN-интерфейс. Поэтому
        сначала ждём начатое подключение, затем гасим ядро, даже если до
        `set_running` дело не дошло.
        """
        if pending is not None and pending.is_alive():
            pending.join(timeout)
            if pending.is_alive():
                logger.warning("Connection still in progress on exit, stopping the core anyway")

        if self._context.proxy_state.is_running or self._context.xray_manager.is_running:
            self.disconnect()
        elif self._block_held:
            self.release_block()

    def _auto_disconnect_vpn(self, profile_id: int) -> None:
        context = self._context
        try:
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
