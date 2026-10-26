"""Окно сообщений Win32 с иконкой в области уведомлений.

Свой поток: RegisterClassExW → CreateWindowExW (невидимое окно верхнего уровня:
message-only окно не получает широковещательное `TaskbarCreated`) → цикл
GetMessageW. Изменения из главного потока складываются под замком и
применяются по `WM_APP_UPDATE`. После перезапуска Проводника иконка
добавляется заново по сообщению `TaskbarCreated`.
"""

from __future__ import annotations

import ctypes
import logging
import re
import threading
from ctypes import wintypes

logger = logging.getLogger("tenga.ui.tray.win32")

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_NULL = 0x0000
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_APP = 0x8000
WM_APP_TRAY = WM_APP + 1
WM_APP_UPDATE = WM_APP + 2

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x10
SM_CXSMICON, SM_CYSMICON = 49, 50
MF_STRING, MF_GRAYED, MF_CHECKED, MF_POPUP, MF_SEPARATOR = 0x0, 0x1, 0x8, 0x10, 0x800
TPM_RIGHTBUTTON, TPM_NONOTIFY, TPM_RETURNCMD = 0x2, 0x80, 0x100


class MENUITEMINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("fMask", wintypes.UINT),
        ("fType", wintypes.UINT),
        ("fState", wintypes.UINT),
        ("wID", wintypes.UINT),
        ("hSubMenu", wintypes.HMENU),
        ("hbmpChecked", wintypes.HBITMAP),
        ("hbmpUnchecked", wintypes.HBITMAP),
        ("dwItemData", ctypes.c_size_t),
        ("dwTypeData", wintypes.LPWSTR),
        ("cch", wintypes.UINT),
        ("hbmpItem", wintypes.HBITMAP),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


def _api():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # Список, а не словарь: функции ctypes не хешируются.
    sig = [
        (user32.RegisterClassExW, [ctypes.POINTER(WNDCLASSEXW)], wintypes.ATOM),
        (
            user32.CreateWindowExW,
            [
                wintypes.DWORD,
                wintypes.LPCWSTR,
                wintypes.LPCWSTR,
                wintypes.DWORD,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.HWND,
                wintypes.HMENU,
                wintypes.HINSTANCE,
                wintypes.LPVOID,
            ],
            wintypes.HWND,
        ),
        (
            user32.DefWindowProcW,
            [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM],
            LRESULT,
        ),
        (user32.DestroyWindow, [wintypes.HWND], wintypes.BOOL),
        (
            user32.PostMessageW,
            [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM],
            wintypes.BOOL,
        ),
        (
            user32.GetMessageW,
            [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT],
            wintypes.BOOL,
        ),
        (user32.TranslateMessage, [ctypes.POINTER(wintypes.MSG)], wintypes.BOOL),
        (user32.DispatchMessageW, [ctypes.POINTER(wintypes.MSG)], LRESULT),
        (user32.PostQuitMessage, [ctypes.c_int], None),
        (user32.RegisterWindowMessageW, [wintypes.LPCWSTR], wintypes.UINT),
        (
            user32.LoadImageW,
            [
                wintypes.HINSTANCE,
                wintypes.LPCWSTR,
                wintypes.UINT,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ],
            wintypes.HANDLE,
        ),
        (user32.DestroyIcon, [wintypes.HICON], wintypes.BOOL),
        (user32.GetSystemMetrics, [ctypes.c_int], ctypes.c_int),
        (user32.CreatePopupMenu, [], wintypes.HMENU),
        (
            user32.AppendMenuW,
            [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR],
            wintypes.BOOL,
        ),
        (user32.DestroyMenu, [wintypes.HMENU], wintypes.BOOL),
        (
            user32.SetMenuItemInfoW,
            [wintypes.HMENU, wintypes.UINT, wintypes.BOOL, ctypes.POINTER(MENUITEMINFOW)],
            wintypes.BOOL,
        ),
        (
            user32.TrackPopupMenu,
            [
                wintypes.HMENU,
                wintypes.UINT,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.HWND,
                wintypes.LPVOID,
            ],
            wintypes.BOOL,
        ),
        (user32.GetCursorPos, [ctypes.POINTER(wintypes.POINT)], wintypes.BOOL),
        (user32.SetForegroundWindow, [wintypes.HWND], wintypes.BOOL),
        (
            shell32.Shell_NotifyIconW,
            [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)],
            wintypes.BOOL,
        ),
        (kernel32.GetModuleHandleW, [wintypes.LPCWSTR], wintypes.HMODULE),
    ]
    for fn, argtypes, restype in sig:
        fn.argtypes = argtypes
        fn.restype = restype
    return user32, shell32, kernel32


