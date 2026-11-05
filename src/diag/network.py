"""Какая сеть проверяется и можно ли в ней идти напрямую. Здесь нет ничего об оценке."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.diag.models import AddressFamily
from src.sys import netbind


@dataclass(frozen=True)
class DirectPolicy:
    """Что запущено в приложении: читается из AppContext, в CLI всё выключено."""

    tun_interface: str | None = None
    kill_switch: bool = False


@dataclass(frozen=True)
class NetworkState:
    interface: str | None
    kind: str
    addresses: tuple[str, ...]
    policy: DirectPolicy

    @property
    def under_tun(self) -> bool:
        return self.policy.tun_interface is not None

    @property
    def available(self) -> bool:
        return self.interface is not None and bool(self.addresses)

    @property
    def transport_family(self) -> AddressFamily:
        # Bootstrap идёт по имеющимся адресам сети; вопрос A/AAAA от него не зависит.
        if any(":" not in a for a in self.addresses) or not self.addresses:
            return AddressFamily.IPV4
        return AddressFamily.IPV6

    @property
    def restricted(self) -> bool:
        """Прямой путь не проверить: закрыт блокировкой или обход TUN здесь не подтверждён."""
        return self.policy.kill_switch or (self.under_tun and not netbind.binding_confirmed())


def read_network_state(policy: DirectPolicy) -> NetworkState:
    exclude = (policy.tun_interface,) if policy.tun_interface else ()
    interface = netbind.physical_interface(exclude)
    if interface is None:
        return NetworkState(None, "OTHER", (), policy)
    return NetworkState(
        interface,
        netbind.interface_kind(interface),
        netbind.interface_addresses(interface),
        policy,
    )


class NetworkWatcher:
    """Опрос вместо событий: смена сети или режима TUN обрывает проверку прямого пути."""

    def __init__(
        self,
        baseline: NetworkState,
        policy: Callable[[], DirectPolicy],
        read: Callable[[DirectPolicy], NetworkState] = read_network_state,
    ):
        self._baseline = baseline
        self._policy = policy
        self._read = read

    def changed(self) -> bool:
        state = self._read(self._policy())
        return (state.interface, state.addresses, state.policy) != (
            self._baseline.interface,
            self._baseline.addresses,
            self._baseline.policy,
        )
