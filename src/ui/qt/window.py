"""Главное окно Qt: карточка, плашка, дерево серверов, поиск, мониторинг.

Рамку, заголовок и Snap Layouts даёт система: окно — обычный `QMainWindow`.
Окно рисует состояние и передаёт намерения приложению; решения принимает
`AppController`.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QModelIndex, QPoint, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from src.ui.logic.geometry import Geometry, format_geometry, parse_geometry
from src.ui.logic.monitoring_view import monitoring_view
from src.ui.logic.profiles_view import SortKey, build_profile_rows
from src.ui.logic.status import ConnectionState, status_view
from src.ui.logic.subscriptions_view import build_subscription_rows
from src.ui.qt.icons import flagged
from src.ui.qt.models import (
    ADDRESS_COLUMN,
    GROUP,
    NAME_COLUMN,
    PING_COLUMN,
    PROFILE,
    SORT_KEYS,
    TYPE_COLUMN,
    ProfileTreeModel,
)
from src.ui.qt.view_state import ConnectionPresentation
from src.ui.qt.widgets.diagnostics import DiagnosticsPanel
from src.ui.qt.widgets.profile_delegate import ProfileDelegate
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
    ("quit", "Выход"),
)

# Меню кнопки «Добавить» внизу окна.
ADD_MENU = (
    ("add-profile", "Профиль по ссылке…"),
    ("add-profile-from-clipboard", "Профиль из буфера обмена"),
    ("add-subscription", "Подписка…"),
    ("add-group", "Группа…"),
)

# Меню строк дерева: (действие, подпись); None — разделитель. Как в GTK
# (src/ui/pages/profiles.py), у подписки ещё «Обновить подписку»: списка
# подписок на главном экране Qt нет.
PROFILE_MENU = (
    ("connect-profile", "Подключить"),
    ("profile-routing", "VPN и маршруты…"),
    ("test-profile", "Тест задержки"),
    None,
    ("edit-profile", "Редактировать"),
    ("delete-profile", "Удалить"),
)
GROUP_MENU = (
    ("toggle-group", ""),  # подпись зависит от того, раскрыта ли группа
    ("update-subscription", "Обновить подписку"),
    ("test-group", "Тест задержки"),
    ("keep-working", "Оставить рабочие…"),
    None,
    ("edit-group", "Редактировать"),
    ("delete-group", "Удалить"),
)


STYLE_SHEET = Path(__file__).with_name("style.qss")
CONTENT_MAX_WIDTH = 1000


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
        self.presentation = ConnectionPresentation()
        self._rebuilding = False
        self._monitoring_values: dict[str, QLabel] = {}

        self.setWindowTitle("Veblock")
        available = self.screen().availableGeometry()
        self.setMinimumSize(min(900, available.width()), min(540, available.height() - 40))
        geometry = parse_geometry(
            getattr(context.config, "window_size", ""), default=Geometry(1180, 760)
        )
        self.resize(
            min(geometry.width, available.width()), min(geometry.height, available.height() - 40)
        )
        self._start_maximized = geometry.maximized

        self._build_ui()
        # На окно, а не на приложение: остальные виджеты (диалоги, меню трея)
        # остаются в чистом системном стиле.
        self.setStyleSheet(STYLE_SHEET.read_text(encoding="utf-8"))
        app.qt.paletteChanged.connect(self._schedule_palette_refresh)
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
        self.content_layout = layout
        toolbar = QHBoxLayout()
        brand = QLabel("Veblock")
        brand.setObjectName("brandLabel")
        toolbar.addWidget(brand)
        toolbar.addStretch(1)
        self.settings_button = QPushButton("Настройки")
        self.settings_button.clicked.connect(lambda: self._app.activate_action("settings"))
        toolbar.addWidget(self.settings_button)
        layout.addLayout(toolbar)

        self.status_card = StatusCard()
        self.status_card.setMaximumWidth(CONTENT_MAX_WIDTH)
        self.status_card.action_clicked.connect(
            lambda: self._app.activate_action("toggle-connection")
        )
        self.monitoring_button = QToolButton()
        self.monitoring_button.setObjectName("monitoringToggle")
        self.monitoring_button.setText("Диагностика")
        self.monitoring_button.setCheckable(True)
        self.monitoring_button.setChecked(self._context.config.monitoring_panel)
        self.menu_button = QPushButton("Меню")
        self.menu_button.setAccessibleName("Главное меню")
        self.menu_button.setToolTip("Главное меню")
        self.main_menu = QMenu(self.menu_button)
        for name, label in MAIN_MENU:
            action = self._app.actions.get(name)
            if action is not None:
                entry = self.main_menu.addAction(label)
                entry.triggered.connect(action.trigger)
        self.menu_button.setMenu(self.main_menu)
        self.main_menu.addAction("Журнал…", self.show_diagnostics)
        toolbar.addWidget(self.menu_button)
        hero_row = QHBoxLayout()
        hero_row.setContentsMargins(12, 0, 12, 0)
        hero_row.addStretch(1)
        hero_row.addWidget(self.status_card, 1000)
        hero_row.addStretch(1)
        layout.addLayout(hero_row)

        self.pending_banner = QFrame()
        self.pending_banner.setObjectName("pendingBanner")
        banner = QHBoxLayout(self.pending_banner)
        banner.addWidget(QLabel("Изменения применятся после переподключения"), 1)
        self.reconnect_button = QPushButton("Переподключить")
        self.reconnect_button.clicked.connect(
            lambda: self._app.activate_action(
                "connect-profile", self._context.proxy_state.started_profile_id
            )
        )
        banner.addWidget(self.reconnect_button)
        self.pending_banner.hide()
        layout.addWidget(self.pending_banner)

        self.library_container = QFrame()
        self.library_container.setObjectName("profileContainer")
        self.library_container.setMaximumWidth(CONTENT_MAX_WIDTH)
        self.library_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        library = QVBoxLayout(self.library_container)
        library.setContentsMargins(16, 12, 16, 12)
        library.setSpacing(10)
        library_row = QHBoxLayout()
        library_row.setContentsMargins(12, 0, 12, 0)
        library_row.addStretch(1)
        library_row.addWidget(self.library_container, 1000)
        library_row.addStretch(1)
        layout.addLayout(library_row, 1)

        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск сервера… (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Поиск профилей")
        self.search.textChanged.connect(lambda _text: self.refresh_pages())
        tools.addWidget(self.search, 1)
        self.add_button = QToolButton()
        self.add_button.setText("Добавить…")
        self.add_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.add_menu = QMenu(self.add_button)
        for name, label in ADD_MENU:
            self.add_menu.addAction(label).triggered.connect(self._app.actions[name].trigger)
        self.add_button.setMenu(self.add_menu)
        tools.addWidget(self.add_button)
        library.addLayout(tools)

        self.model = ProfileTreeModel()
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.selectionModel().currentChanged.connect(self._selection_changed)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setUniformRowHeights(False)
        self.tree.setItemDelegate(ProfileDelegate(self.tree))
        self.tree.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setIndentation(20)
        self.tree.header().setSectionsClickable(True)
        self.tree.header().setSortIndicatorShown(True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(NAME_COLUMN, self.tree.header().ResizeMode.Stretch)
        self.tree.header().setMinimumSectionSize(80)
        for column, width in ((TYPE_COLUMN, 135), (ADDRESS_COLUMN, 260), (PING_COLUMN, 100)):
            self.tree.header().resizeSection(column, width)
        self.tree.header().sectionClicked.connect(self._on_header_clicked)
        self.tree.activated.connect(self._on_activated)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.collapsed.connect(lambda index: self._remember_collapsed(index, True))
        self.tree.expanded.connect(lambda index: self._remember_collapsed(index, False))
        self.empty_label = QLabel("Нет профилей. Добавьте профиль или подписку.")
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.list_box = QWidget()
        list_layout = QVBoxLayout(self.list_box)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.addWidget(self.tree, 1)
        list_layout.addWidget(self.empty_label, 1)
        library.addWidget(self.list_box, 1)

        self.toast_widget = Toast()
        library.addWidget(self.toast_widget)

        bottom = QHBoxLayout()
        self.selection_label = QLabel()
        self.selection_label.setTextFormat(Qt.TextFormat.PlainText)
        self.selection_label.setWordWrap(True)
        bottom.addWidget(self.selection_label, 1)
        self.switch_button = QPushButton("Переключить на выбранный")
        self.switch_button.clicked.connect(self._switch_selected)
        bottom.addWidget(self.switch_button)
        library.addLayout(bottom)

        self.setCentralWidget(central)
        self._build_monitoring()
        footer = QHBoxLayout()
        self.footer_status = QLabel()
        self.footer_status.setTextFormat(Qt.TextFormat.PlainText)
        self.footer_status.setWordWrap(True)
        footer.addWidget(self.footer_status, 1)
        footer.addWidget(self.monitoring_button)
        layout.addLayout(footer)

    def _build_monitoring(self) -> None:
        self.monitoring_window = QDialog(self, Qt.WindowType.Window)
        self.monitoring_window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.monitoring_window.setWindowTitle("Диагностика — Veblock")
        self.monitoring_window.resize(720, 270)
        self.monitoring_window.installEventFilter(self)
        self.monitoring_window_layout = QVBoxLayout(self.monitoring_window)
        body = QWidget()
        body.setObjectName("monitoringPanel")
        column = QHBoxLayout(body)
        self.monitoring_form = QFormLayout()
        column.addLayout(self.monitoring_form)
        self.routing_form = QFormLayout()
        column.addLayout(self.routing_form)
        commands = QVBoxLayout()
        self.last_check = QLabel()
        commands.addWidget(self.last_check)
        self.check_button = QPushButton("Проверить сейчас")
        self.check_button.clicked.connect(self._on_check_now)
        commands.addWidget(self.check_button)
        self.diagnostics = DiagnosticsPanel(
            dispatch=self._app.loop.dispatch, show_dialog=self._app.show_dialog
        )
        self.diagnostics_window = QDialog(self, Qt.WindowType.Window)
        self.diagnostics_window.setWindowTitle("Журнал — Veblock")
        self.diagnostics_window.resize(960, 600)
        journal_layout = QVBoxLayout(self.diagnostics_window)
        journal_layout.addWidget(self.diagnostics)
        self.log_button = QPushButton("Открыть журнал…")
        self.log_button.clicked.connect(self.show_diagnostics)
        commands.addWidget(self.log_button)
        commands.addStretch(1)
        column.addLayout(commands)
        self.monitoring_body = body
        self.content_layout.addWidget(body)
        body.hide()
        self.monitoring_button.toggled.connect(self._on_monitoring_toggled)

    def show_diagnostics(self) -> None:
        self.diagnostics_window.show()
        self.diagnostics_window.raise_()
        self.diagnostics_window.activateWindow()

    # --- состояние ---

    def refresh_status(self) -> None:
        from src.ui.logic.settings_state import pending_settings

        self.pending_banner.setVisible(pending_settings(self._context))
        state = self._context.proxy_state
        store = self._context.profiles
        selected = store.get_profile(self.selected_profile_id())
        target = selected or store.last_used_profile()
        profile = store.get_profile(state.started_profile_id) if state.is_running else target
        busy = self._app.controller.connection_busy()
        mode = state.started_mode if state.is_running else self._context.config.proxy_mode
        mode_text = "Системный прокси" if mode == "system" else "TUN"
        view = self.presentation.resolve(
            running=state.is_running,
            active_id=state.started_profile_id,
            busy=busy,
            profile_name=profile.name if profile else "",
            mode="",
            upload=state.upload_bytes,
            download=state.download_bytes,
            latency=getattr(profile, "latency_ms", None) if profile and state.is_running else None,
        )
        if self.presentation.error and not state.is_running:
            view = replace(view, subtitle=profile.name if profile else "")
        if not store.profiles and not state.is_running:
            view = replace(view, title="Добавьте сервер или подписку")
        self.status_card.update_view(
            view, enabled=not busy and (state.is_running or target is not None), mode=mode_text
        )
        selected_name = flagged(selected.name)[1] if selected else "Сервер не выбран"
        self.selection_label.setText(f"Выбран: {selected_name}" if selected else selected_name)
        self.selection_label.setToolTip(
            f"{selected.proxy_type.upper()} · {selected.bean.server_address}:{selected.bean.server_port}"
            if selected
            else ""
        )
        self.switch_button.setVisible(
            bool(selected and state.is_running and selected.id != state.started_profile_id)
        )
        self.switch_button.setEnabled(not busy)
        self.switch_button.setToolTip(f"Подключить: {selected_name}")
        self.refresh_monitoring()

    def begin_operation(self, name: str, profile_id: int | None = None) -> None:
        if self._app.controller.connection_busy():
            return
        state = self._context.proxy_state
        disconnect = name == "disconnect" or (name == "toggle-connection" and state.is_running)
        profile = self._context.profiles.get_profile(profile_id) if profile_id is not None else None
        self.presentation.begin(
            "disconnect" if disconnect else "connect", profile.name if profile else ""
        )

    def show_connecting(self, profile_name: str = "") -> None:
        self.presentation.begin("connect", profile_name)
        view = status_view(ConnectionState.CONNECTING, profile_name=profile_name)
        view = replace(view, button_label="Подключение…")
        self.status_card.update_view(view, enabled=False)

    def show_error(self, message: str) -> None:
        state = self._context.proxy_state
        self.presentation.fail(
            message, (state.is_running, state.started_profile_id if state.is_running else None)
        )
        self.refresh_status()

    def _selection_changed(self, *_args) -> None:
        if not self._rebuilding:
            self.refresh_status()

    def _switch_selected(self) -> None:
        selected = self.selected_profile_id()
        if selected is not None:
            self._app.activate_action("connect-profile", selected)

    def refresh_pages(self) -> None:
        """Пересобрать дерево, сохранив выделение и свёрнутые группы."""
        selected = self.selected_profile_id()
        selected_target = self.model.target(self.tree.currentIndex())
        top_index = self.tree.indexAt(QPoint(30, 1))
        top_target = self.model.target(top_index)
        top_offset = self.tree.visualRect(top_index).top()
        scroll = self.tree.verticalScrollBar().value()
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
        self._rendered_active = (state.is_running, state.started_profile_id)
        if self._ping_progress is not None:
            for position, row in enumerate(rows):
                group_index = self.model.group_index(row.group_id)
                group = self.model.itemFromIndex(group_index)
                if group is not None:
                    order = {
                        self.model.target(group.child(i, 0).index())[1]: i
                        for i in range(group.rowCount())
                    }
                    rows[position] = replace(
                        row,
                        children=tuple(
                            sorted(row.children, key=lambda p: order.get(p.profile_id, len(order)))
                        ),
                    )
        details = {
            row.group_id: (row.details_text, row.expired)
            for row in build_subscription_rows(groups, {})
        }
        self._rebuilding = True
        self.model.set_rows(rows, self._ping_progress, details)
        for position in range(self.model.rowCount()):
            index = self.model.index(position, NAME_COLUMN)
            self.tree.setFirstColumnSpanned(position, QModelIndex(), True)
            group_id = self.model.target(index)[1]
            # Поиск раскрывает всё: совпадение в свёрнутой группе не видно.
            self.tree.setExpanded(
                index, bool(self.search.text()) or group_id not in self._collapsed
            )
        if selected is not None:
            index = self.model.profile_index(selected)
            if index.isValid():
                self.tree.setCurrentIndex(index)
        elif selected_target and selected_target[0] == GROUP:
            self.tree.setCurrentIndex(self.model.group_index(selected_target[1]))
        self.tree.doItemsLayout()
        if top_target:
            anchor = (
                self.model.profile_index(top_target[1])
                if top_target[0] == PROFILE
                else self.model.group_index(top_target[1])
            )
            if anchor.isValid():
                self.tree.scrollTo(anchor, QAbstractItemView.ScrollHint.PositionAtTop)
                scroll = self.tree.verticalScrollBar().value() - top_offset
        self.tree.verticalScrollBar().setValue(scroll)
        self._rebuilding = False
        has_profiles = any(row.children for row in rows)
        self.tree.setVisible(has_profiles or bool(rows))
        self.empty_label.setVisible(not has_profiles)
        self.empty_label.setText(
            "Ничего не найдено. Измените запрос."
            if self.search.text()
            else "Нет профилей. Добавьте профиль или подписку."
        )
        self.refresh_status()

    def refresh_monitoring(self) -> None:
        monitor = self._context.monitor
        status = monitor.status if monitor is not None else _EmptyStatus()
        state = self._context.proxy_state
        session = (state.is_running, state.started_profile_id)
        if getattr(self, "_monitor_session", None) != session:
            self._monitor_session = session
            self._monitor_baseline = status.last_check_time
        checked = bool(status.last_check_time and status.last_check_time > self._monitor_baseline)
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
        for position, row in enumerate((*view.connection, *view.routing)):
            key = str(position)
            value = self._monitoring_values.get(key)
            if value is None:
                value = QLabel()
                value.setWordWrap(True)
                value.setTextFormat(Qt.TextFormat.PlainText)
                (
                    self.monitoring_form if position < len(view.connection) else self.routing_form
                ).addRow(row.title, value)
                self._monitoring_values[key] = value
            value.setText(
                "Проверка ещё не выполнена"
                if position == 0 and state.is_running and not checked
                else row.value
            )
            value.setProperty("state", row.css_class)
        self.last_check.setText(
            f"Последняя проверка: {view.last_check}"
            if checked or not state.is_running
            else "Ожидается проверка соединения"
        )
        if self.presentation.error:
            summary = self.presentation.error
        elif state.is_running and not checked:
            summary = "Проверка соединения ещё не выполнена"
        elif state.is_running and not status.proxy_ok:
            summary = "Прокси запущен, соединение не прошло проверку"
        elif state.is_running:
            summary = f"Последняя проверка соединения: {view.last_check}"
        else:
            summary = ""
        self.status_card.health.setText(summary)
        self.status_card.health.setVisible(bool(summary))
        if hasattr(self, "footer_status"):
            self.footer_status.setText(
                "Подробности подключения и журнал"
                if not self.presentation.error
                else "Ошибка — откройте диагностику"
            )

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
        self.tree.doItemsLayout()

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
        if (
            target is not None
            and target[0] == PROFILE
            and not self._app.controller.connection_busy()
        ):
            self.begin_operation("connect-profile", target[1])
            self._app.controller.select_profile(target[1])
            self.refresh_status()

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

    def _on_monitoring_toggled(self, visible: bool) -> None:
        self._context.config.monitoring_panel = visible
        self.status_card.set_compact(self.height() < 720)
        self._place_monitoring()

    def _place_monitoring(self) -> None:
        if not hasattr(self, "monitoring_body") or getattr(self, "_placing_monitoring", False):
            return
        self._placing_monitoring = True
        try:
            visible = self.monitoring_button.isChecked() and self.isVisible()
            separate = self.height() < 760 or self.width() < 1050
            if visible and not separate:
                self.status_card.set_compact(True)
            if separate:
                if self.monitoring_body.parent() is not self.monitoring_window:
                    self.content_layout.removeWidget(self.monitoring_body)
                    self.monitoring_window_layout.addWidget(self.monitoring_body)
                self.monitoring_body.setVisible(visible)
                self.monitoring_window.setVisible(visible)
            else:
                self.monitoring_window.hide()
                if self.monitoring_body.parent() is not self.centralWidget():
                    self.monitoring_window_layout.removeWidget(self.monitoring_body)
                    self.content_layout.insertWidget(
                        self.content_layout.count() - 1, self.monitoring_body
                    )
                self.monitoring_body.setVisible(visible)
        finally:
            self._placing_monitoring = False

    def eventFilter(self, watched, event) -> bool:
        if (
            watched is getattr(self, "monitoring_window", None)
            and event.type() == QEvent.Type.Close
        ):
            self.monitoring_button.setChecked(False)
        return super().eventFilter(watched, event)

    def _schedule_palette_refresh(self, *_args) -> None:
        if not getattr(self, "_palette_refresh_pending", False):
            self._palette_refresh_pending = True
            QTimer.singleShot(0, self, self._refresh_palette)

    def _refresh_palette(self) -> None:
        # QSS palette(...) кэширует цвета: после смены схемы нужен новый polish.
        self.setStyleSheet("")
        palette = self._app.qt.palette()
        for widget in (self, *self.findChildren(QWidget)):
            widget.setPalette(palette)
        self.setStyleSheet(STYLE_SHEET.read_text(encoding="utf-8"))
        self._palette_refresh_pending = False

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "status_card"):
            compact = self.status_card.compact
            self.status_card.set_compact(self.height() < (780 if compact else 720))
            self._place_monitoring()

    def hideEvent(self, event) -> None:
        if hasattr(self, "diagnostics_window"):
            self.diagnostics_window.hide()
            self.monitoring_window.hide()
        super().hideEvent(event)

    def toggle_group(self, group_id: int) -> None:
        index = self.model.group_index(group_id)
        if index.isValid():
            self.tree.setExpanded(index, not self.tree.isExpanded(index))

    def context_menu(self, index) -> QMenu:
        """Меню строки; пункты зовут действия приложения с id строки."""
        menu = QMenu(self)
        target = self.model.target(index)
        if target is None:
            return menu
        kind, row_id = target
        entries = PROFILE_MENU if kind == PROFILE else GROUP_MENU
        group = self._context.profiles.get_group(row_id) if kind == GROUP else None
        for entry in entries:
            if entry is None:
                menu.addSeparator()
                continue
            name, label = entry
            if name == "toggle-group":
                expanded = self.tree.isExpanded(self.model.index(index.row(), NAME_COLUMN))
                label = "Свернуть группу" if expanded else "Развернуть группу"
            if name == "update-subscription" and not getattr(group, "is_subscription", False):
                continue
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, n=name: self._app.activate_action(n, row_id)
            )
        return menu

    def _on_context_menu(self, point) -> None:
        index = self.tree.indexAt(point)
        if not index.isValid():
            return
        self.tree.setCurrentIndex(index)
        self.context_menu(index).exec(self.tree.viewport().mapToGlobal(point))

    def _on_proxy_state_changed(self, _state) -> None:
        # Состояние меняет поток подключения; виджеты — только из главного.
        self._app.loop.dispatch(self._refresh_after_state_change)

    def _refresh_after_state_change(self) -> None:
        state = self._context.proxy_state
        changed = getattr(self, "_rendered_active", None) != (
            state.is_running,
            state.started_profile_id,
        )
        self.refresh_status()
        if changed:
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
        self._place_monitoring()

    def closeEvent(self, event) -> None:
        """С треем окно прячется, без него закрытие завершает приложение."""
        self.save_geometry()
        self.diagnostics_window.hide()
        self.monitoring_window.hide()
        if self._app.tray is not None and self._context.config.close_to_tray:
            event.ignore()
            self.hide()
            self.diagnostics.set_active(False)
            return
        event.accept()
        self._app.quit()

    def detach(self) -> None:
        """Перестать слушать состояние прокси, как `MainWindow.detach()` в GTK."""
        if getattr(self, "_detached", False):
            return
        self._detached = True
        self._context.proxy_state.remove_listener(self._on_proxy_state_changed)
        self._app.qt.paletteChanged.disconnect(self._schedule_palette_refresh)
        self.monitoring_window.hide()
        self.diagnostics_window.hide()
        self.diagnostics.set_active(False)

    def save_geometry(self) -> None:
        size = self.normalGeometry().size() if self.isMaximized() else self.size()
        geometry = Geometry(width=size.width(), height=size.height(), maximized=self.isMaximized())
        self._context.config.window_size = format_geometry(geometry)
        try:
            self._context.save_config()
        except Exception as e:
            logger.warning("Could not persist window geometry: %s", e)