class NotifyIconWindow:
    def __init__(self):
        # Класс окна свой у каждого экземпляра: повторная регистрация того же
        # имени не удалась бы, и новое окно получило бы WNDPROC прежнего.
        self._class_name = f"TengaProxyTrayWindow-{id(self):x}"
        self._user32, self._shell32, self._kernel32 = _api()
        self._gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self._gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
        self._gdi32.DeleteObject.restype = wintypes.BOOL
        self._lock = threading.Lock()
        self._pending: tuple[str, str] = ("", "")
        self._hwnd = None
        self._hicon = None
        self._added = False
        self._on_event = None
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        # Ссылка держит callback живым: иначе сборщик мусора освободит его,
        # пока окно ещё получает сообщения.
        self._wndproc = WNDPROC(self._window_proc)
        self._taskbar_created = 0

    # --- вызовы из главного потока ---

    def start(self, on_event) -> None:
        self._on_event = on_event
        self._thread = threading.Thread(target=self._run, name="tenga-tray", daemon=True)
        self._thread.start()
        if not self._ready.wait(5):
            raise RuntimeError("Tray window did not start")
        if not self._hwnd:
            raise RuntimeError("Tray window could not be created")

    def update(self, icon_path: str, tooltip: str) -> None:
        with self._lock:
            self._pending = (icon_path, tooltip)
        if self._hwnd:
            self._user32.PostMessageW(self._hwnd, WM_APP_UPDATE, 0, 0)

    def stop(self) -> None:
        if self._hwnd:
            self._user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=2)

    # --- поток окна ---

    def show_menu(self, ops) -> int:
        """Показать меню и вернуть id выбранного пункта (0 — закрыто без выбора)."""
        bitmaps = []
        menu = None
        try:
            menu = self._build_menu(ops, bitmaps)
            point = wintypes.POINT()
            self._user32.GetCursorPos(ctypes.byref(point))
            # Без SetForegroundWindow меню не закрывается щелчком мимо него
            # (известная особенность Shell_NotifyIcon).
            self._user32.SetForegroundWindow(self._hwnd)
            chosen = self._user32.TrackPopupMenu(
                menu,
                TPM_RIGHTBUTTON | TPM_NONOTIFY | TPM_RETURNCMD,
                point.x,
                point.y,
                0,
                self._hwnd,
                None,
            )
            self._user32.PostMessageW(self._hwnd, WM_NULL, 0, 0)
            return int(chosen)
        finally:
            if menu:
                self._user32.DestroyMenu(menu)
            for bitmap in bitmaps:
                self._gdi32.DeleteObject(bitmap)

    def _build_menu(self, ops, bitmaps):
        from src.ui.tray.win32.menu_ops import Entry, Popup, Separator

        menu = self._user32.CreatePopupMenu()
        for position, op in enumerate(ops):
            label = op.label
            bitmap = None
            if not isinstance(op, Separator):
                label, bitmap = self._menu_flag(label)
                if bitmap:
                    bitmaps.append(bitmap)
            if isinstance(op, Separator):
                self._user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            elif isinstance(op, Popup):
                sub = self._build_menu(op.children, bitmaps)
                self._user32.AppendMenuW(menu, MF_POPUP, sub, label)
            elif isinstance(op, Entry):
                flags = MF_STRING
                if not op.enabled:
                    flags |= MF_GRAYED
                if op.checked:
                    flags |= MF_CHECKED
                self._user32.AppendMenuW(menu, flags, op.id, label)
            if bitmap:
                info = MENUITEMINFOW()
                info.cbSize = ctypes.sizeof(info)
                info.fMask = 0x80  # MIIM_BITMAP: сохраняет checkmark активного профиля.
                info.hbmpItem = bitmap
                self._user32.SetMenuItemInfoW(menu, position, True, ctypes.byref(info))
        return menu

    def _menu_flag(self, label):
        from src.core.config import get_asset_path
        from src.ui.logic.country_flags import split_flag_prefix

        match = re.search(r"[\U0001f1e6-\U0001f1ff]{2}\ufe0f?", label)
        if match is None:
            return label, None
        code, _ = split_flag_prefix(match[0])
        path = get_asset_path(f"flags/win/{code}.bmp")
        if not path.is_file():
            return label, None
        height = max(16, self._user32.GetSystemMetrics(72))  # SM_CYMENUCHECK
        bitmap = self._user32.LoadImageW(None, str(path), 0, height * 4 // 3, height, 0x2010)
        if not bitmap:
            return label, None
        return (label[: match.start()] + label[match.end() :]).strip(), bitmap

    def _run(self) -> None:
        try:
            hinstance = self._kernel32.GetModuleHandleW(None)
            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.lpfnWndProc = self._wndproc
            wc.hInstance = hinstance
            wc.lpszClassName = self._class_name
            self._user32.RegisterClassExW(ctypes.byref(wc))
            self._taskbar_created = self._user32.RegisterWindowMessageW("TaskbarCreated")
            self._hwnd = self._user32.CreateWindowExW(
                0, self._class_name, "Veblock", 0, 0, 0, 0, 0, None, None, hinstance, None
            )
        finally:
            self._ready.set()
        if not self._hwnd:
            logger.error("CreateWindowExW failed: %s", ctypes.get_last_error())
            return

        msg = wintypes.MSG()
        while self._user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            self._user32.TranslateMessage(ctypes.byref(msg))
            self._user32.DispatchMessageW(ctypes.byref(msg))

    def _notify_data(self, flags: int) -> NOTIFYICONDATAW:
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = self._hwnd
        data.uID = 1
        data.uFlags = flags
        data.uCallbackMessage = WM_APP_TRAY
        return data

    def _apply_pending(self) -> None:
        with self._lock:
            icon_path, tooltip = self._pending
        if icon_path:
            hicon = self._user32.LoadImageW(
                None,
                icon_path,
                IMAGE_ICON,
                self._user32.GetSystemMetrics(SM_CXSMICON),
                self._user32.GetSystemMetrics(SM_CYSMICON),
                LR_LOADFROMFILE,
            )
            if hicon:
                if self._hicon:
                    self._user32.DestroyIcon(self._hicon)
                self._hicon = hicon
        data = self._notify_data(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        data.hIcon = self._hicon
        data.szTip = tooltip
        self._added = (
            bool(
                self._shell32.Shell_NotifyIconW(
                    NIM_MODIFY if self._added else NIM_ADD, ctypes.byref(data)
                )
            )
            or self._added
        )

    def _window_proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_APP_UPDATE:
                self._apply_pending()
                return 0
            if msg == WM_APP_TRAY:
                if lparam == WM_LBUTTONUP:
                    self._on_event("primary")
                elif lparam == WM_RBUTTONUP:
                    self._on_event("menu")
                return 0
            if msg == self._taskbar_created and self._taskbar_created:
                self._added = False
                self._apply_pending()
                return 0
            if msg == WM_CLOSE:
                self._user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                if self._added:
                    self._shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._notify_data(0)))
                    self._added = False
                if self._hicon:
                    self._user32.DestroyIcon(self._hicon)
                    self._hicon = None
                self._hwnd = None
                self._user32.PostQuitMessage(0)
                return 0
        except Exception:
            # Исключение из WNDPROC ctypes проглотит молча; пишем в лог сами.
            logger.exception("Tray window procedure failed")
        return self._user32.DefWindowProcW(hwnd, msg, wparam, lparam)
