"""Synthetic Qt visual acceptance: python -m tests.support.render_windows_ui DIR.

QT_QPA_PLATFORM and QT_SCALE_FACTOR select the backend and scale. No network
session is started; all settings and logs live in a temporary directory.
"""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.core.context import AppContext
from src.db.config import ProxyMode
from src.fmt import parse_link
from src.ui.logic.status import ConnectionState, status_view
from src.ui.qt.application import QtApplication
from src.ui.qt.dialogs.settings import SettingsDialog
from src.ui.qt.theme import apply_theme
from src.ui.qt.window import MainWindow
from tests.test_ui_qt_application import FakeService


def render(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    qt = QApplication.instance() or QApplication([])
    with TemporaryDirectory(dir=output) as directory:
        context = AppContext(config_dir=Path(directory))
        context.config.proxy_mode = ProxyMode.SYSTEM_PROXY
        app = QtApplication(context, with_tray=False)
        app.set_connection_service(FakeService(context))
        for city in ("Амстердам", "Франкфурт", "Хельсинки", "Париж"):
            app.controller.add_profile_from_bean(
                parse_link("vless://11111111-2222-3333-4444-555555555555@example.org:443#" + city)
            )
        app.window = MainWindow(app, context)
        if "--interactive" not in sys.argv:
            app.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        app.activate()
        window = app.window
        window.diagnostics._log_dir = lambda: Path(directory)
        entries = list(context.profiles.profiles.values())
        for number, entry in enumerate(entries):
            entry.latency_ms = 42 + number * 13
        context.proxy_state.upload_bytes = 12 * 1024 * 1024
        context.proxy_state.download_bytes = 128 * 1024 * 1024
        context.proxy_state.set_running(entries[0].id, mode="system")
        window.refresh_pages()
        window.tree.setCurrentIndex(window.model.profile_index(entries[1].id))
        window.tree.setFocus()
        for theme in ("dark", "light", "system"):
            apply_theme(theme)
            for width, height in ((900, 540), (1180, 760)):
                window.resize(width, height)
                for _ in range(4):
                    qt.processEvents()
                assert window.width() == width, (window.size(), width)
                assert window.height() == height, (window.size(), height)
                card = window.status_card
                assert card.health.geometry().bottom() < card.height()
                assert window.latency_button.isVisible()
                assert window.switch_button.isVisible()
                window.grab().save(str(output / f"main-{theme}-{width}.png"))
                window.show_diagnostics()
                qt.processEvents()
                assert window.size().width() == width and window.size().height() == height
                assert window.diagnostics.view.height() >= 160
                window.grab().save(str(output / f"diagnostics-{theme}-{width}.png"))
                window.back_button.click()
        context.config.theme = "dark"
        apply_theme("dark")
        window.resize(1180, 760)
        # Prevent access to any real logs, including during asynchronous refresh.
        window.diagnostics._log_dir = lambda: Path(directory)
        (Path(directory) / "tenga_gui.log").write_text(
            "14:31:55 | UI | Синтетический пример журнала\n"
            "14:32:08 | UI | Проверка ещё не выполнена\n",
            encoding="utf-8",
        )
        window.show_diagnostics()
        if window.diagnostics.thread is not None:
            window.diagnostics.thread.join(5)
        window.diagnostics.set_active(False)
        qt.processEvents()
        window.grab().save(str(output / "diagnostics.png"))
        dialog = SettingsDialog(app, dispatch=app.loop.dispatch, parent=window)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        dialog.show()
        qt.processEvents()
        dialog.grab().save(str(output / "settings.png"))
        dialog.reject()
        window.monitoring_button.setChecked(False)
        for state in (
            ConnectionState.DISCONNECTED,
            ConnectionState.CONNECTED,
            ConnectionState.CONNECTING,
            ConnectionState.ERROR,
        ):
            window.status_card.update_view(status_view(state, profile_name="Амстердам"))
            qt.processEvents()
            window.status_card.grab().save(str(output / f"monolith-{state.value}.png"))
        if "--interactive" in sys.argv:
            window.refresh_status()
            window.present()
            qt.exec()
        window.detach()
        window.hide()


if __name__ == "__main__":
    render(Path(sys.argv[1]).resolve())
