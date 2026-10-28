"""Импорт общей маршрутизации ссылкой: что показать, что применить, как откатить.

GTK не импортирует: окно строит `src/ui/dialogs/routing_import.py`.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

from src.db.config import RoutingMode, RoutingSettings

# Из ссылки переносятся только эти списки; остальное — настройки устройства.
IMPORTED_LISTS = (
    ("proxy_list", "Через прокси"),
    ("direct_list", "Напрямую"),
    ("block_list", "Блокировать"),
)
REST_LABEL = "Остальное"
_DETAILS_LIMIT = 10


@dataclass(frozen=True)
class ImportRow:
    label: str
    value: str
    details: tuple[str, ...] = ()
    warning: bool = False


def effective_routing(routing: RoutingSettings, config_dir: Path | None) -> RoutingSettings:
    """Списки, с которыми подключилось бы ядро, — копией, без правки настроек.

    У старой установки списки живут в текстовых файлах и попадают в память
    только при подключении: без этого окно обещало бы «−0» перед удалением.
    """
    result = copy.deepcopy(routing)
    if config_dir is not None and not result.use_saved_lists:
        result.load_lists_from_files(config_dir)
    return result


def _rules(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        word = "правило"
    elif count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        word = "правила"
    else:
        word = "правил"
    return f"{count} {word}"


def _list_row(label: str, before: list[str], after: list[str]) -> ImportRow:
    old, new = set(before), set(after)
    changes = [f"+ {v}" for v in after if v not in old] + [f"− {v}" for v in before if v not in new]
    details = changes[:_DETAILS_LIMIT]
    if len(changes) > _DETAILS_LIMIT:
        details.append(f"и ещё {len(changes) - _DETAILS_LIMIT}")
    value = f"{_rules(len(after))}: +{len(new - old)}, −{len(old - new)}"
    return ImportRow(label, value, tuple(details))


def import_rows(
    before: RoutingSettings, after: RoutingSettings, *, name: str, direct_default: bool
) -> list[ImportRow]:
    """Строки окна подтверждения: «подпись — значение»."""
    rows = [ImportRow("Профиль", name)] if name else []
    if before.mode != after.mode:
        labels = RoutingMode.LABELS
        rows.append(ImportRow("Режим", f"{labels[before.mode]} → {labels[after.mode]}"))
    for key, label in IMPORTED_LISTS:
        rows.append(_list_row(label, getattr(before, key), getattr(after, key)))
    if direct_default:
        rest = ImportRow(
            REST_LABEL,
            "через прокси. Провайдер просил пускать остальное напрямую — "
            "Veblock намеренно это не поддерживает",
            warning=True,
        )
    else:
        rest = ImportRow(REST_LABEL, "через прокси")
    rows.append(rest)
    rows.append(ImportRow("Не переносится", "DNS, VPN, порядок правил и адреса геобаз"))
    return rows


def apply_import(config, new: RoutingSettings, config_dir: Path | None) -> None:
    """Заменить списки из ссылки, запомнив прежнюю маршрутизацию для отката.

    Копия хранит `use_saved_lists` как было: импорт не трогает текстовые
    файлы, и после отката старая установка снова читает их.
    """
    current = effective_routing(config.routing, config_dir)
    config.routing_backup = copy.deepcopy(current)
    # Списки, которых нет в ссылке (VPN), остаются из файлов: дальше они
    # читаются из settings.json.
    current.mode = new.mode
    current.use_saved_lists = True
    for key, _label in IMPORTED_LISTS:
        setattr(current, key, list(getattr(new, key)))
    config.routing = current


def restore_backup(config) -> bool:
    """Вернуть маршрутизацию до последнего импорта; False — возвращать нечего."""
    backup = config.routing_backup
    if backup is None:
        return False
    config.routing = backup
    config.routing_backup = None
    return True
