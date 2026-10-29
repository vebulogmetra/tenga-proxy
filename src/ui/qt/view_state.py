"""Состояние представления Windows; операции выполняет общий контроллер."""

from __future__ import annotations

from dataclasses import dataclass, replace

from src.ui.logic.status import ConnectionState, StatusView, status_view


@dataclass
class ConnectionPresentation:
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
            title = "Отключение…" if self.operation == "disconnect" else view.title
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
