"""System tray over StatusNotifierItem (GTK4).

Имя `tray4`, а не `tray`: рядом ещё живёт GTK3-модуль `src/ui/tray.py`, и пакет
с тем же именем перекрыл бы его. На этапе 5, вместе с удалением GTK3-кода,
пакет переименовывается в `tray`.
"""
