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
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from src.ui.logic.geometry import (
    DEFAULT_GEOMETRY,
    MIN_HEIGHT,
    MIN_WIDTH,
    Geometry,
    format_geometry,
    parse_geometry,
)
from src.ui.logic.menus import ADD_MENU, CONNECT_BEST_GROUP_LABEL, MAIN_MENU
from src.ui.logic.monitoring_view import (
    NOT_CHECKED,
    format_last_check,
    last_check_text,
    monitoring_view,
)
from src.ui.logic.platform_texts import profile_routing_title
from src.ui.logic.profiles_view import (
    EMPTY_DESCRIPTION,
    EMPTY_TITLE,
    NO_RESULTS_TEXT,
    SEARCH_PLACEHOLDER,
    SELECTED_NONE,
    SortKey,
    build_profile_rows,
    selected_text,
)
from src.ui.logic.status import (
    BLOCKED_BANNER,
    RELEASE_BLOCK_LABEL,
    SWITCH_LABEL,
    ConnectionPresentation,
    ConnectionState,
    connecting_view,
    health_text,
    is_traffic_blocked,
    mode_text,
    status_view,
    switch_hint,
)
from src.ui.logic.subscriptions_view import build_subscription_rows
from src.ui.qt.icons import flagged
from src.ui.qt.models import (
    ADDRESS_COLUMN,
    GROUP,
    ID_ROLE,
    NAME_COLUMN,
    PING_COLUMN,
    PROFILE,
    SORT_KEYS,
    TYPE_COLUMN,
    ProfileTreeModel,
)
from src.ui.qt.widgets.diagnostics import DiagnosticsPanel
from src.ui.qt.widgets.profile_delegate import ProfileDelegate
from src.ui.qt.widgets.status_card import ElidedLabel, StatusCard
from src.ui.qt.widgets.toast import Toast

if TYPE_CHECKING:
    from src.core.context import AppContext
    from src.ui.logic.latency import PingProgress
    from src.ui.qt.application import QtApplication

logger = logging.getLogger("tenga.ui.qt.window")

