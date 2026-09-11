"""Presentation logic for the connection status card (GTK-free).

Виджет получает готовый `StatusView` и только раскладывает его по меткам,
поэтому тексты и классы проверяются обычным pytest без дисплея.
"""

from __future__ import annotations

from dataclasses import dataclass
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
            button_label="Отменить",
            button_class="destructive-action",
            show_spinner=True,
            metrics=metrics,
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
