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
from dataclasses import dataclass, replace
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
from src.sys.resolver import system_dns_servers
from src.sys.tun_access import tun_problems
from src.sys.tun_dns import route_system_dns_to_tun
from src.sys.tun_firewall import apply_firewall, remove_firewall
from src.sys.tun_route import apply_tun_routes, restore_tun_routes
from src.sys.vpn import (
    connect_vpn,
    disconnect_vpn,
    get_default_interface,
    is_vpn_active,
    vpn_connection_type,
    vpn_server_addresses,
    vpn_tunnel_interface,
)
from src.ui.logic.settings_state import runtime_snapshot

if TYPE_CHECKING:
    from src.core.context import AppContext
    from src.sys.tun_route import TunRouteState

logger = logging.getLogger("tenga.core.connection")

PROFILE_NOT_FOUND = "Сервер не найден"
NO_CONFIG = "Не удалось построить конфигурацию сервера"
UNSAFE_CONFIG = "Конфигурация отклонена"
IPV6_BLOCK_WARNING = "IPv6 не заблокирован, трафик по нему может идти мимо прокси: {error}"
KILL_SWITCH_NEEDS_DNS = (
    "Блокировка трафика при обрыве требует перехвата DNS: включите его в настройках DNS "
    "или выключите блокировку"
)
KILL_SWITCH_VPN_TYPE = (
    "Блокировка трафика при обрыве не поддерживает VPN «{name}» этого типа (WireGuard, tun): "
    "выключите блокировку или VPN у сервера"
)
KILL_SWITCH_NO_VPN_ADDRESS = (
    "Не удалось узнать адрес сервера VPN «{name}»: блокировка трафика закрыла бы сам VPN"
)
KILL_SWITCH_NO_VPN_INTERFACE = (
    "Не удалось узнать интерфейс VPN «{name}»: блокировка трафика закрыла бы сам VPN"
)
KILL_SWITCH_NOT_APPLIED = "Не удалось включить блокировку трафика: {error}"
DNS_UNPROTECTED = "DNS не защищён: при обрыве запросы имён могут уйти напрямую"

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
        self._policy: FirewallPolicy | None = None
        # VPN, чей интерфейс открыт в таблице: при переподключении имя может смениться.
        self._block_vpn_name: str | None = None
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
        """Start xray-core for one profile, preparing VPN and routing first.

        Смена сервера и перезапуск идут здесь же. Таблица nftables и VPN прошлого
        сеанса при этом остаются: иначе между ядрами трафик ушёл бы напрямую.
        """
        context = self._context

        profile = context.profiles.get_profile(profile_id)
        if profile is None:
            logger.error("Profile %s not found", profile_id)
            return ConnectionResult(False, PROFILE_NOT_FOUND)

        previous_profile_id = self._crashed_profile_id
        if context.proxy_state.is_running:
            previous_profile_id = context.proxy_state.started_profile_id
            self._teardown()

        build_context, profile = self._session_inputs(profile)
        settings = build_context.config
        runtime_mode = normalize_proxy_mode(getattr(settings, "proxy_mode", None))
        tun_name = getattr(settings, "tun_name", "xray0")
        kill_switch = (
            runtime_mode == ProxyMode.TUN and getattr(settings, "tun_kill_switch", False) is True
        )
        # Прошлый сеанс закрыл трафик и пользователь не передумал: неудача его не откроет.
        keeps_block = kill_switch and self._holds_full_block()
        self._open_dns_window()
        self._drop_previous_vpn(previous_profile_id, profile)

        vpn_name = self._profile_vpn_name(profile) if kill_switch else None
        vpn_addresses: tuple[str, ...] = ()
        if vpn_name:
            refusal = self._refuse_vpn(vpn_name)
            if refusal:
                return self._fail(refusal, profile_id, keeps_block)
            vpn_addresses = vpn_server_addresses(vpn_name)
            if not vpn_addresses:
                return self._fail(
                    KILL_SWITCH_NO_VPN_ADDRESS.format(name=vpn_name), profile_id, keeps_block
                )
            if self._block_held:
                # Таблица прошлого сеанса закрыла бы сам VPN нового сервера.
                self._apply_block(
                    FirewallPolicy(
                        Level.FULL,
                        tun_name,
                        None,
                        vpn_addresses,
                        dns_addresses=self._network_dns(tun_name),
                    )
                )

        self._auto_connect_vpn(profile, profile_id)

        try:
            config = build_session_config(build_context, profile)
        except UnsafeConfigError as e:
            return self._fail(f"{UNSAFE_CONFIG}: {e}", profile_id, keeps_block)
        if not config:
            logger.error("Could not build a configuration for profile %s", profile_id)
            return self._fail(NO_CONFIG, profile_id, keeps_block)

        applied_settings = runtime_snapshot(settings, profile)
        health_endpoint = new_health_endpoint()
        attach_health_inbound(config, health_endpoint)
        self._write_debug_config(config, profile_id)

        warnings: list[str] = []
        intercepting = runtime_mode == ProxyMode.TUN and intercepts_dns(config)
        if kill_switch:
            refusal = self._block_everything(tun_name, vpn_name, vpn_addresses, intercepting)
            if refusal:
                return self._fail(refusal, profile_id, keeps_block)
        elif runtime_mode == ProxyMode.TUN:
            warnings.append(self._block_ipv6(tun_name))
        else:
            # Пользователь ушёл из TUN в системный прокси: таблице здесь делать нечего.
            self._release_table()

        try:
            started, error = context.xray_manager.start(config)
        except Exception as e:
            logger.exception("Error starting xray-core: %s", e)
            return self._fail(str(e), profile_id, keeps_block)

        if not started:
            logger.error("Error starting xray-core: %s", error)
            message = error or "Не удалось запустить xray-core"
            if runtime_mode == ProxyMode.TUN:
                message = self._explain_tun_failure(message)
            return self._fail(message, profile_id, keeps_block)

        self._remember_core()
        context.proxy_state.applied_settings = applied_settings
        context.proxy_state.health_endpoint = health_endpoint
        context.proxy_state.set_running(profile_id, mode=runtime_mode)

        routed = self._apply_runtime_mode(runtime_mode, profile, settings=settings)
        if not routed.ok:
            return self._fail(routed.error, profile_id, keeps_block)

        dns_routed = intercepting and self._route_system_dns(tun_name)
        if kill_switch:
            warnings.append(self._close_dns_window(dns_routed))

        self._crashed_profile_id = -1
        self._clear_blocked_state()

        if context.monitor is not None:
            context.monitor.start()

        return ConnectionResult(True, warning="\n".join(filter(None, warnings)))

    # --- блокировка трафика ---

    def _holds_full_block(self) -> bool:
        return self._block_held and self._policy is not None and self._policy.level == Level.FULL

    def _apply_block(self, policy: FirewallPolicy) -> tuple[bool, str]:
        ok, error = apply_firewall(policy)
        if ok:
            self._block_held = True
            self._policy = policy
            if policy.level == Level.FULL:
                core_pid.remember_block()
            else:
                core_pid.forget_block()
        return ok, error

    def _block_ipv6(self, tun_name: str) -> str:
        """Таблица до запуска ядра: окна, когда трафик идёт мимо, нет.

        Возвращает предупреждение, если поставить не удалось: блокировку
        пользователь не включал, срывать подключение нельзя.
        """
        ok, error = self._apply_block(FirewallPolicy(Level.IPV6_ONLY, tun_name))
        if ok:
            return ""
        logger.warning("IPv6 block not applied: %s", error)
        return IPV6_BLOCK_WARNING.format(error=error)

    def _block_everything(
        self,
        tun_name: str,
        vpn_name: str | None,
        vpn_addresses: tuple[str, ...],
        intercepting: bool,
    ) -> str:
        """Поставить уровень `full`; непустая строка — почему подключаться нельзя."""
        if not intercepting:
            return KILL_SWITCH_NEEDS_DNS

        vpn_interface = None
        if vpn_name and is_vpn_active(vpn_name):
            vpn_interface = vpn_tunnel_interface(vpn_name)
            if vpn_interface is None:
                return KILL_SWITCH_NO_VPN_INTERFACE.format(name=vpn_name)

        # VPN не поднялся: подключаемся без него, и его сервер открывать незачем.
        policy = FirewallPolicy(
            Level.FULL,
            tun_name,
            vpn_interface,
            vpn_addresses if vpn_interface else (),
            dns_addresses=self._network_dns(tun_name),
        )
        ok, error = self._apply_block(policy)
        if ok:
            self._block_vpn_name = vpn_name if vpn_interface else None
            return ""
        logger.error("Traffic block not applied: %s", error)
        return self._explain_tun_failure(KILL_SWITCH_NOT_APPLIED.format(error=error))

    def watched_vpn(self) -> str | None:
        """VPN, за интерфейсом которого нужно следить: он открыт в таблице уровня `full`."""
        if not self._holds_full_block() or self._policy is None or not self._policy.vpn_interface:
            return None
        return self._block_vpn_name

    @staticmethod
    def probe_vpn_interface(name: str) -> str | None:
        """Текущий интерфейс VPN; None — VPN сейчас не поднят. Зовёт nmcli: не из главного потока."""
        return vpn_tunnel_interface(name)

    def follow_vpn_interface(self, name: str, interface: str) -> bool:
        """Открыть в таблице новый интерфейс VPN вместо старого. True — таблица изменилась."""
        policy = self._policy
        if name != self.watched_vpn() or policy is None or interface == policy.vpn_interface:
            return False
        ok, error = self._apply_block(replace(policy, vpn_interface=interface))
        if not ok:
            logger.warning("VPN interface %s not opened: %s", interface, error)
            return False
        logger.info("VPN interface changed: %s -> %s", policy.vpn_interface, interface)
        return True

    def _profile_vpn_name(self, profile) -> str | None:
        """VPN, который будет работать в этом сеансе и которому нужны разрешения."""
        vpn = getattr(profile, "vpn_settings", None)
        if not vpn or not vpn.enabled:
            return None
        if getattr(vpn, "auto_connect", False) or is_vpn_active(vpn.connection_name):
            return vpn.connection_name
        return None

    def _refuse_vpn(self, name: str) -> str:
        kind = vpn_connection_type(name)
        if kind == "vpn":
            return ""
        if kind in ("wireguard", "tun"):
            # WireGuard шлёт UDP через output без запасного маршрута: закрыли бы сам VPN.
            return KILL_SWITCH_VPN_TYPE.format(name=name)
        return KILL_SWITCH_NO_VPN_ADDRESS.format(name=name)

    def _open_dns_window(self) -> None:
        """Подключению нужен DNS: имя сервера разрешается системным резолвером."""
        if self._block_held and self._policy is not None and self._policy.dns_closed:
            ok, error = self._apply_block(
                replace(
                    self._policy,
                    dns_closed=False,
                    dns_addresses=self._network_dns(self._policy.tun_name),
                )
            )
            if not ok:
                logger.warning("Could not open the DNS window: %s", error)

    @staticmethod
    def _network_dns(tun_name: str) -> tuple[str, ...]:
        """DNS-серверы текущей сети: их спросит системный резолвер, пока окно открыто."""
        interface = get_default_interface(exclude=(tun_name,))
        return tuple(system_dns_servers(interface)) if interface else ()

    def _close_dns_window(self, dns_routed: bool) -> str:
        """Закрыть порт 53; возвращает предупреждение, если DNS остаётся открытым.

        Закрывать можно, только когда resolved смотрит в TUN: иначе DNS перестанет
        работать совсем, и лучше сказать об этом, чем молча всё сломать.
        """
        state = self._context.proxy_state
        if not dns_routed:
            state.dns_unprotected = True
            return DNS_UNPROTECTED
        state.dns_unprotected = False
        if self._policy is not None:
            ok, error = self._apply_block(replace(self._policy, dns_closed=True))
            if not ok:
                logger.warning("Could not close the DNS window: %s", error)
                state.dns_unprotected = True
                return DNS_UNPROTECTED
        return ""

    def _fail(self, message: str, profile_id: int, keeps_block: bool) -> ConnectionResult:
        """Подключение не состоялось: снять таблицу или оставить закрытым, если просили."""
        if keeps_block:
            state = self._context.proxy_state
            state.traffic_blocked = True
            state.blocked_profile_id = profile_id
            self._crashed_profile_id = profile_id
            if self._policy is not None and not state.dns_unprotected:
                ok, error = self._apply_block(replace(self._policy, dns_closed=True))
                if not ok:
                    logger.warning("Could not close the DNS window: %s", error)
        else:
            self._release_table()
        return ConnectionResult(False, message)

    def _release_table(self) -> None:
        if not self._block_held:
            return
        ok, error = remove_firewall()
        if ok:
            self._block_held = False
            self._policy = None
            self._block_vpn_name = None
            core_pid.forget_block()
        else:
            logger.warning("Failed to remove the firewall table: %s", error)

    def _clear_blocked_state(self) -> None:
        state = self._context.proxy_state
        state.traffic_blocked = False
        state.blocked_profile_id = -1

    def _drop_previous_vpn(self, previous_profile_id: int, profile) -> None:
        """Прошлый сеанс поднял другой VPN: его больше никто не погасит.

        Тот же VPN остаётся: переподнимать его — десятки секунд `nmcli`.
        """
        if previous_profile_id < 0:
            return
        previous = self._context.profiles.get_profile(previous_profile_id)
        old_vpn = getattr(previous, "vpn_settings", None)
        new_vpn = getattr(profile, "vpn_settings", None)
        keeps_it = (
            old_vpn
            and new_vpn
            and new_vpn.enabled
            and new_vpn.connection_name == old_vpn.connection_name
        )
        if not keeps_it:
            self._auto_disconnect_vpn(previous_profile_id)

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

    def _route_system_dns(self, tun_name: str) -> bool:
        """Направить системный DNS в TUN; отказ не срывает подключение."""
        ok, error = route_system_dns_to_tun(tun_name)
        if not ok:
            logger.warning("Системный DNS не направлен в %s: %s", tun_name, error)
        return ok

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
        self._crashed_profile_id = -1
        self._clear_blocked_state()
        return ConnectionResult(True)

    def _teardown(self) -> None:
        """Убрать сеанс перед следующим: таблицу и VPN оставить, между ядрами трафик закрыт."""
        try:
            stopped, error = self._context.xray_manager.stop()
            if not stopped:
                logger.error("Error stopping xray-core: %s", error)
        except Exception as e:
            logger.exception("Exception when stopping xray-core: %s", e)
        self._finish_session()

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
        if self._holds_full_block():
            context.proxy_state.traffic_blocked = True
            context.proxy_state.blocked_profile_id = profile_id
        return profile_id

    def release_block(self) -> ConnectionResult:
        """Сеанса больше нет: снять таблицу и погасить поднятый им VPN."""
        self._release_table()
        self._auto_disconnect_vpn(self._crashed_profile_id)
        self._crashed_profile_id = -1
        self._clear_blocked_state()
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