# Меню строк дерева: (действие, подпись); None — разделитель. Как в GTK
# (src/ui/pages/profiles.py), у подписки ещё «Обновить подписку»: списка
# подписок на главном экране Qt нет.
PROFILE_MENU = (
    ("connect-profile", "Подключить"),
    ("profile-routing", profile_routing_title() + "…"),
    ("test-profile", "Тест задержки"),
    None,
    ("edit-profile", "Редактировать"),
    ("delete-profile", "Удалить"),
)
GROUP_MENU = (
    ("toggle-group", ""),  # подпись зависит от того, раскрыта ли группа
    ("update-subscription", "Обновить подписку"),
    ("test-group", "Тест задержки"),
    ("connect-best", CONNECT_BEST_GROUP_LABEL),
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

        self.setWindowTitle("Monoliten")
        available = self.screen().availableGeometry()
        self.setMinimumSize(
            min(MIN_WIDTH, available.width()), min(MIN_HEIGHT, available.height() - 40)
        )
        geometry = parse_geometry(
            getattr(context.config, "window_size", ""), default=DEFAULT_GEOMETRY
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
        toolbar = QHBoxLayout()
        brand = QLabel("Серверы")
        self.page_title = brand
        brand.setObjectName("brandLabel")
        toolbar.addWidget(brand)
        toolbar.addStretch(1)
        self.settings_button = QPushButton("Настройки")
        self.settings_button.clicked.connect(lambda: self._app.activate_action("settings"))
        toolbar.addWidget(self.settings_button)

        self.status_card = StatusCard()
        self.status_card.action_clicked.connect(
            lambda: self._app.activate_action("toggle-connection")
        )
        self.monitoring_button = QToolButton()
        self.monitoring_button.setObjectName("monitoringToggle")
        self.monitoring_button.setText("Диагностика")
        self.monitoring_button.setCheckable(True)
        self.monitoring_button.setChecked(False)
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
        toolbar.addWidget(self.menu_button)
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

        self.blocked_banner = QFrame()
        self.blocked_banner.setObjectName("pendingBanner")
        blocked = QHBoxLayout(self.blocked_banner)
        blocked.addWidget(QLabel(BLOCKED_BANNER), 1)
        self.release_block_button = QPushButton(RELEASE_BLOCK_LABEL)
        self.release_block_button.clicked.connect(
            lambda: self._app.activate_action("release-block")
        )
        blocked.addWidget(self.release_block_button)
        self.blocked_banner.hide()

        self.library_container = QFrame()
        self.library_container.setObjectName("profileContainer")
        self.library_container.setMaximumWidth(CONTENT_MAX_WIDTH)
        self.library_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        library = QVBoxLayout(self.library_container)
        library.setContentsMargins(16, 12, 16, 12)
        library.setSpacing(10)
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(SEARCH_PLACEHOLDER)
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Поиск серверов")
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
        delegate = ProfileDelegate(self.tree)
        self.tree.setItemDelegate(delegate)
        delegate.menu_requested.connect(self._row_menu)
        delegate.ping_requested.connect(
            lambda index: self._app.activate_action("test-profile", index.data(ID_ROLE))
        )
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
        self.empty_label = QLabel(f"{EMPTY_TITLE}\n{EMPTY_DESCRIPTION}")
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
        self.selection_label = ElidedLabel()
        self.selection_label.setMinimumWidth(0)
        self.selection_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.selection_label.setTextFormat(Qt.TextFormat.PlainText)
        self.selection_label.setWordWrap(False)
        bottom.addWidget(self.selection_label, 1)
        self.switch_button = QPushButton(SWITCH_LABEL)
        self.switch_button.clicked.connect(self._switch_selected)
        bottom.addWidget(self.switch_button)
        self.selection_layout = bottom
        library.addLayout(bottom)

        self.setCentralWidget(central)
        self._build_monitoring()
        self.footer_container = QWidget()
        self.footer_container.setMaximumWidth(CONTENT_MAX_WIDTH)
        footer = QHBoxLayout(self.footer_container)
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addWidget(self.monitoring_button)
        footer.addStretch(1)
        self.latency_button = QPushButton("Проверить задержку")
        self.latency_button.clicked.connect(lambda: self._app.activate_action("test-latency"))
        footer.addWidget(self.latency_button)
        self.servers_page = QWidget()
        servers = QVBoxLayout(self.servers_page)
        servers.setContentsMargins(0, 0, 0, 0)
        servers.addWidget(self.library_container, 1)
        servers.addWidget(self.footer_container)
        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self.servers_page)
        self.right_stack.addWidget(self.monitoring_body)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 8, 8, 8)
        right_layout.addLayout(toolbar)
        right_layout.addWidget(self.pending_banner)
        right_layout.addWidget(self.blocked_banner)
        right_layout.addWidget(self.right_stack, 1)
        self.back_button = QPushButton("← Серверы")
        self.back_button.clicked.connect(lambda: self.monitoring_button.setChecked(False))
        toolbar.insertWidget(0, self.back_button)
        self.back_button.hide()
        columns = QHBoxLayout()
        columns.setSpacing(8)
        self.status_card.setMinimumWidth(280)
        self.status_card.setMaximumWidth(360)
        columns.addWidget(self.status_card, 1)
        columns.addWidget(right, 2)
        layout.addLayout(columns, 1)
        self.sort_button = QToolButton()
        self.sort_button.setText("Сортировка")
        self.sort_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        sort_menu = QMenu(self.sort_button)
        for key, title in (
            (SortKey.NAME, "По имени"),
            (SortKey.TYPE, "По типу"),
            (SortKey.PING, "По задержке"),
        ):
            sort_menu.addAction(title).triggered.connect(
                lambda _checked=False, k=key: self.set_sort(
                    k, ascending=(not self._ascending if k == self._sort_key else True)
                )
            )
        self.sort_button.setMenu(sort_menu)
        tools.addWidget(self.sort_button)
        self.tree.setHeaderHidden(True)
        for column in (TYPE_COLUMN, ADDRESS_COLUMN, PING_COLUMN):
            self.tree.hideColumn(column)

    def _build_monitoring(self) -> None:
        body = QFrame()
        body.setObjectName("monitoringPanel")
        body.setMaximumWidth(CONTENT_MAX_WIDTH)
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        panel = QVBoxLayout(body)
        panel.setContentsMargins(16, 12, 16, 12)
        panel.setSpacing(12)
        column = QHBoxLayout()
        column.setSpacing(16)
        connection_group = QGroupBox("Состояние соединения")
        self.monitoring_form = QFormLayout(connection_group)
        self.monitoring_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        column.addWidget(connection_group, 1)
        routing_group = QGroupBox("Маршрутизация")
        self.routing_form = QFormLayout(routing_group)
        self.routing_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        column.addWidget(routing_group, 1)
        panel.addLayout(column)
        commands = QHBoxLayout()
        self.last_check = QLabel()
        self.last_check.setWordWrap(True)
        panel.addWidget(self.last_check)
        self.check_button = QPushButton("Проверить сейчас")
        self.check_button.clicked.connect(self._on_check_now)
        commands.addWidget(self.check_button)
        self.network_check_button = QPushButton("Диагностика сети…")
        self.network_check_button.clicked.connect(
            lambda: self._app.activate_action("network-diagnostics")
        )
        commands.addWidget(self.network_check_button)
        self.diagnostics = DiagnosticsPanel(
            dispatch=self._app.loop.dispatch, show_dialog=self._app.show_dialog
        )
        panel.addLayout(commands)
        panel.addWidget(self.diagnostics, 1)
        self.monitoring_body = body
        self.monitoring_button.toggled.connect(self._on_monitoring_toggled)

    def show_diagnostics(self) -> None:
        self.monitoring_button.setChecked(True)
        self.diagnostics.view.setFocus()

    # --- состояние ---

    def refresh_status(self) -> None:
        from src.ui.logic.settings_state import pending_settings

        self.pending_banner.setVisible(pending_settings(self._context))
        state = self._context.proxy_state
        blocked = is_traffic_blocked(state)
        self.blocked_banner.setVisible(blocked)
        store = self._context.profiles
        selected = store.get_profile(self.selected_profile_id())
        # При блокировке — тот же сервер, что подключит логотип.
        target = store.get_profile(state.blocked_profile_id) if blocked else None
        target = target or selected or store.last_used_profile()
        profile = store.get_profile(state.started_profile_id) if state.is_running else target
        busy = self._app.controller.connection_busy()
        mode = state.started_mode if state.is_running else self._context.config.proxy_mode
        view = self.presentation.resolve(
            running=state.is_running,
            active_id=state.started_profile_id,
            busy=busy,
            profile_name=profile.name if profile else "",
            mode=mode_text(mode),
            upload=state.upload_bytes,
            download=state.download_bytes,
            latency=getattr(profile, "latency_ms", None) if profile and state.is_running else None,
            has_profiles=bool(store.profiles),
            can_connect=target is not None,
            blocked=blocked,
        )
        self.status_card.update_view(view)
        selected_name = flagged(selected.name)[1] if selected else SELECTED_NONE
        self.selection_label.setText(selected_text(selected.name if selected else ""))
        self.selection_label.setToolTip(
            f"{selected.proxy_type.upper()} · {selected.bean.server_address}:{selected.bean.server_port}"
            if selected
            else ""
        )
        self.switch_button.setVisible(
            bool(selected and state.is_running and selected.id != state.started_profile_id)
        )
        self.switch_button.setEnabled(not busy)
        self.switch_button.setToolTip(switch_hint(selected_name))
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

    def show_connecting(self, profile_name: str = "", note: str = "") -> None:
        self.presentation.begin("connect", profile_name, note)
        self.status_card.update_view(connecting_view(profile_name, note))

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
            NO_RESULTS_TEXT if self.search.text() else f"{EMPTY_TITLE}\n{EMPTY_DESCRIPTION}"
        )
        self.refresh_status()

    def refresh_monitoring(self) -> None:
        monitor = self._context.monitor
        status = monitor.status if monitor is not None else _EmptyStatus()
        state = self._context.proxy_state
        checked = self.presentation.check_done(
            running=state.is_running,
            active_id=state.started_profile_id,
            last_check_time=status.last_check_time,
        )
        profile = (
            self._context.profiles.get_profile(state.started_profile_id)
            if state.is_running
            else None
        )
        routing = getattr(profile, "routing_settings", None) or self._context.config.routing
        own_rules = getattr(profile, "routing_settings", None) is not None
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
            own_rules=own_rules,
            vpn_enabled=vpn_enabled,
            vpn_is_up=vpn_enabled and status.vpn_ok,
            checked=checked,
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
            value.setText(row.value)
            value.setProperty("state", row.css_class)
        self.last_check.setText(view.last_check_line)
        summary = health_text(
            running=state.is_running,
            checked=checked,
            proxy_ok=status.proxy_ok,
            last_check=format_last_check(status.last_check_time),
            error=self.presentation.error,
        )
        self.status_card.health.setText(summary)
        self.status_card.health.setVisible(bool(summary))

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
        self.monitoring_button.setChecked(False)
        self.search.setFocus()
        self.search.selectAll()

    # --- события ---

    def _on_header_clicked(self, column: int) -> None:
        sort_key = SORT_KEYS.get(column)
        if sort_key is None:
            # По адресу не сортируют: вернуть индикатор на текущую колонку.
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
        self.right_stack.setCurrentIndex(1 if visible else 0)
        self.back_button.setVisible(visible)
        self.page_title.setText("Диагностика" if visible else "Серверы")
        self._place_monitoring()
        if not visible:
            self.tree.setFocus()

    def _place_monitoring(self) -> None:
        if hasattr(self, "right_stack"):
            self.diagnostics.set_active(self.monitoring_button.isChecked() and self.isVisible())

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
            if hasattr(self, "selection_layout"):
                self.selection_layout.setDirection(
                    QHBoxLayout.Direction.TopToBottom
                    if self.width() < 1050
                    else QHBoxLayout.Direction.LeftToRight
                )
            compact = self.status_card.compact
            self.status_card.set_compact(self.height() < (750 if compact else 680))
            self._place_monitoring()

    def hideEvent(self, event) -> None:
        if hasattr(self, "diagnostics"):
            self.diagnostics.set_active(False)
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

    def _row_menu(self, index, point) -> None:
        self.tree.setCurrentIndex(index)
        self.context_menu(index).exec(self.tree.viewport().mapToGlobal(point))

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
        self.diagnostics.set_active(False)
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
        self.diagnostics.set_active(False)

    def save_geometry(self) -> None:
        size = self.normalGeometry().size() if self.isMaximized() else self.size()
        geometry = Geometry(width=size.width(), height=size.height(), maximized=self.isMaximized())
        self._context.config.window_size = format_geometry(geometry)
        try:
            self._context.save_config()
        except Exception as e:
            logger.warning("Could not persist window geometry: %s", e)
