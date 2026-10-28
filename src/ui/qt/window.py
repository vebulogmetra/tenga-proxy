"""Главное окно Qt: карточка, плашка, дерево серверов, поиск, мониторинг.

Рамку, заголовок и Snap Layouts даёт система: окно — обычный `QMainWindow`.
Окно рисует состояние и передаёт намерения приложению; решения принимает
`AppController`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from src.ui.logic.geometry import MIN_HEIGHT, MIN_WIDTH, Geometry, format_geometry, parse_geometry
from src.ui.logic.monitoring_view import monitoring_view
from src.ui.logic.profiles_view import SortKey, build_profile_rows
from src.ui.logic.status import ConnectionState, status_view
from src.ui.qt.models import (
    GROUP,
    NAME_COLUMN,
    PROFILE,
    SORT_KEYS,
    ProfileTreeModel,
)
from src.ui.qt.widgets.status_card import StatusCard
from src.ui.qt.widgets.toast import Toast

if TYPE_CHECKING:
    from src.core.context import AppContext
    from src.ui.logic.latency import PingProgress
    from src.ui.qt.application import QtApplication

logger = logging.getLogger("tenga.ui.qt.window")

# Пункты меню «☰»: имя действия приложения → подпись.
MAIN_MENU = (
    ("refresh-subscriptions", "Обновить подписки"),
    ("test-latency", "Проверить задержку"),
    ("settings", "Настройки"),
    ("shortcuts", "Сочетания клавиш"),
    ("about", "О программе"),
    ("quit", "Выход"),
)


STYLE_SHEET = Path(__file__).with_name("style.qss")


class _EmptyStatus:
    """Подстановка до появления монитора, как в GTK-окне."""

    proxy_ok = False
    vpn_ok = True
    last_check_time = 0.0
    proxy_error = ""
    vpn_error = ""


class MainWindow(QMainWindow):
    def __init__(self, app: QtApplication, context: AppContext) -> None:
        super().__init__()
        self._app = app
        self._context = context
        self._sort_key = SortKey.NAME
        self._ascending = True
        self._ping_progress: PingProgress | None = None
        self._collapsed: set[int] = set()

        self.setWindowTitle("Veblock")
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)
        geometry = parse_geometry(getattr(context.config, "window_size", ""))
        self.resize(geometry.width, geometry.height)
        self._start_maximized = geometry.maximized

        self._build_ui()
        # На окно, а не на приложение: остальные виджеты (диалоги, меню трея)
        # остаются в чистом системном стиле.
        self.setStyleSheet(STYLE_SHEET.read_text(encoding="utf-8"))
        for action in app.actions.values():
            # Сочетания клавиш работают, пока окно в фокусе.
            self.addAction(action)

        context.proxy_state.add_listener(self._on_proxy_state_changed)
        self.refresh_status()
        self.refresh_pages()

    # --- построение ---

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)

        self.status_card = StatusCard()
        self.status_card.action_clicked.connect(
            lambda: self._app.activate_action("toggle-connection")
        )
        self.monitoring_button = QToolButton()
        self.monitoring_button.setText("Мониторинг")
        self.monitoring_button.setCheckable(True)
        self.monitoring_button.setChecked(True)
        self.status_card.add_tool(self.monitoring_button)
        self.menu_button = QToolButton()
        self.menu_button.setText("☰")
        self.menu_button.setToolTip("Главное меню")
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.main_menu = QMenu(self.menu_button)
        for name, label in MAIN_MENU:
            action = self._app.actions.get(name)
            if action is not None:
                entry = self.main_menu.addAction(label)
                entry.triggered.connect(action.trigger)
        self.menu_button.setMenu(self.main_menu)
        self.status_card.add_tool(self.menu_button)
        layout.addWidget(self.status_card)

        self.pending_banner = QFrame()
        self.pending_banner.setObjectName("pendingBanner")
        banner = QHBoxLayout(self.pending_banner)
        banner.addWidget(QLabel("Изменения применятся после переподключения"), 1)
        self.reconnect_button = QPushButton("Переподключить")
        self.reconnect_button.clicked.connect(lambda: self._app.controller.reconnect_current())
        banner.addWidget(self.reconnect_button)
        self.pending_banner.hide()
        layout.addWidget(self.pending_banner)

        self.model = ProfileTreeModel()
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionsClickable(True)
        self.tree.header().setSortIndicatorShown(True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(NAME_COLUMN, self.tree.header().ResizeMode.Stretch)
        self.tree.header().sectionClicked.connect(self._on_header_clicked)
        self.tree.activated.connect(self._on_activated)
        self.tree.collapsed.connect(lambda index: self._remember_collapsed(index, True))
        self.tree.expanded.connect(lambda index: self._remember_collapsed(index, False))
        layout.addWidget(self.tree, 1)

        self.toast_widget = Toast()
        layout.addWidget(self.toast_widget)

        bottom = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self.refresh_pages())
        bottom.addWidget(self.search, 1)
        layout.addLayout(bottom)

        self.setCentralWidget(central)
        self._build_monitoring_dock()

    def _build_monitoring_dock(self) -> None:
        self.monitoring_dock = QDockWidget("Мониторинг", self)
        self.monitoring_dock.setObjectName("monitoringDock")
        self.monitoring_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        body = QWidget()
        column = QVBoxLayout(body)
        self.monitoring_form = QFormLayout()
        column.addLayout(self.monitoring_form)
        self.last_check = QLabel()
        column.addWidget(self.last_check)
        self.check_button = QPushButton("Проверить сейчас")
        self.check_button.clicked.connect(self._on_check_now)
        column.addWidget(self.check_button)
        column.addStretch(1)
        self.monitoring_dock.setWidget(body)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.monitoring_dock)
        self.monitoring_button.toggled.connect(self.monitoring_dock.setVisible)
        self.monitoring_dock.visibilityChanged.connect(self._on_dock_visibility)

    # --- состояние ---

    def refresh_status(self) -> None:
        from src.ui.logic.settings_state import pending_settings

        self.pending_banner.setVisible(pending_settings(self._context))
        state = self._context.proxy_state
        if state.is_running:
            profile = self._context.profiles.get_profile(state.started_profile_id)
            view = status_view(
                ConnectionState.CONNECTED,
                profile_name=profile.name if profile else "",
                latency_ms=getattr(profile, "latency_ms", None) if profile else None,
                upload_bytes=state.upload_bytes,
                download_bytes=state.download_bytes,
                mode=state.started_mode.upper(),
            )
        else:
            view = status_view(ConnectionState.DISCONNECTED)
        self.status_card.update_view(view)

    def show_connecting(self, profile_name: str = "") -> None:
        self.status_card.update_view(
            status_view(ConnectionState.CONNECTING, profile_name=profile_name)
        )

    def show_error(self, message: str) -> None:
        self.status_card.update_view(status_view(ConnectionState.ERROR, error=message))

    def refresh_pages(self) -> None:
        """Пересобрать дерево, сохранив выделение и свёрнутые группы."""
        selected = self.selected_profile_id()
        store = self._context.profiles
        groups = store.groups
        state = self._context.proxy_state
        rows = build_profile_rows(
            groups,
            {group_id: store.get_profiles_in_group(group_id) for group_id in groups},
            query=self.search.text(),
            sort_key=self._sort_key,
            ascending=self._ascending,
            active_profile_id=state.started_profile_id if state.is_running else -1,
        )
        self.model.set_rows(rows, self._ping_progress)
        for position in range(self.model.rowCount()):
            index = self.model.index(position, NAME_COLUMN)
            group_id = self.model.target(index)[1]
            # Поиск раскрывает всё: совпадение в свёрнутой группе не видно.
            self.tree.setExpanded(
                index, bool(self.search.text()) or group_id not in self._collapsed
            )
        if selected is not None:
            index = self.model.profile_index(selected)
            if index.isValid():
                self.tree.setCurrentIndex(index)
        self.refresh_monitoring()

    def refresh_monitoring(self) -> None:
        monitor = self._context.monitor
        status = monitor.status if monitor is not None else _EmptyStatus()
        state = self._context.proxy_state
        profile = (
            self._context.profiles.get_profile(state.started_profile_id)
            if state.is_running
            else None
        )
        routing = getattr(profile, "routing_settings", None) or self._context.config.routing
        vpn_settings = getattr(profile, "vpn_settings", None)
        vpn_enabled = bool(
            vpn_settings
            and getattr(vpn_settings, "enabled", False)
            and getattr(vpn_settings, "connection_name", "")
        )
        view = monitoring_view(
            status,
            routing,
            is_running=state.is_running,
            profile_found=profile is not None,
            vpn_enabled=vpn_enabled,
            vpn_is_up=vpn_enabled and status.vpn_ok,
        )
        while self.monitoring_form.rowCount():
            self.monitoring_form.removeRow(0)
        for row in (*view.connection, *view.routing):
            value = QLabel(row.value)
            value.setProperty("state", row.css_class)
            value.setWordWrap(True)
            self.monitoring_form.addRow(row.title, value)
        self.last_check.setText(f"Последняя проверка: {view.last_check}")

    # --- запросы оболочки контроллера ---

    def selected_profile_id(self) -> int | None:
        target = self.model.target(self.tree.currentIndex())
        if target is None or target[0] != PROFILE:
            return None
        return target[1]

    def set_sort(self, sort_key: SortKey, *, ascending: bool = True) -> None:
        self._sort_key = sort_key
        self._ascending = ascending
        column = next(c for c, key in SORT_KEYS.items() if key is sort_key)
        order = Qt.SortOrder.AscendingOrder if ascending else Qt.SortOrder.DescendingOrder
        self.tree.header().setSortIndicator(column, order)
        self.refresh_pages()

    def set_ping_progress(self, progress: PingProgress | None) -> None:
        self._ping_progress = progress
        for row in range(self.model.rowCount()):
            group_id = self.model.target(self.model.index(row, NAME_COLUMN))[1]
            self.model.update_group_progress(group_id, progress)

    def update_group_progress(self, group_id: int) -> None:
        self.model.update_group_progress(group_id, self._ping_progress)

    def toast(self, text: str, *, button: str | None = None, action: str | None = None) -> None:
        on_click = None
        if button and action:
            name = action.removeprefix("app.")

            def on_click() -> None:
                self._app.activate_action(name)

        self.toast_widget.show_message(text, button=button, on_click=on_click)

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    # --- события ---

    def _on_header_clicked(self, column: int) -> None:
        sort_key = SORT_KEYS.get(column)
        if sort_key is None:
            # По «Серверу» не сортируют: вернуть индикатор на текущую колонку.
            self.set_sort(self._sort_key, ascending=self._ascending)
            return
        ascending = not self._ascending if sort_key is self._sort_key else True
        self.set_sort(sort_key, ascending=ascending)

    def _on_activated(self, index) -> None:
        target = self.model.target(index)
        if target is not None and target[0] == PROFILE:
            self._app.controller.select_profile(target[1])

    def _remember_collapsed(self, index, collapsed: bool) -> None:
        target = self.model.target(index)
        if target is None or target[0] != GROUP or self.search.text():
            return
        if collapsed:
            self._collapsed.add(target[1])
        else:
            self._collapsed.discard(target[1])

    def _on_check_now(self) -> None:
        monitor = self._context.monitor
        if monitor is not None:
            monitor.check_now()
        self.refresh_monitoring()

    def _on_dock_visibility(self, visible: bool) -> None:
        # Свёрнутое окно прячет и панель: кнопка следит только за явным закрытием.
        if not self.isMinimized() and self.isVisible():
            self.monitoring_button.setChecked(visible)

    def _on_proxy_state_changed(self, _state) -> None:
        # Состояние меняет поток подключения; виджеты — только из главного.
        self._app.loop.dispatch(self._refresh_after_state_change)

    def _refresh_after_state_change(self) -> None:
        self.refresh_status()
        self.refresh_pages()

    # --- жизненный цикл ---

    def present(self) -> None:
        if self._start_maximized:
            self._start_maximized = False
            self.showMaximized()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:
        """С треем окно прячется, без него закрытие завершает приложение."""
        self.save_geometry()
        if self._app.tray is not None:
            event.ignore()
            self.hide()
            return
        event.accept()
        self._app.quit()

    def detach(self) -> None:
        """Перестать слушать состояние прокси, как `MainWindow.detach()` в GTK."""
        self._context.proxy_state.remove_listener(self._on_proxy_state_changed)

    def save_geometry(self) -> None:
        size = self.normalGeometry().size() if self.isMaximized() else self.size()
        geometry = Geometry(width=size.width(), height=size.height(), maximized=self.isMaximized())
        self._context.config.window_size = format_geometry(geometry)
        try:
            self._context.save_config()
        except Exception as e:
            logger.warning("Could not persist window geometry: %s", e)
