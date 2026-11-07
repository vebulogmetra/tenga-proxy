"""Самообновление приложения: можно ли и как запустить скачанный установщик."""

from src.core.platform_info import IS_WINDOWS

if IS_WINDOWS:
    from src.sys.windows.app_install import can_self_update, launch_installer
else:
    from src.sys.linux.app_install import can_self_update, launch_installer

__all__ = ["can_self_update", "launch_installer"]
