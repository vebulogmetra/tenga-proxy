from src.ui.logic.settings_form import validate_settings


def test_invalid_fragment_is_reported_without_mutating_config():
    from src.db.data_store import DataStore

    config = DataStore()
    config.tls_fragment.length = "0-100"
    assert "fragment_length" in validate_settings(config)
    assert config.tls_fragment.length == "0-100"


def test_default_settings_are_valid():
    from src.db.data_store import DataStore

    assert validate_settings(DataStore()) == {}


def test_save_status_texts():
    from src.ui.logic.settings_form import (
        SAVE_DONE,
        SAVE_FAILED,
        SAVE_IDLE,
        SAVE_PENDING,
        SAVE_RECONNECT,
        invalid_text,
        save_status_text,
    )

    assert SAVE_IDLE == "Изменения сохраняются автоматически"
    assert SAVE_PENDING == "Ожидание сохранения…"
    assert SAVE_FAILED == "Не удалось сохранить настройки. Повторите изменение."
    assert save_status_text(saved=True, reconnect=False) == SAVE_DONE == "Изменения сохранены"
    assert save_status_text(saved=True, reconnect=True) == f"{SAVE_DONE} · {SAVE_RECONNECT}"
    assert save_status_text(saved=False, reconnect=False) == SAVE_FAILED
    assert invalid_text("порт") == "Исправьте настройки: порт"


def test_settings_sections_have_icons():
    from src.core.config import get_asset_path
    from src.ui.logic.settings_form import SETTINGS_SECTIONS

    assert [title for _key, title, _icon in SETTINGS_SECTIONS] == [
        "Общие",
        "Мониторинг",
        "DNS",
        "Маршрутизация",
        "Обход блокировок",
        "Подписки",
        "О программе",
    ]
    for _key, _title, icon in SETTINGS_SECTIONS:
        assert get_asset_path(f"icons/ui/{icon}.svg").is_file()
