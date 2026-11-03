"""Presentation logic for the connection status card (GTK-free).

Виджет получает готовый `StatusView` и только раскладывает его по меткам,
поэтому тексты и классы проверяются обычным pytest без дисплея.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from src.ui.logic.formatting import format_bytes


class ConnectionState(StrEnum):
    """Connection state shown by the status card.

    Отдельное перечисление, а не поля `ProxyState`: карточке нужно промежуточное
    состояние `CONNECTING`, которого в состоянии прокси нет.
    """

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    BLOCKED = "blocked"


SWITCH_LABEL = "Переключить на выбранный"
EMPTY_TITLE = "Добавьте сервер или подписку"
BLOCKED_BANNER = "Соединение потеряно. Трафик закрыт, локальная сеть доступна"
RELEASE_BLOCK_LABEL = "Снять блокировку"


@dataclass(frozen=True)
class StatusView:
    """Everything the status card needs to render itself."""

    title: str
    subtitle: str
    icon_name: str
    css_class: str
    button_label: str
    show_spinner: bool
    metric_items: tuple[tuple[str, str], ...] = ()
    mode: str = ""
    # Логотип есть всегда: цветной, только когда соединение установлено.
    # Ожидание и ошибку показывают спиннер и значок поверх него.
    logo_desaturated: bool = True
    # Пока операция идёт, кнопка недоступна: контроллер не умеет прерывать
    # начатое подключение, а повторное нажатие дало бы только тост.
    action_enabled: bool = True


def mode_text(proxy_mode: str) -> str:
    """Name the proxy mode for the card."""
    return "Режим Системный прокси" if proxy_mode == "system" else "Режим TUN"


def switch_hint(target_name: str) -> str:
    """Tooltip of the switch button: the button itself does not name its target."""
    return f"Подключить: {target_name}"


def action_hint(view: StatusView) -> str:
    """Explain what pressing the logo does in this state."""
    if view.show_spinner:
        return view.title
    if not view.action_enabled:
        return "Сначала добавьте или выберите сервер"
    if view.css_class == "status-connected":
        return "Нажмите на логотип для отключения"
    if view.css_class == "status-error":
        return "Нажмите на логотип для повторного подключения"
    if view.css_class == "status-blocked":
        return "Нажмите на логотип, чтобы подключить сервер прошлого сеанса"
    return "Нажмите на логотип для подключения"


def summary_line(view: StatusView) -> str:
    """Join the mode and metrics into one line that wraps only between items."""
    items = [f"{caption} {value}" for caption, value in view.metric_items]
    if view.mode:
        items.insert(0, view.mode)
    return " · ".join(item.replace(" ", " ") for item in items)


def status_view(
    state: ConnectionState,
    *,
    profile_name: str = "",
    latency_ms: int | None = None,
    upload_bytes: int | None = None,
    download_bytes: int | None = None,
    mode: str = "",
) -> StatusView:
    """Describe how the status card should look in the given state.

    Причину ошибки карточка показывает строкой проверки (`health_text`), а в
    подписи остаётся сервер, который не удалось подключить.
    """
    items = []
    if latency_ms is not None and latency_ms >= 0:
        items.append(("Задержка", f"{latency_ms} мс"))
    if upload_bytes is not None and download_bytes is not None:
        items.extend(
            (
                ("↓ Получено", format_bytes(download_bytes)),
                ("↑ Отправлено", format_bytes(upload_bytes)),
            )
        )
    metric_items = tuple(items)

    if state is ConnectionState.CONNECTED:
        return StatusView(
            title="Подключено",
            subtitle=profile_name or "Сервер неизвестен",
            icon_name="network-vpn-symbolic",
            css_class="status-connected",
            button_label="Отключить",
            show_spinner=False,
            metric_items=metric_items,
            mode=mode,
            logo_desaturated=False,
        )

    if state is ConnectionState.CONNECTING:
        return StatusView(
            title="Подключение…",
            subtitle=profile_name,
            icon_name="network-transmit-receive-symbolic",
            css_class="status-connecting",
            button_label="Подключение…",
            show_spinner=True,
            metric_items=metric_items,
            mode=mode,
            action_enabled=False,
        )

    if state is ConnectionState.ERROR:
        return StatusView(
            title="Ошибка",
            subtitle=profile_name,
            icon_name="dialog-warning-symbolic",
            css_class="status-error",
            button_label="Повторить",
            show_spinner=False,
            metric_items=metric_items,
            mode=mode,
        )

    if state is ConnectionState.BLOCKED:
        return StatusView(
            title="Трафик заблокирован",
            subtitle=profile_name,
            icon_name="dialog-warning-symbolic",
            css_class="status-blocked",
            button_label="Переподключить",
            show_spinner=False,
            metric_items=metric_items,
            mode=mode,
        )

    return StatusView(
        title="Отключено",
        subtitle=profile_name,
        icon_name="network-offline-symbolic",
        css_class="status-disconnected",
        button_label="Подключить",
        show_spinner=False,
        metric_items=metric_items,
        mode=mode,
    )


def health_text(
    *, running: bool, checked: bool, proxy_ok: bool, last_check: str, error: str = ""
) -> str:
    """Describe the monitor's check of the running session, or the last failure.

    «Подключено» на карточке значит только, что сессия запущена; работает ли
    соединение, говорит эта строка, и только по данным монитора.
    """
    if error:
        return error
    if not running:
        return ""
    if not checked:
        return "Проверка соединения ещё не выполнена"
    if not proxy_ok:
        return "Прокси запущен, соединение не прошло проверку"
    return f"Последняя проверка соединения: {last_check}"


@dataclass
class ConnectionPresentation:
    """Connection state as the card shows it, between controller events.

    Ошибку держит до новой попытки или до настоящей смены состояния прокси:
    контроллер перерисовывает окно сразу после `show_error`, и без этого
    ошибку тут же заменило бы «Отключено».
    """

    operation: str = ""
    target_name: str = ""
    error: str = ""
    error_snapshot: tuple[bool, int | None] | None = None
    check_session: tuple[bool, int | None] | None = None
    check_baseline: float = 0.0

    def check_done(self, *, running: bool, active_id: int | None, last_check_time: float) -> bool:
        """Tell whether the monitor checked the current session.

        Время проверки, бывшее на момент начала сессии, относится к прошлому
        подключению и проверкой этой сессии не считается.
        """
        session = (running, active_id)
        if self.check_session != session:
            self.check_session = session
            self.check_baseline = last_check_time
        return bool(last_check_time and last_check_time > self.check_baseline)

    def begin(self, operation: str, target_name: str = "") -> None:
        self.operation = operation
        self.target_name = target_name
        self.error = ""
        self.error_snapshot = None

    def fail(self, message: str, snapshot: tuple[bool, int | None]) -> None:
        self.operation = ""
        self.error = message
        self.error_snapshot = snapshot

    def resolve(
        self,
        *,
        running: bool,
        active_id: int | None,
        busy: bool,
        profile_name: str,
        mode: str,
        upload: int,
        download: int,
        latency: int | None,
        has_profiles: bool = True,
        can_connect: bool = True,
        blocked: bool = False,
    ) -> StatusView:
        snapshot = (running, active_id if running else None)
        if self.error_snapshot is not None and snapshot != self.error_snapshot:
            self.error = ""
            self.error_snapshot = None
        if busy:
            view = status_view(
                ConnectionState.CONNECTING,
                profile_name=self.target_name or profile_name,
                mode=mode,
            )
            # Об отключении оболочка может и не сообщить: занятый поток при
            # работающем прокси без начатого подключения — это отключение.
            disconnecting = self.operation == "disconnect" or (not self.operation and running)
            title = "Отключение…" if disconnecting else view.title
            return replace(view, title=title, button_label=title)
        if self.operation == "disconnect" and running:
            self.fail("Не удалось отключиться. Подробности в журнале.", snapshot)
        self.operation = ""
        if running:
            return status_view(
                ConnectionState.CONNECTED,
                profile_name=profile_name,
                mode=mode,
                upload_bytes=upload,
                download_bytes=download,
                latency_ms=latency,
            )
        if blocked:
            # Важнее ошибки: причина видна в строке проверки, а закрытый трафик — нет.
            return status_view(ConnectionState.BLOCKED, profile_name=profile_name, mode=mode)
        state = ConnectionState.ERROR if self.error else ConnectionState.DISCONNECTED
        view = replace(
            status_view(state, profile_name=profile_name, mode=mode), action_enabled=can_connect
        )
        if not has_profiles and not self.error:
            view = replace(view, title=EMPTY_TITLE)
        return view


def is_traffic_blocked(state) -> bool:
    """Показывать ли «Трафик заблокирован»: закрыто, а сеанса нет."""
    return bool(state.traffic_blocked) and not state.is_running
