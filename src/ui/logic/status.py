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


@dataclass(frozen=True)
class StatusView:
    """Everything the status card needs to render itself."""

    title: str
    subtitle: str
    icon_name: str
    css_class: str
    button_label: str
    button_class: str
    show_spinner: bool
    metrics: str = ""
    # Логотип приложения вместо системной иконки: цветной, когда соединение
    # установлено, и обесцвеченный, когда нет. В состояниях «подключение» и
    # «ошибка» показываются спиннер и предупреждение, логотип там не нужен.
    use_logo: bool = False
    logo_desaturated: bool = False
    # Пока операция идёт, кнопка недоступна: контроллер не умеет прерывать
    # начатое подключение, а повторное нажатие дало бы только тост.
    action_enabled: bool = True


def metrics_text(
    latency_ms: int | None = None,
    upload_bytes: int | None = None,
    download_bytes: int | None = None,
    mode: str = "",
) -> str:
    """Build the metrics line, dropping every part that is unknown."""
    parts: list[str] = []

    if latency_ms is not None and latency_ms >= 0:
        parts.append(f"{latency_ms} ms")

    if upload_bytes is not None and download_bytes is not None:
        parts.append(f"↑ {format_bytes(upload_bytes)} ↓ {format_bytes(download_bytes)}")

    if mode:
        parts.append(mode)

    return " · ".join(parts)


def status_view(
    state: ConnectionState,
    *,
    profile_name: str = "",
    error: str = "",
    latency_ms: int | None = None,
    upload_bytes: int | None = None,
    download_bytes: int | None = None,
    mode: str = "",
) -> StatusView:
    """Describe how the status card should look in the given state."""
    metrics = metrics_text(latency_ms, upload_bytes, download_bytes, mode)

    if state is ConnectionState.CONNECTED:
        return StatusView(
            title="Подключено",
            subtitle=profile_name or "Профиль неизвестен",
            icon_name="network-vpn-symbolic",
            css_class="status-connected",
            button_label="Отключить",
            button_class="destructive-action",
            show_spinner=False,
            metrics=metrics,
            use_logo=True,
        )

    if state is ConnectionState.CONNECTING:
        return StatusView(
            title="Подключение…",
            subtitle=profile_name,
            icon_name="network-transmit-receive-symbolic",
            css_class="status-connecting",
            button_label="Подключение…",
            button_class="suggested-action",
            show_spinner=True,
            metrics=metrics,
            action_enabled=False,
        )

    if state is ConnectionState.ERROR:
        return StatusView(
            title="Ошибка",
            subtitle=error or "Соединение не установлено",
            icon_name="dialog-warning-symbolic",
            css_class="status-error",
            button_label="Подключить",
            button_class="suggested-action",
            show_spinner=False,
            metrics=metrics,
        )

    return StatusView(
        title="Отключено",
        subtitle="",
        icon_name="network-offline-symbolic",
        css_class="status-disconnected",
        button_label="Подключить",
        button_class="suggested-action",
        show_spinner=False,
        metrics=metrics,
        use_logo=True,
        logo_desaturated=True,
    )


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
    ) -> StatusView:
        snapshot = (running, active_id if running else None)
        if self.error_snapshot is not None and snapshot != self.error_snapshot:
            self.error = ""
            self.error_snapshot = None
        if busy:
            view = status_view(
                ConnectionState.CONNECTING, profile_name=self.target_name or profile_name
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
        if self.error:
            view = status_view(ConnectionState.ERROR, error=self.error)
            return replace(view, button_label="Повторить")
        view = status_view(ConnectionState.DISCONNECTED)
        return replace(view, subtitle=profile_name)
