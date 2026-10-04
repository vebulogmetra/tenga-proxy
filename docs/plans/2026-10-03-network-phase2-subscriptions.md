# Сетевой слой, этап 2: подписки — план реализации

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Довести работу с подписками до уровня Android-версии: обновление без
смены id профилей, метаданные провайдера (трафик, срок, объявление, ссылки),
загрузка через работающий прокси с откатом, понятные ошибки.

**Architecture:** Всё про подписку живёт в `src/sub/`: `updater.py` качает и
раскладывает ответ, `metadata.py` разбирает заголовки и строки `#key: value`,
`errors.py`, `route.py`, `device.py` и `url_change.py` — по одной заботе на
модуль. Хранилище (`src/db/profiles.py`) получает `sync_group` — upsert вместо
«очистить и добавить заново». Интерфейс берёт готовые строки из
`src/ui/logic/subscriptions_view.py` (без GTK, обычный pytest), GTK-код только
раскладывает их по виджетам.

**Tech Stack:** Python 3.11, requests, pytest, ruff, GTK 4 + libadwaita 1.5
(задачи 4, 7, 8, 10–14).

Дорожная карта всех этапов — `2026-10-03-network-parity-roadmap.md`.

**Зависимости.** План предполагает, что **этап 1 выполнен**
(`2026-10-03-network-phase1-protocols.md`). Этапы 3 и 4 писались параллельно
с этим на той же базе — состоянии после этапа 1. Этап 4 опирается на S1
(id профилей сохраняются при обновлении), поэтому этап 2 идёт раньше. Общие с
ними файлы — `src/db/data_store.py`, `src/ui/dialogs/settings.py`,
`src/ui/application.py`; правки в них добавочные.

---

## Принятые решения

Пользователь на вопросы дорожной карты не отвечал — взяты значения по
умолчанию. Каждое можно поменять до начала работ; что при этом меняется в
плане, указано.

1. **S4, режим TUN.** Запросы приложения в TUN и так идут через туннель —
   ничего особого не делаем, отката «напрямую» с привязкой сокета к физическому
   интерфейсу нет. В режиме системного прокси при подключённом профиле — сначала
   через локальный HTTP-inbound (`socks_port + 1`), при сетевой или HTTP-ошибке
   — напрямую (задача 11).
2. **S4, поле `sub_use_proxy`.** Удаляется. Оно осталось от NekoRay, нигде не
   читалось, а настройки сохраняются целиком — у каждого пользователя в
   `settings.json` уже лежит `"sub_use_proxy": false`. Сделать его выключателем
   значило бы молча выключить новую загрузку у всех. Маршрут выбирается сам, как
   в Android. Нужен выключатель — добавить новое поле с другим именем.
3. **S5, User-Agent.** По умолчанию `v2rayNG/1.8.23` — ровно как в Android
   (`SubscriptionRequestHeaders.COMPAT_USER_AGENT`). Своё значение вводится в
   настройках (задача 12). Прежнее значение по умолчанию, если оно попало в
   `settings.json`, считается «не задано».
4. **S7 (данные устройства) и S8 (смена адреса)** — задачи 13 и 14, обе
   **необязательные**: можно вычеркнуть без последствий для остальных. S7
   выключено по умолчанию.
5. **Объявление провайдера стирается, когда провайдер его убрал.** В Android
   сохранённое объявление остаётся навсегда — похоже на недосмотр. Остальные
   метаданные, как в Android, при отсутствии в ответе сохраняют прошлое
   значение: нестандартные заголовки режет CDN.
6. **Название подписки необязательно** (задача 7). Сейчас диалог требует
   название, поэтому правило Android «`profile-title` переименовывает группу,
   пока её имя равно хосту» не сработало бы никогда.
7. **Дубликаты в ответе сохраняются.** Android оставляет один профиль на ключ
   `имя|тип|сервер|порт`; здесь два одинаковых ключа дают два профиля — как
   было до этого этапа. Ничего не теряется.
8. **`routing` из подписки не поддерживается.** В Android это импорт
   маршрутизации в формате Happ; на настольной версии такого формата нет.

## Что проверено до написания плана

Проверено 2026-10-03 запуском, а не предположено.

1. **Весь код плана прототипирован** в копии проекта (состояние после этапов 0
   и 1, ядро 26.9.9), по одному коммиту на задачу, тест раньше кода. Затем
   блоки кода **из этого файла** применены к чистой копии: после каждой задачи
   дерево файлов совпало с прототипом, обычный набор тестов зелёный
   (790 passed в конце), `ruff check` и `ruff format --check` чистые.
   Каждый красный шаг проверен отдельно: упал с указанными числами и
   сообщениями. Подробности — «Итог воспроизведения» в конце файла.
2. **GTK-код запускался**, но не на экране, а на headless-бэкенде
   `gtk4-broadwayd` со своей шиной D-Bus (рецепт — в «Соглашениях»). Прошли все
   GTK-тесты приложения, окна, страницы подписок, диалогов подписки и настроек.
   Глазами интерфейс никто не смотрел: как выглядят вторая строка в списке
   подписок, кнопка объявления и страница настроек — проверить руками (задача
   15).
3. **Не проверено на живом провайдере.** Формат заголовков взят из
   Android-версии (`docs/subscriptions/`, `SubscriptionMetadataParser.kt`,
   `SubscriptionRequestHeaders.kt`), там он обкатан на настоящих подписках.
   Загрузка через локальный HTTP-inbound проверена только на заглушках
   `requests`.

## Что нашлось при подготовке

1. **`last_updated` никогда не записывался.** Поле есть, список подписок его
   показывает, но ни одна строка кода его не меняет: у любой подписки всегда
   «Никогда». Задача 2.
2. **Адрес подписки с `&` не показывается.** Подзаголовок `Adw.ActionRow` по
   умолчанию — разметка Pango; на адресе вида `…?token=a&client=b` GTK пишет
   предупреждение и оставляет строку пустой. Задача 8.
3. **Адрес подписки (с токеном) попадает в уведомление и в журнал.** Текст
   ошибок `requests` содержит URL целиком. Задачи 4 и 11 собирают сообщения
   заново. Остаётся одно место: `src/ui/logic/async_utils.py` пишет traceback
   упавшей фоновой задачи через `logger.exception` — в нём адрес есть. Это
   общий механизм, в этом плане он не тронут.
4. **GTK-тесты диалогов не входят в `make test-gtk`.** Список `GTK4_TESTS` в
   `Makefile` собирает `test_ui_application.py`, `test_ui_window.py`,
   `test_ui_widgets_*.py`, `test_ui_pages_*.py`; `test_ui_dialogs_*.py` в нём
   нет. В плане они запускаются явно.
5. **`python cli.py sub <url>`** качает подписку собственным `requests.get`, без
   User-Agent и без `SubscriptionUpdater`. В план не входит.

## Соглашения

- Рабочая ветка: `feature/network-phase2` от ветки с выполненным этапом 1.
- Тесты: `uv run pytest <путь> -q`. Полный набор: `uv run pytest -q`.
- Перед каждым коммитом: `python cli.py lint-all`.
- Сообщения коммитов — как в истории: `fix(sub): …`, `feat(ui): …`, по-русски.
- Фрагменты `diff` сняты с прототипа. Привязывайся к **содержимому** (имя
  функции, строки контекста), а не к номерам строк в заголовках `@@`: после
  этапа 1 и параллельных этапов номера сдвинутся. Если контекст не совпал —
  файл изменился, сверяйся с кодом и переноси правку по смыслу.
- **GTK-тесты** помечены маркером `gtk` и в обычный прогон не входят. Их можно
  гонять без экрана — так проверялся этот план:

  ```bash
  gtk_test() {
    dbus-run-session -- sh -c '
      gtk4-broadwayd :27 >/dev/null 2>&1 & B=$!
      sleep 1
      env -u DISPLAY -u WAYLAND_DISPLAY GDK_DEBUG=no-portals ADW_DISABLE_PORTAL=1 \
        GDK_BACKEND=broadway BROADWAY_DISPLAY=:27 \
        uv run pytest -m gtk -p no:cacheprovider --no-cov -q "$@"
      R=$?; kill $B; exit $R' sh "$@"
  }
  ```

  Своя шина обязательна: иначе имя `ru.tenga.Proxy` занято установленным
  приложением и тесты окна пропускаются. `GDK_DEBUG=no-portals` и
  `ADW_DISABLE_PORTAL=1` убирают обращения к `xdg-desktop-portal`: без них на
  пустой шине тесты с фикстурой `adw_app` стартуют около 25 секунд (таймауты,
  не зависание). Сообщение `A connection to the bus can't be made` после
  итоговой строки pytest и предупреждения `fusermount3` к тестам не относятся.

  На broadway не работают два существующих теста геометрии окна:
  `test_narrow_window_moves_the_switcher_down` и
  `test_default_size_comes_from_saved_geometry` — оба падают (без
  `GDK_DEBUG=no-portals` первый зависает). Так было и до этого плана; для `tests/test_ui_window.py` добавляй
  `--deselect tests/test_ui_window.py::test_narrow_window_moves_the_switcher_down --deselect tests/test_ui_window.py::test_default_size_comes_from_saved_geometry`.
  С настоящим дисплеем вместо `gtk_test` годится `make test-gtk` (плюс явный
  запуск `tests/test_ui_dialogs_*.py`).
- Не запускай настоящее приложение и настоящий xray для проверки: на машине
  разработчика работает установленный Tenga с интерфейсом `xray0`.

---

### Task 0: Сверка с кодом

План написан до того, как этап 1 внесён в репозиторий. Прежде чем что-то
менять, убедись, что места, на которые он опирается, выглядят как ожидается.

**Step 1: Создать ветку**

```bash
git switch -c feature/network-phase2
```

**Step 2: Убедиться, что набор зелёный**

Run: `uv run pytest -q`
Expected: все passed. В прототипе после этапа 1 — `634 passed`; если число
другое, запиши его как базу: дальше план называет абсолютные числа, прибавляй
разницу.

**Step 3: Проверить якоря**

```bash
grep -n "self._profiles.clear_group(group_id)" src/sub/updater.py
grep -n 'sub_user_info: str = ""' src/db/profiles.py
grep -n "Prefer ClashMeta Format" src/db/data_store.py
grep -rn "sub_use_proxy" src tests
grep -rn "last_updated" src
grep -n "EMPTY_SUBSCRIPTION_NAME" src/ui/logic/forms.py
grep -n "Adw.ActionRow(title=row.name, subtitle=row.url)" src/ui/pages/subscriptions.py
grep -n '"delete-subscription",' src/ui/window.py
grep -n "self._build_dns_page()" src/ui/dialogs/settings.py
grep -n "def _default_subscription_updater" src/ui/application.py
```

Expected:

- первая команда — одна строка в `update()` (в прототипе — строка 131);
- `sub_use_proxy` — только объявление в `src/db/data_store.py`;
- `last_updated` — объявление поля в `src/db/profiles.py` и два чтения в
  `src/ui/`; **ни одной записи**;
- остальные — по одной строке.

Если какой-то якорь не нашёлся, соответствующая задача требует сверки с кодом:
прочитай файл и перенеси правку по смыслу.

**Step 4: Проверить, что GTK-тесты запускаются**

Run: `gtk_test tests/test_ui_pages_subscriptions.py tests/test_ui_dialogs_subscription.py`
Expected: `25 passed`.

Если `gtk4-broadwayd` нет — GTK-шаги задач выполняй через `make test-gtk` на
машине с дисплеем или отмечай как непроверенные в итоговом отчёте.

---

### Task 1: Сохранять id профилей при обновлении (S1)

Сейчас обновление — это `clear_group` и `add_profile` для каждого профиля.
Каждый профиль получает новый id: теряются замер задержки, `last_used`,
персональные `vpn_settings` и `routing_settings`, а `started_profile_id`
подключённого профиля указывает на удалённую запись.

Новый `ProfileManager.sync_group` делает upsert по ключу
`имя|тип|сервер|порт`:

- совпавший профиль получает новый bean, всё остальное в `ProfileEntry`
  остаётся;
- новые добавляются, пропавшие из ответа удаляются;
- порядок в группе — порядок ответа (как и раньше: профили перевставляются в
  конец словаря);
- одинаковые ключи в ответе сопоставляются по очереди, лишние становятся
  новыми профилями.

Имя входит в ключ намеренно: один сервер часто отдаёт несколько профилей с
разным транспортом, и сопоставление без имени склеило бы их. Провайдер,
переименовавший сервер, получает новый профиль — так же в Android.

**Files:**
- Modify: `src/db/profiles.py` (рядом с `ProfileGroup` и перед `clear_group`, ~стр. 44 и 339)
- Modify: `src/sub/updater.py` (`update`, ~стр. 126–134)
- Test: `tests/test_db_profiles.py`, `tests/test_sub_updater.py`

**Step 1: Написать падающие тесты хранилища**

```diff
--- a/tests/test_db_profiles.py
+++ b/tests/test_db_profiles.py
@@ -177,3 +177,94 @@ def test_marking_a_missing_profile_is_harmless(tmp_path):
     mgr = ProfileManager(profiles_dir=tmp_path)
     mgr.mark_used(42)
     assert mgr.last_used_profile() is None
+
+
+# --- sync_group: обновление подписки без смены id -----------------------------
+
+
+def _vless(name: str, server: str = "a.example.org", port: int = 443, uuid: str = "u-1"):
+    from src.fmt.protocols import VLESSBean
+
+    return VLESSBean(name=name, server_address=server, server_port=port, uuid=uuid)
+
+
+def test_profile_match_key_is_name_type_server_port():
+    from src.db.profiles import profile_match_key
+
+    assert profile_match_key(_vless("NL-1")) == "NL-1|vless|a.example.org|443"
+
+
+def test_sync_group_keeps_id_and_user_data_of_a_matched_profile(tmp_path):
+    from src.db.config import RoutingSettings, VpnSettings
+
+    manager = ProfileManager(profiles_dir=tmp_path)
+    group = manager.add_group("Sub", is_subscription=True)
+    entry = manager.add_profile(_vless("NL-1", uuid="old"), group.id)
+    entry.latency_ms = 87
+    entry.last_used = 1_700_000_000
+    entry.vpn_settings = VpnSettings()
+    entry.routing_settings = RoutingSettings()
+
+    manager.sync_group(group.id, [_vless("NL-1", uuid="new")])
+
+    synced = manager.get_profiles_in_group(group.id)
+    assert [p.id for p in synced] == [entry.id]
+    assert synced[0].bean.uuid == "new"
+    assert synced[0].latency_ms == 87
+    assert synced[0].last_used == 1_700_000_000
+    assert synced[0].vpn_settings is entry.vpn_settings
+    assert synced[0].routing_settings is entry.routing_settings
+
+
+def test_sync_group_adds_new_and_removes_missing_profiles(tmp_path):
+    manager = ProfileManager(profiles_dir=tmp_path)
+    group = manager.add_group("Sub", is_subscription=True)
+    kept = manager.add_profile(_vless("NL-1"), group.id)
+    gone = manager.add_profile(_vless("DE-1", server="b.example.org"), group.id)
+
+    result = manager.sync_group(group.id, [_vless("NL-1"), _vless("FI-1", server="c.example.org")])
+
+    names = {p.name: p.id for p in manager.get_profiles_in_group(group.id)}
+    assert set(names) == {"NL-1", "FI-1"}
+    assert names["NL-1"] == kept.id
+    assert names["FI-1"] not in (kept.id, gone.id)
+    assert manager.get_profile(gone.id) is None
+    assert (result.updated, result.added, result.removed) == (1, 1, 1)
+
+
+def test_sync_group_follows_the_order_of_the_response(tmp_path):
+    manager = ProfileManager(profiles_dir=tmp_path)
+    group = manager.add_group("Sub", is_subscription=True)
+    manager.add_profile(_vless("B"), group.id)
+    manager.add_profile(_vless("C"), group.id)
+
+    manager.sync_group(group.id, [_vless("A"), _vless("C"), _vless("B")])
+
+    assert [p.name for p in manager.get_profiles_in_group(group.id)] == ["A", "C", "B"]
+
+
+def test_sync_group_does_not_touch_other_groups(tmp_path):
+    manager = ProfileManager(profiles_dir=tmp_path)
+    group = manager.add_group("Sub", is_subscription=True)
+    other = manager.add_group("Manual")
+    manual = manager.add_profile(_vless("NL-1"), other.id)
+
+    manager.sync_group(group.id, [_vless("NL-1")])
+
+    assert manager.get_profile(manual.id) is manual
+    assert [p.id for p in manager.get_profiles_in_group(other.id)] == [manual.id]
+    assert len(manager.get_profiles_in_group(group.id)) == 1
+
+
+def test_sync_group_keeps_duplicates_from_the_response(tmp_path):
+    """Два одинаковых ключа в ответе — два профиля, как и до перехода на upsert."""
+    manager = ProfileManager(profiles_dir=tmp_path)
+    group = manager.add_group("Sub", is_subscription=True)
+    first = manager.add_profile(_vless("NL-1", uuid="a"), group.id)
+
+    manager.sync_group(group.id, [_vless("NL-1", uuid="a"), _vless("NL-1", uuid="b")])
+
+    synced = manager.get_profiles_in_group(group.id)
+    assert len(synced) == 2
+    assert synced[0].id == first.id
+    assert synced[1].id != first.id
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_db_profiles.py -q`
Expected: 6 failed, 8 passed. В сообщениях — `cannot import name
'profile_match_key'` и `'ProfileManager' object has no attribute 'sync_group'`.

**Step 3: Реализовать `sync_group`**

```diff
--- a/src/db/profiles.py
+++ b/src/db/profiles.py
@@ -40,6 +40,25 @@ def _get_protocol_classes() -> dict[str, type[ProxyBean]]:
     }
 
 
+def profile_match_key(bean: ProxyBean) -> str:
+    """Identity of a profile inside a subscription: name, type, server and port.
+
+    Имя входит в ключ намеренно: провайдер, переименовавший сервер, получает
+    новый профиль. Сопоставление «по адресу без имени» склеило бы разные
+    профили на одном сервере (один хост, разные транспорты).
+    """
+    return f"{bean.name}|{bean.proxy_type}|{bean.server_address}|{bean.server_port}"
+
+
+@dataclass(frozen=True)
+class GroupSyncResult:
+    """What sync_group did to the group."""
+
+    updated: int = 0
+    added: int = 0
+    removed: int = 0
+
+
 @dataclass
 class ProfileGroup(ConfigBase):
     """Profile group."""
@@ -336,6 +355,45 @@ class ProfileManager:
             print(f"Error saving profiles: {e}")
             return False
 
+    def sync_group(self, group_id: int, beans: list[ProxyBean]) -> GroupSyncResult:
+        """Replace the group content with ``beans``, keeping ids of matching profiles.
+
+        Совпавший по ``profile_match_key`` профиль обновляется на месте: id,
+        замер задержки, ``last_used`` и персональные настройки остаются. Иначе
+        после каждого обновления подписки подключённый профиль терял бы id, и
+        ``started_profile_id`` указывал бы в пустоту. Пропавшие из ответа
+        удаляются. Порядок в группе — порядок ответа.
+        """
+        existing: dict[str, list[ProfileEntry]] = {}
+        for entry in self._profiles.values():
+            if entry.group_id == group_id:
+                existing.setdefault(profile_match_key(entry.bean), []).append(entry)
+
+        synced: list[ProfileEntry] = []
+        updated = added = 0
+        for bean in beans:
+            candidates = existing.get(profile_match_key(bean))
+            if candidates:
+                entry = candidates.pop(0)
+                entry.bean = bean
+                updated += 1
+            else:
+                entry = ProfileEntry(id=self._next_profile_id, group_id=group_id, bean=bean)
+                self._next_profile_id += 1
+                added += 1
+            synced.append(entry)
+
+        leftovers = [entry.id for entries in existing.values() for entry in entries]
+        # Перевставка в конец задаёт порядок ответа: словарь хранит порядок вставки.
+        for entry in synced:
+            self._profiles.pop(entry.id, None)
+        for profile_id in leftovers:
+            del self._profiles[profile_id]
+        for entry in synced:
+            self._profiles[entry.id] = entry
+
+        return GroupSyncResult(updated=updated, added=added, removed=len(leftovers))
+
     def clear_group(self, group_id: int) -> int:
         """Clear group (remove all profiles)."""
         profile_ids = [p.id for p in self._profiles.values() if p.group_id == group_id]
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_db_profiles.py -q`
Expected: 14 passed.

**Step 5: Написать тесты обновления**

`MockBean` в существующем тесте получает поля, из которых строится ключ: без
них `sync_group` упадёт на `AttributeError`.

```diff
--- a/tests/test_sub_updater.py
+++ b/tests/test_sub_updater.py
@@ -9,6 +9,9 @@ from src.sub.updater import SubscriptionUpdater, update_subscription
 class MockBean:
     display_name: str = "Test"
     proxy_type: str = "test"
+    name: str = "Test"
+    server_address: str = "example.com"
+    server_port: int = 443
 
     def to_dict(self) -> dict[str, str]:
         return {"type": "test"}
@@ -180,3 +183,69 @@ def test_fetch_respects_an_explicit_charset():
         result = SubscriptionUpdater().fetch("http://example.com/sub")
 
     assert result == text
+
+
+# --- Обновление без смены id --------------------------------------------------
+
+LINK_NL = "vless://11111111-1111-1111-1111-111111111111@nl.example.org:443?type=tcp#NL-1"
+LINK_DE = "vless://22222222-2222-2222-2222-222222222222@de.example.org:443?type=tcp#DE-1"
+
+
+def _text_response(text: str) -> Mock:
+    response = Mock()
+    response.text = text
+    response.raise_for_status = Mock()
+    return response
+
+
+def _subscription(tmp_path):
+    from src.db.profiles import ProfileManager
+
+    profiles = ProfileManager(profiles_dir=tmp_path)
+    group = profiles.add_group("Sub", is_subscription=True)
+    return profiles, group
+
+
+def test_update_keeps_the_id_and_latency_of_a_profile_still_in_the_response(tmp_path):
+    profiles, group = _subscription(tmp_path)
+    updater = SubscriptionUpdater(profiles=profiles)
+
+    with patch("src.sub.updater.requests.get") as mock_get:
+        mock_get.return_value = _text_response(f"{LINK_NL}\n{LINK_DE}")
+        updater.update("http://example.com/sub", group_id=group.id)
+        before = {p.name: p for p in profiles.get_profiles_in_group(group.id)}
+        before["NL-1"].latency_ms = 42
+
+        mock_get.return_value = _text_response(LINK_NL)
+        updater.update("http://example.com/sub", group_id=group.id)
+
+    after = profiles.get_profiles_in_group(group.id)
+    assert [p.name for p in after] == ["NL-1"]
+    assert after[0].id == before["NL-1"].id
+    assert after[0].latency_ms == 42
+
+
+def test_update_with_an_empty_response_leaves_the_group_alone(tmp_path):
+    """Пустой ответ — сбой провайдера, а не «серверов больше нет»."""
+    profiles, group = _subscription(tmp_path)
+    updater = SubscriptionUpdater(profiles=profiles)
+
+    with patch("src.sub.updater.requests.get") as mock_get:
+        mock_get.return_value = _text_response(LINK_NL)
+        updater.update("http://example.com/sub", group_id=group.id)
+        mock_get.return_value = _text_response("<html>maintenance</html>")
+        assert updater.update("http://example.com/sub", group_id=group.id) == []
+
+    assert [p.name for p in profiles.get_profiles_in_group(group.id)] == ["NL-1"]
+
+
+def test_update_without_clearing_appends_to_the_group(tmp_path):
+    profiles, group = _subscription(tmp_path)
+    updater = SubscriptionUpdater(profiles=profiles)
+
+    with patch("src.sub.updater.requests.get") as mock_get:
+        mock_get.return_value = _text_response(LINK_NL)
+        updater.update("http://example.com/sub", group_id=group.id)
+        updater.update("http://example.com/sub", group_id=group.id, clear_existing=False)
+
+    assert [p.name for p in profiles.get_profiles_in_group(group.id)] == ["NL-1", "NL-1"]
```

**Step 6: Убедиться, что падает нужный**

Run: `uv run pytest tests/test_sub_updater.py -q`
Expected: 1 failed, 11 passed —
`test_update_keeps_the_id_and_latency_of_a_profile_still_in_the_response`
(`assert 3 == 1`: профиль получил новый id). Два других новых теста проходят
сразу: они закрепляют поведение, которое нельзя сломать (пустой ответ не
трогает группу; `clear_existing=False` дописывает).

**Step 7: Перевести `update` на `sync_group`**

```diff
--- a/src/sub/updater.py
+++ b/src/sub/updater.py
@@ -128,10 +128,12 @@ class SubscriptionUpdater:
                 group_id = self._profiles.current_group_id
 
             if clear_existing:
-                self._profiles.clear_group(group_id)
-
-            for bean in beans:
-                self._profiles.add_profile(bean, group_id)
+                # Не clear_group + add_profile: так профили получали новые id, и
+                # подключённый профиль, замеры и персональные настройки терялись.
+                self._profiles.sync_group(group_id, beans)
+            else:
+                for bean in beans:
+                    self._profiles.add_profile(bean, group_id)
 
             self._profiles.save()
 
```

**Step 8: Полный прогон**

Run: `uv run pytest -q`
Expected: `643 passed`.

**Step 9: Commit**

```bash
git add src/db/profiles.py src/sub/updater.py tests/test_db_profiles.py tests/test_sub_updater.py
git commit -m "fix(sub): сохранять id профилей при обновлении подписки"
```

---

### Task 2: Записывать время обновления

`ProfileGroup.last_updated` показывается в списке и в диалоге подписки, но
нигде не записывается. Время ставится только при непустом ответе: ноль
серверов — это сбой провайдера, а не обновление.

**Files:**
- Modify: `src/sub/updater.py` (`update`)
- Test: `tests/test_sub_updater.py`

**Step 1: Написать тесты**

```diff
--- a/tests/test_sub_updater.py
+++ b/tests/test_sub_updater.py
@@ -249,3 +249,30 @@ def test_update_without_clearing_appends_to_the_group(tmp_path):
         updater.update("http://example.com/sub", group_id=group.id, clear_existing=False)
 
     assert [p.name for p in profiles.get_profiles_in_group(group.id)] == ["NL-1", "NL-1"]
+
+
+# --- Время обновления ---------------------------------------------------------
+
+
+def test_update_records_when_the_subscription_was_refreshed(tmp_path):
+    profiles, group = _subscription(tmp_path)
+    updater = SubscriptionUpdater(profiles=profiles)
+
+    with (
+        patch("src.sub.updater.requests.get", return_value=_text_response(LINK_NL)),
+        patch("src.sub.updater.time.time", return_value=1_800_000_000.7),
+    ):
+        updater.update("http://example.com/sub", group_id=group.id)
+
+    assert group.last_updated == 1_800_000_000
+
+
+def test_an_empty_response_does_not_count_as_a_refresh(tmp_path):
+    profiles, group = _subscription(tmp_path)
+    group.last_updated = 1_700_000_000
+    updater = SubscriptionUpdater(profiles=profiles)
+
+    with patch("src.sub.updater.requests.get", return_value=_text_response("nothing here")):
+        updater.update("http://example.com/sub", group_id=group.id)
+
+    assert group.last_updated == 1_700_000_000
```

**Step 2: Убедиться, что падает**

Run: `uv run pytest tests/test_sub_updater.py -q`
Expected: 1 failed, 13 passed — `test_update_records_when_the_subscription_was_refreshed`
(`assert 0 == 1800000000`). Тест про пустой ответ проходит сразу.

**Step 3: Реализовать**

```diff
--- a/src/sub/updater.py
+++ b/src/sub/updater.py
@@ -135,6 +135,10 @@ class SubscriptionUpdater:
                 for bean in beans:
                     self._profiles.add_profile(bean, group_id)
 
+            group = self._profiles.get_group(group_id)
+            if group is not None:
+                group.last_updated = int(time.time())
+
             self._profiles.save()
 
         return beans
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_sub_updater.py -q`
Expected: 14 passed.

**Step 5: Commit**

```bash
git add src/sub/updater.py tests/test_sub_updater.py
git commit -m "fix(sub): записывать время обновления подписки"
```

---

### Task 3: User-Agent по умолчанию (S5)

Прежнее значение — `Tenga-proxy/1.0 (Prefer ClashMeta Format)` — просит у
провайдера Clash YAML, который приложение не разбирает
(`src/fmt/parsers.py`, `# TODO: Parse Clash YAML`). Провайдер вправе ответить
YAML, и подписка даст ноль профилей. Новое значение — как в Android.

Старое значение по умолчанию приравнивается к «не задано»: в `settings.json`
оно могло попасть только как сохранённое значение по умолчанию, выбором
пользователя оно не было.

**Files:**
- Modify: `src/db/data_store.py` (константы перед `DataStore`, `get_user_agent`, ~стр. 121)
- Test: `tests/test_db_data_store.py`

**Step 1: Написать тесты**

```diff
--- a/tests/test_db_data_store.py
+++ b/tests/test_db_data_store.py
@@ -1,4 +1,5 @@
 from src.db.data_store import (
+    DEFAULT_USER_AGENT,
     DataStore,
     get_default_config_path,
     load_data_store,
@@ -26,11 +27,32 @@ def test_to_dict_excludes_runtime_fields():
 def test_get_user_agent_default_and_custom():
     store = DataStore()
 
-    assert "Tenga-proxy" in store.get_user_agent()
+    assert store.get_user_agent() == DEFAULT_USER_AGENT
 
     store.user_agent = "MyAgent/1.0"
     assert store.get_user_agent() == "MyAgent/1.0"
-    assert "Tenga-proxy" in store.get_user_agent(use_default=True)
+    assert store.get_user_agent(use_default=True) == DEFAULT_USER_AGENT
+
+
+def test_default_user_agent_is_one_providers_recognise():
+    """Незнакомому клиенту часть провайдеров рвёт соединение или отдаёт Clash YAML."""
+    assert DEFAULT_USER_AGENT == "v2rayNG/1.8.23"
+    assert "clash" not in DEFAULT_USER_AGENT.lower()
+
+
+def test_the_old_default_user_agent_is_not_treated_as_a_custom_one():
+    """Прежнее значение по умолчанию могло попасть в settings.json как «своё»."""
+    store = DataStore()
+    store.user_agent = "Tenga-proxy/1.0 (Prefer ClashMeta Format)"
+
+    assert store.get_user_agent() == DEFAULT_USER_AGENT
+
+
+def test_a_blank_user_agent_falls_back_to_the_default():
+    store = DataStore()
+    store.user_agent = "   "
+
+    assert store.get_user_agent() == DEFAULT_USER_AGENT
 
 
 def test_update_started_id_and_remember():
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_db_data_store.py -q`
Expected: ошибка сборки тестов —
`ImportError: cannot import name 'DEFAULT_USER_AGENT'`.

**Step 3: Реализовать**

```diff
--- a/src/db/data_store.py
+++ b/src/db/data_store.py
@@ -15,6 +15,14 @@ from src.db.config import (
     VpnSettings,
 )
 
+# Так представляется провайдеру подписки Android-версия. v2rayNG знают все панели
+# и отдают ему список ссылок; незнакомому клиенту часть провайдеров рвёт
+# соединение ещё на TLS-рукопожатии.
+DEFAULT_USER_AGENT = "v2rayNG/1.8.23"
+# Значение по умолчанию до этапа 2. Просило Clash YAML, который приложение не
+# разбирает: провайдер был вправе ответить YAML, и подписка давала ноль профилей.
+LEGACY_USER_AGENT = "Tenga-proxy/1.0 (Prefer ClashMeta Format)"
+
 
 @dataclass
 class DataStore(ConfigBase):
@@ -120,9 +128,10 @@ class DataStore(ConfigBase):
 
     def get_user_agent(self, use_default: bool = False) -> str:
         """Get User-Agent."""
-        if use_default or not self.user_agent:
-            return "Tenga-proxy/1.0 (Prefer ClashMeta Format)"
-        return self.user_agent
+        custom = self.user_agent.strip()
+        if use_default or not custom or custom == LEGACY_USER_AGENT:
+            return DEFAULT_USER_AGENT
+        return custom
 
     def update_started_id(self, profile_id: int) -> None:
         """Update started profile ID."""
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_db_data_store.py tests/test_sub_updater.py -q`
Expected: 24 passed.

**Step 5: Commit**

```bash
git add src/db/data_store.py tests/test_db_data_store.py
git commit -m "fix(sub): представляться провайдеру как v2rayNG, а не просить Clash YAML"
```

---

### Task 4: Ошибки и предел размера (S6)

Три изменения:

- HTTP-ошибка становится `SubscriptionHttpError` с кодом и началом тела ответа.
  При 403 и 429 начало тела показывается пользователю: провайдеры пишут там
  причину («превышен лимит устройств»). HTML-страницы CDN отбрасываются.
  Класс наследует `requests.HTTPError` — код, который ловит её, не ломается.
- Ответ длиннее 10 МБ — `SubscriptionTooLargeError`, без повторов. Как в
  Android, проверяется уже прочитанное тело: это защищает разбор, а не
  загрузку. Обрыв загрузки на лету потребовал бы `stream=True` и переписывания
  всех заглушек ответа в тестах — отдельное улучшение.
- Сообщение об ошибке для уведомления собирает
  `describe_update_error` — без адреса подписки. Текст ошибок `requests`
  содержит URL целиком, а в нём токен.

**Files:**
- Create: `src/sub/errors.py`
- Modify: `src/sub/updater.py` (импорты, цикл в `fetch`, новый `_raise_for_status`, `_is_retryable`)
- Modify: `src/ui/logic/subscriptions_view.py` (новая функция в конце файла)
- Modify: `src/ui/application.py` (импорт, `_refresh_subscriptions`, `_on_subscriptions_failed`)
- Test: `tests/test_sub_errors.py` (новый), `tests/test_ui_logic_subscriptions_view.py`, `tests/test_ui_application.py` (GTK)

**Step 1: Написать падающие тесты**

Создать файл `tests/test_sub_errors.py`:

```python
"""Ошибки загрузки подписки: что показать пользователю вместо голого кода."""

from unittest.mock import Mock, patch

import pytest
import requests

from src.sub.errors import (
    MAX_RESPONSE_SIZE,
    SubscriptionHttpError,
    SubscriptionTooLargeError,
    snippet_of,
)
from src.sub.updater import SubscriptionUpdater


def _http_error_response(status: int, body: str) -> Mock:
    response = Mock()
    response.status_code = status
    response.text = body
    response.content = body.encode("utf-8")
    response.encoding = "utf-8"
    response.headers = {"Content-Type": "text/plain; charset=utf-8"}
    response.raise_for_status = Mock(side_effect=requests.HTTPError(f"{status} Client Error"))
    return response


def test_snippet_collapses_whitespace_and_drops_control_characters():
    assert snippet_of("  Device\tlimit\r\n\r\n reached\x00\x07 ") == "Device limit reached"


def test_snippet_is_cut_to_200_characters():
    assert len(snippet_of("a" * 500)) == 200


@pytest.mark.parametrize("body", ["<html><body>403</body></html>", "  <!DOCTYPE html><html>"])
def test_snippet_ignores_html_pages(body):
    """Страница-заглушка CDN ничего не объясняет и только засоряет сообщение."""
    assert snippet_of(body) == ""


@pytest.mark.parametrize("body", [None, 12, Mock()])
def test_snippet_of_a_non_text_body_is_empty(body):
    assert snippet_of(body) == ""


@pytest.mark.parametrize("status", [403, 429])
def test_access_denied_error_shows_the_providers_explanation(status):
    error = SubscriptionHttpError(status, "Превышен лимит устройств")

    assert error.is_access_denied
    assert str(error) == f"HTTP {status}: Превышен лимит устройств"


def test_other_http_errors_show_only_the_code():
    error = SubscriptionHttpError(404, "Not Found")

    assert not error.is_access_denied
    assert str(error) == "HTTP 404"


def test_fetch_raises_http_error_with_the_body_snippet():
    with patch("src.sub.updater.requests.get") as mock_get:
        mock_get.return_value = _http_error_response(403, "Device limit reached\n")
        with pytest.raises(SubscriptionHttpError) as caught:
            SubscriptionUpdater().fetch("https://example.com/sub/secret-token")

    assert caught.value.status_code == 403
    assert caught.value.body_snippet == "Device limit reached"
    # Адрес подписки содержит токен: в тексте ошибки его быть не должно.
    assert "secret-token" not in str(caught.value)
    assert mock_get.call_count == 1


def test_http_error_is_still_a_requests_http_error():
    """Код, который ловит requests.HTTPError, не должен сломаться."""
    assert issubclass(SubscriptionHttpError, requests.HTTPError)


def test_fetch_rejects_a_response_over_the_size_limit():
    response = Mock()
    response.text = "x" * (MAX_RESPONSE_SIZE + 1)
    response.raise_for_status = Mock()

    with (
        patch("src.sub.updater.requests.get", return_value=response) as mock_get,
        pytest.raises(SubscriptionTooLargeError),
    ):
        SubscriptionUpdater().fetch("https://example.com/sub")

    # Слишком большой ответ — окончательный: повтор вернёт то же самое.
    assert mock_get.call_count == 1


def test_size_limit_is_ten_megabytes():
    assert MAX_RESPONSE_SIZE == 10 * 1024 * 1024
```

```diff
--- a/tests/test_ui_logic_subscriptions_view.py
+++ b/tests/test_ui_logic_subscriptions_view.py
@@ -90,3 +90,50 @@ def test_url_is_not_truncated(sample):
     groups[1].subscription_url = "https://sub.example/" + "x" * 200
     rows = build_subscription_rows(groups, counts, query="xxxxx")
     assert rows[0].url == groups[1].subscription_url
+
+
+# --- Сообщение об ошибке обновления -------------------------------------------
+
+
+def test_access_denied_is_described_with_the_providers_text():
+    from src.sub.errors import SubscriptionHttpError
+    from src.ui.logic.subscriptions_view import describe_update_error
+
+    text = describe_update_error(SubscriptionHttpError(403, "Превышен лимит устройств"))
+
+    assert text == "сервер ответил 403: Превышен лимит устройств"
+
+
+def test_other_http_errors_are_described_by_code():
+    from src.sub.errors import SubscriptionHttpError
+    from src.ui.logic.subscriptions_view import describe_update_error
+
+    assert describe_update_error(SubscriptionHttpError(404, "Not Found")) == "сервер ответил 404"
+
+
+def test_too_large_response_is_described():
+    from src.sub.errors import SubscriptionTooLargeError
+    from src.ui.logic.subscriptions_view import describe_update_error
+
+    assert describe_update_error(SubscriptionTooLargeError(11 * 1024 * 1024)) == (
+        "ответ сервера больше 10 МБ"
+    )
+
+
+def test_network_errors_do_not_leak_the_subscription_address():
+    """Текст ошибки requests содержит полный URL, а в нём — токен подписки."""
+    import requests
+
+    from src.ui.logic.subscriptions_view import describe_update_error
+
+    refused = requests.ConnectionError("HTTPSConnectionPool(host='x'): /sub/secret-token")
+    timeout = requests.Timeout("Read timed out: /sub/secret-token")
+
+    assert describe_update_error(refused) == "нет связи с сервером подписки"
+    assert describe_update_error(timeout) == "сервер подписки не ответил вовремя"
+
+
+def test_unknown_errors_fall_back_to_their_text():
+    from src.ui.logic.subscriptions_view import describe_update_error
+
+    assert describe_update_error(ValueError("boom")) == "boom"
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_sub_errors.py tests/test_ui_logic_subscriptions_view.py -q`
Expected: ошибка сборки `No module named 'src.sub.errors'` — на ней pytest
останавливается. Пять новых тестов описания ошибки упадут на
`cannot import name 'describe_update_error'`, если запустить их файл отдельно.

**Step 3: Реализовать ошибки и их описание**

Создать файл `src/sub/errors.py`:

```python
"""Ошибки загрузки подписки."""

from __future__ import annotations

import re
from typing import Any

import requests

MAX_RESPONSE_SIZE = 10 * 1024 * 1024
MAX_SNIPPET = 200

_ACCESS_DENIED = (403, 429)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_WHITESPACE = re.compile(r"\s+")


def snippet_of(raw_body: Any) -> str:
    """Начало тела ответа, пригодное для показа в одной строке.

    Провайдеры объясняют отказ в теле («превышен лимит устройств»): это
    полезнее голого кода. HTML-страницы CDN ничего не объясняют и отбрасываются.
    """
    if not isinstance(raw_body, str):
        return ""
    text = _WHITESPACE.sub(" ", _CONTROL_CHARS.sub("", raw_body)).strip()
    if text.startswith("<"):
        return ""
    return text[:MAX_SNIPPET]


class SubscriptionHttpError(requests.HTTPError):
    """Окончательный HTTP-ответ провайдера: не повторяется.

    Текст ошибки не содержит адреса подписки — в нём токен пользователя, а
    сообщение уходит в уведомление и в журнал.
    """

    def __init__(self, status_code: int, body_snippet: str = "", **kwargs: Any) -> None:
        self.status_code = status_code
        self.body_snippet = body_snippet
        super().__init__(self._message(), **kwargs)

    @property
    def is_access_denied(self) -> bool:
        return self.status_code in _ACCESS_DENIED

    def _message(self) -> str:
        if self.is_access_denied and self.body_snippet:
            return f"HTTP {self.status_code}: {self.body_snippet}"
        return f"HTTP {self.status_code}"


class SubscriptionTooLargeError(requests.RequestException):
    """Ответ больше MAX_RESPONSE_SIZE: окончательный, повтор вернёт то же самое."""

    def __init__(self, size: int) -> None:
        self.size = size
        super().__init__(f"Ответ сервера слишком большой: {size} символов")
```

```diff
--- a/src/sub/updater.py
+++ b/src/sub/updater.py
@@ -8,6 +8,12 @@ import requests
 
 from src.db import DataStore
 from src.fmt import ProxyBean, parse_subscription_content
+from src.sub.errors import (
+    MAX_RESPONSE_SIZE,
+    SubscriptionHttpError,
+    SubscriptionTooLargeError,
+    snippet_of,
+)
 
 if TYPE_CHECKING:
     from src.db.profiles import ProfileManager
@@ -46,8 +52,13 @@ class SubscriptionUpdater:
         for attempt in range(self.MAX_ATTEMPTS):
             try:
                 response = requests.get(url, headers=headers, timeout=30, verify=verify)
-                response.raise_for_status()
-                return self._decode(response)
+                self._raise_for_status(response)
+                content = self._decode(response)
+                # Как в Android: проверяется уже прочитанное тело. Защищает разбор
+                # от гигантского ответа, но не саму загрузку.
+                if len(content) > MAX_RESPONSE_SIZE:
+                    raise SubscriptionTooLargeError(len(content))
+                return content
             except requests.RequestException as e:
                 # Повторяем только сетевые сбои: HTTP-код — окончательный ответ
                 # сервера, повтор лишь задержит обновление.
@@ -67,6 +78,18 @@ class SubscriptionUpdater:
         # Недостижимо: последняя попытка либо возвращает результат, либо бросает.
         raise last_error or requests.RequestException("Не удалось загрузить подписку")
 
+    @classmethod
+    def _raise_for_status(cls, response: requests.Response) -> None:
+        """Turn an HTTP error into one carrying the start of the response body."""
+        try:
+            response.raise_for_status()
+        except requests.HTTPError as e:
+            status = getattr(response, "status_code", 0)
+            raise SubscriptionHttpError(
+                status if isinstance(status, int) else 0,
+                snippet_of(cls._decode(response)),
+            ) from e
+
     @staticmethod
     def _decode(response: requests.Response) -> str:
         """Read the body as text, assuming UTF-8 when no charset is declared.
@@ -93,7 +116,7 @@ class SubscriptionUpdater:
         HTTPError — это ответ сервера (404/403/500), повтор ничего не изменит.
         Обрывы соединения и таймауты обычно разовые.
         """
-        if isinstance(error, requests.HTTPError):
+        if isinstance(error, (requests.HTTPError, SubscriptionTooLargeError)):
             return False
         return isinstance(error, (requests.ConnectionError, requests.Timeout))
 
```

```diff
--- a/src/ui/logic/subscriptions_view.py
+++ b/src/ui/logic/subscriptions_view.py
@@ -68,3 +68,29 @@ def build_subscription_rows(
         )
 
     return rows
+
+
+def describe_update_error(error: BaseException) -> str:
+    """Explain a failed update without quoting the subscription address.
+
+    Текст ошибок requests содержит полный URL, а в нём — токен подписки:
+    сообщение уходит в уведомление и в журнал, поэтому собирается заново.
+    """
+    # Импорт внутри функции: модуль списка подписок не должен тянуть requests
+    # при каждом открытии окна.
+    import requests
+
+    from src.sub.errors import SubscriptionHttpError, SubscriptionTooLargeError
+
+    if isinstance(error, SubscriptionHttpError):
+        text = f"сервер ответил {error.status_code}"
+        if error.is_access_denied and error.body_snippet:
+            text += f": {error.body_snippet}"
+        return text
+    if isinstance(error, SubscriptionTooLargeError):
+        return "ответ сервера больше 10 МБ"
+    if isinstance(error, requests.Timeout):
+        return "сервер подписки не ответил вовремя"
+    if isinstance(error, requests.ConnectionError):
+        return "нет связи с сервером подписки"
+    return str(error)
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_sub_errors.py tests/test_ui_logic_subscriptions_view.py tests/test_sub_updater.py tests/test_sub_updater_retry_json.py -q`
Expected: 53 passed.

**Step 5: Написать GTK-тесты уведомления**

```diff
--- a/tests/test_ui_application.py
+++ b/tests/test_ui_application.py
@@ -161,6 +161,42 @@ def test_refresh_without_subscriptions_is_a_no_op(adw_app):
     assert called == []
 
 
+def test_a_failed_update_explains_the_reason_without_the_address(adw_app):
+    import requests
+
+    adw_app.activate()
+    group = adw_app.context.profiles.add_group("Подписка", is_subscription=True)
+    group.subscription_url = "https://sub.example/secret-token"
+
+    def failing(_group_id: int, url: str) -> int:
+        raise requests.ConnectionError(f"Max retries exceeded with url: {url}")
+
+    adw_app.set_subscription_updater(failing)
+    adw_app.update_subscription(group.id)
+    adw_app.wait_for_subscriptions_for_test()
+
+    assert adw_app.last_toast_for_test == (
+        "Не удалось обновить подписки: нет связи с сервером подписки"
+    )
+
+
+def test_a_denied_update_shows_the_providers_explanation(adw_app):
+    from src.sub.errors import SubscriptionHttpError
+
+    adw_app.activate()
+    group = adw_app.context.profiles.add_group("Подписка", is_subscription=True)
+    group.subscription_url = "https://sub.example/list"
+
+    def denied(_group_id: int, _url: str) -> int:
+        raise SubscriptionHttpError(403, "Превышен лимит устройств")
+
+    adw_app.set_subscription_updater(denied)
+    adw_app.update_subscription(group.id)
+    adw_app.wait_for_subscriptions_for_test()
+
+    assert "403: Превышен лимит устройств" in adw_app.last_toast_for_test
+
+
 # --- подключение и диалоги (этап 3) ---
 
 LINK = "vless://11111111-1111-1111-1111-111111111111@host.example:443?type=tcp#Новый"
```

**Step 6: Убедиться, что падает**

Run: `gtk_test tests/test_ui_application.py -k "update"`
Expected: 1 failed —
`test_a_failed_update_explains_the_reason_without_the_address`: в уведомлении
текст ошибки `requests` вместе с адресом. Второй новый тест проходит сразу:
текст `SubscriptionHttpError` уже не содержит адреса.

**Step 7: Подключить описание ошибки в приложении**

```diff
--- a/src/ui/application.py
+++ b/src/ui/application.py
@@ -18,6 +18,7 @@ from src.ui.logic.async_utils import run_in_background
 from src.ui.logic.latency import LatencyRunner
 from src.ui.logic.profiles_view import SortKey
 from src.ui.logic.status import ConnectionState
+from src.ui.logic.subscriptions_view import describe_update_error
 from src.ui.logic.version import app_version, core_version
 from src.ui.window import APP_ICON, MainWindow, load_css, load_icons
 
@@ -704,7 +705,7 @@ class TengaApplication(Adw.Application):
                 try:
                     total += updater(group_id, url)
                 except Exception as e:
-                    logger.warning("Subscription %s failed: %s", group_id, e)
+                    logger.warning("Subscription %s failed: %s", group_id, describe_update_error(e))
             return total
 
         self.toast(f"Обновляю подписки: {len(targets)}")
@@ -726,7 +727,7 @@ class TengaApplication(Adw.Application):
         self.toast(f"Обновлено профилей: {total}")
 
     def _on_subscriptions_failed(self, error: BaseException) -> None:
-        self.toast(f"Не удалось обновить подписки: {error}")
+        self.toast(f"Не удалось обновить подписки: {describe_update_error(error)}")
 
     def _toggle_search(self) -> None:
         if self._window is not None:
```

**Step 8: Убедиться, что проходят**

Run: `gtk_test tests/test_ui_application.py -k "subscription or update"`
Expected: 7 passed.

Run: `uv run pytest -q`
Expected: `667 passed`.

**Step 9: Commit**

```bash
git add src/sub/errors.py src/sub/updater.py src/ui/logic/subscriptions_view.py \
        src/ui/application.py tests/test_sub_errors.py \
        tests/test_ui_logic_subscriptions_view.py tests/test_ui_application.py
git commit -m "feat(sub): объяснять отказ провайдера и ограничить размер ответа"
```

---

### Task 5: Разбор метаданных подписки (S2, часть 1)

Чистый модуль без сети и без хранилища. Правила — из Android
(`SubscriptionMetadataParser.kt`, `docs/subscriptions/gotchas.md`):

| Ключ | Что это |
|---|---|
| `subscription-userinfo` | `upload=N; download=N; total=N; expire=N` — байты и unix-время. Разбор нестрогий: мусорные пары пропускаются |
| `profile-update-interval` | часы; только для показа, фонового обновления нет |
| `announce` | объявление провайдера |
| `support-url`, `profile-web-page-url` | ссылки |
| `profile-title` | название подписки; управляющие символы вырезаются, длина до 64 |

- Ключи приходят заголовками ответа (регистр не важен) и строками
  `#key: value` в теле, в том числе внутри base64-тела. **Тело важнее
  заголовков:** CDN режет нестандартные заголовки, а тело провайдер
  контролирует целиком.
- Любое значение может идти с префиксом `base64:`. `announce` декодируется и
  без префикса (так исторически делают провайдеры), но только если результат —
  корректный UTF-8 без управляющих символов: обычный текст должен остаться
  собой.
- Ключи, которыми провайдер управлял бы клиентом (`hide-settings`, `routing`,
  mux, per-app), не распознаются — намеренно.

**Files:**
- Create: `src/sub/metadata.py`
- Test: `tests/test_sub_metadata.py` (новый)

**Step 1: Написать падающие тесты**

Создать файл `tests/test_sub_metadata.py`:

```python
"""Метаданные подписки: заголовки ответа и строки `#key: value` в теле."""

import base64

import pytest

from src.sub.metadata import (
    SubscriptionMetadata,
    SubscriptionUserInfo,
    decode_value,
    metadata_from_body,
    metadata_from_headers,
    parse_body_line,
    read_metadata,
)


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


# --- subscription-userinfo ----------------------------------------------------


def test_user_info_is_parsed_from_the_header_string():
    info = SubscriptionUserInfo.from_header(
        "upload=1024; download=2048; total=10737418240; expire=1767225600"
    )

    assert info == SubscriptionUserInfo(
        upload=1024, download=2048, total=10737418240, expire=1767225600
    )
    assert info.used == 3072
    assert not info.is_unlimited


def test_user_info_parsing_is_lenient():
    info = SubscriptionUserInfo.from_header("upload=abc;;download = 5 ;garbage;total=;expire=7")

    assert info == SubscriptionUserInfo(upload=0, download=5, total=0, expire=7)
    assert info.is_unlimited


@pytest.mark.parametrize("header", ["", "   ", "nothing useful", None])
def test_user_info_without_known_keys_is_absent(header):
    assert SubscriptionUserInfo.from_header(header) is None


def test_user_info_round_trips_through_its_header_form():
    info = SubscriptionUserInfo(upload=1, download=2, total=3, expire=4)

    assert info.to_header() == "upload=1; download=2; total=3; expire=4"
    assert SubscriptionUserInfo.from_header(info.to_header()) == info


# --- base64: ------------------------------------------------------------------


def test_base64_prefix_is_decoded_for_any_value():
    assert decode_value(f"base64:{b64('Моя подписка')}") == "Моя подписка"
    assert decode_value(f"BASE64: {b64('Моя подписка')}") == "Моя подписка"


def test_value_without_the_prefix_is_left_alone():
    encoded = b64("Моя подписка")

    assert decode_value(encoded) == encoded


def test_lenient_mode_decodes_without_the_prefix():
    """announce исторически приходит в base64 и без префикса."""
    assert decode_value(b64("Техработы до 12:00"), lenient_base64=True) == "Техработы до 12:00"


@pytest.mark.parametrize("plain", ["Техработы до 12:00", "Maintenance", "News", "hello world"])
def test_lenient_mode_keeps_plain_text(plain):
    assert decode_value(plain, lenient_base64=True) == plain


def test_url_safe_alphabet_is_understood():
    text = "??>>??>>"  # в стандартном алфавите даёт `/` и `+`
    url_safe = base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")
    assert "-" in url_safe or "_" in url_safe

    assert decode_value(f"base64:{url_safe}") == text


def test_broken_base64_keeps_the_raw_value():
    assert decode_value("base64:%%%") == "base64:%%%"
    assert decode_value("base64:" + base64.b64encode(b"\xff\xfe\xfd").decode()) == (
        "base64:" + base64.b64encode(b"\xff\xfe\xfd").decode()
    )


# --- заголовки ----------------------------------------------------------------


def test_headers_are_read_case_insensitively():
    metadata = metadata_from_headers(
        {
            "Subscription-Userinfo": "upload=1; download=2; total=3; expire=4",
            "Profile-Update-Interval": "12",
            "Profile-Title": f"base64:{b64('Быстрый VPN')}",
            "Support-URL": "https://t.me/provider_support",
            "Profile-Web-Page-Url": "https://provider.example/account",
            "Announce": b64("Техработы до 12:00"),
            "Content-Type": "text/plain",
        }
    )

    assert metadata == SubscriptionMetadata(
        user_info=SubscriptionUserInfo(upload=1, download=2, total=3, expire=4),
        update_interval_hours=12,
        title="Быстрый VPN",
        support_url="https://t.me/provider_support",
        web_page_url="https://provider.example/account",
        announce="Техработы до 12:00",
    )


def test_missing_headers_give_empty_metadata():
    assert metadata_from_headers({}) == SubscriptionMetadata()
    assert metadata_from_headers(None) == SubscriptionMetadata()


@pytest.mark.parametrize("value", ["abc", "-5", "", "1.5"])
def test_bad_update_interval_is_zero(value):
    assert metadata_from_headers({"profile-update-interval": value}).update_interval_hours == 0


def test_title_is_a_single_short_line():
    """Заголовок идёт в список и в уведомления: без переводов строк, не длиннее 64."""
    metadata = metadata_from_headers({"profile-title": "My\r\nVPN\x00 " + "x" * 100})

    assert "\n" not in metadata.title
    assert "\x00" not in metadata.title
    assert metadata.title.startswith("MyVPN")
    assert len(metadata.title) == 64


def test_security_related_keys_are_not_recognised():
    """Провайдер не должен управлять настройками клиента через подписку."""
    metadata = metadata_from_headers({"hide-settings": "1", "routing": "happ://routing/add/x"})

    assert metadata == SubscriptionMetadata()


# --- тело ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("#profile-title: Мой VPN", ("profile-title", "Мой VPN")),
        ("#  Profile-Title :  Мой VPN  ", ("profile-title", "Мой VPN")),
        ("#support-url: https://t.me/x", ("support-url", "https://t.me/x")),
        ("# обычный комментарий", None),
        ("#hide-settings: 1", None),
        ("vless://uuid@host:443#name", None),
        ("", None),
    ],
)
def test_body_line(line, expected):
    assert parse_body_line(line) == expected


def test_body_metadata_is_read_from_plain_text():
    body = "#profile-title: Мой VPN\n#profile-update-interval: 6\nvless://uuid@host:443#name\n"

    metadata = metadata_from_body(body)

    assert metadata.title == "Мой VPN"
    assert metadata.update_interval_hours == 6


def test_body_metadata_is_read_from_inside_a_base64_body():
    body = b64("#announce: Техработы\n#support-url: https://t.me/x\nvless://uuid@host:443#name\n")

    metadata = metadata_from_body(body)

    assert metadata.announce == "Техработы"
    assert metadata.support_url == "https://t.me/x"


def test_json_body_has_no_metadata():
    assert metadata_from_body('{"outbounds": []}') == SubscriptionMetadata()


# --- приоритет ----------------------------------------------------------------


def test_body_values_override_headers():
    """CDN режет нестандартные заголовки, а тело провайдер контролирует целиком."""
    headers = {"profile-title": "Из заголовка", "support-url": "https://t.me/from_header"}
    body = "#profile-title: Из тела\nvless://uuid@host:443#name"

    metadata = read_metadata(headers, body)

    assert metadata.title == "Из тела"
    assert metadata.support_url == "https://t.me/from_header"
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_sub_metadata.py -q`
Expected: ошибка сборки `No module named 'src.sub.metadata'`.

**Step 3: Реализовать**

Создать файл `src/sub/metadata.py`:

```python
"""Метаданные подписки: заголовки ответа и строки ``#key: value`` в теле.

Берём только косметику и ссылки. Ключи, которыми провайдер управлял бы
настройками клиента (``hide-settings``, ``routing``, mux, per-app), сознательно
не распознаются.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields

from src.fmt.parsers import decode_base64

KEY_USERINFO = "subscription-userinfo"
KEY_UPDATE_INTERVAL = "profile-update-interval"
KEY_ANNOUNCE = "announce"
KEY_SUPPORT_URL = "support-url"
KEY_PROFILE_TITLE = "profile-title"
KEY_WEB_PAGE_URL = "profile-web-page-url"

KNOWN_KEYS = frozenset(
    {
        KEY_USERINFO,
        KEY_UPDATE_INTERVAL,
        KEY_ANNOUNCE,
        KEY_SUPPORT_URL,
        KEY_PROFILE_TITLE,
        KEY_WEB_PAGE_URL,
    }
)

MAX_TITLE_LENGTH = 64

_BASE64_PREFIX = "base64:"
_BODY_LINE = re.compile(r"^#\s*([A-Za-z0-9-]+)\s*:\s*(.*)$")
_BASE64_PAYLOAD = re.compile(r"^[A-Za-z0-9+/_-]+={0,2}$")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# В декодированном тексте допустимы только перевод строки и табуляция: прочие
# управляющие символы означают, что декодировали не base64, а обычное слово.
_BINARY_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_USERINFO_FIELDS = ("upload", "download", "total", "expire")


@dataclass(frozen=True)
class SubscriptionUserInfo:
    """Трафик и срок из ``subscription-userinfo``: байты и unix-время."""

    upload: int = 0
    download: int = 0
    total: int = 0
    expire: int = 0

    @classmethod
    def from_header(cls, header: str | None) -> SubscriptionUserInfo | None:
        """Parse ``upload=N; download=N; total=N; expire=N``; None when nothing is known."""
        values: dict[str, int] = {}
        for part in (header or "").split(";"):
            key, separator, value = part.partition("=")
            key = key.strip().lower()
            if not separator or key not in _USERINFO_FIELDS:
                continue
            try:
                values[key] = max(int(value.strip()), 0)
            except ValueError:
                values[key] = 0
        return cls(**values) if values else None

    def to_header(self) -> str:
        return "; ".join(f"{name}={getattr(self, name)}" for name in _USERINFO_FIELDS)

    @property
    def used(self) -> int:
        return self.upload + self.download

    @property
    def is_unlimited(self) -> bool:
        return self.total == 0


@dataclass(frozen=True)
class SubscriptionMetadata:
    """Всё, что провайдер сообщил о подписке помимо списка серверов."""

    user_info: SubscriptionUserInfo | None = None
    update_interval_hours: int = 0  # только для показа: фонового обновления нет
    announce: str = ""
    support_url: str = ""
    title: str = ""
    web_page_url: str = ""

    def overridden_by(self, body: SubscriptionMetadata) -> SubscriptionMetadata:
        """Values from the body win over headers; empty ones do not erase anything."""
        merged = {f.name: getattr(body, f.name) or getattr(self, f.name) for f in fields(self)}
        return SubscriptionMetadata(**merged)


def decode_value(raw: str, lenient_base64: bool = False) -> str:
    """Decode a ``base64:`` value; with ``lenient_base64`` the prefix is optional.

    Нестрогий режим нужен только для ``announce``: он исторически приходит в
    base64 без префикса. Обычный текст при этом должен остаться собой, поэтому
    результат принимается, только если это корректный UTF-8 без управляющих
    символов.
    """
    has_prefix = raw[: len(_BASE64_PREFIX)].lower() == _BASE64_PREFIX
    if not has_prefix and not lenient_base64:
        return raw

    payload = (raw[len(_BASE64_PREFIX) :] if has_prefix else raw).strip()
    if not _BASE64_PAYLOAD.match(payload):
        return raw

    payload = payload.rstrip("=")
    payload += "=" * (-len(payload) % 4)
    try:
        if "+" in payload or "/" in payload:
            decoded = base64.b64decode(payload, validate=True)
        else:
            decoded = base64.urlsafe_b64decode(payload)
        text = decoded.decode("utf-8")
    except (binascii.Error, ValueError):
        return raw

    if not text or _BINARY_CHARS.search(text):
        return raw
    return text


def _sanitize_title(raw: str) -> str:
    return _CONTROL_CHARS.sub("", raw).strip()[:MAX_TITLE_LENGTH]


def _parse_interval(raw: str) -> int:
    try:
        return max(int(raw), 0)
    except ValueError:
        return 0


def parse_metadata(values: Mapping[str, str]) -> SubscriptionMetadata:
    """Build metadata from ``lower-case key -> raw value`` pairs."""

    def text(key: str) -> str:
        raw = values.get(key)
        if not isinstance(raw, str):
            return ""
        return decode_value(raw.strip(), lenient_base64=key == KEY_ANNOUNCE).strip()

    return SubscriptionMetadata(
        user_info=SubscriptionUserInfo.from_header(text(KEY_USERINFO)),
        update_interval_hours=_parse_interval(text(KEY_UPDATE_INTERVAL)),
        announce=text(KEY_ANNOUNCE),
        support_url=text(KEY_SUPPORT_URL),
        title=_sanitize_title(text(KEY_PROFILE_TITLE)),
        web_page_url=text(KEY_WEB_PAGE_URL),
    )


def parse_body_line(line: str) -> tuple[str, str] | None:
    """Return ``(key, value)`` for a ``#key: value`` line with a known key."""
    match = _BODY_LINE.match(line.strip())
    if match is None:
        return None
    key = match.group(1).lower()
    if key not in KNOWN_KEYS:
        return None
    return key, match.group(2).strip()


def metadata_from_headers(headers: Mapping[str, str] | None) -> SubscriptionMetadata:
    """Read metadata from response headers (names are case-insensitive)."""
    values: dict[str, str] = {}
    try:
        items = list((headers or {}).items())
    except (AttributeError, TypeError):
        # Ответ без настоящих заголовков (заглушка в тестах).
        items = []
    for name, value in items:
        key = str(name).lower()
        if key in KNOWN_KEYS and isinstance(value, str):
            values[key] = value
    return parse_metadata(values)


def metadata_from_body(content: str) -> SubscriptionMetadata:
    """Read ``#key: value`` lines, looking inside a base64 body as well."""
    text = decode_base64(content.strip()) or content
    values: dict[str, str] = {}
    for line in text.split("\n"):
        parsed = parse_body_line(line)
        if parsed is not None:
            values.setdefault(*parsed)
    return parse_metadata(values)


def read_metadata(headers: Mapping[str, str] | None, content: str) -> SubscriptionMetadata:
    """Headers overridden by the body: the body is what the provider fully controls."""
    return metadata_from_headers(headers).overridden_by(metadata_from_body(content))
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_sub_metadata.py -q`
Expected: 35 passed.

**Step 5: Commit**

```bash
git add src/sub/metadata.py tests/test_sub_metadata.py
git commit -m "feat(sub): разбирать метаданные подписки из заголовков и тела"
```

---

### Task 6: Сохранять метаданные в группе (S2, часть 2)

`fetch` продолжает возвращать текст — на него опираются существующие тесты.
Заголовки отдаёт новый `fetch_response`. `update` разбирает метаданные и кладёт
их в `ProfileGroup`.

Правила сохранения (`apply_metadata`):

- Метаданные сохраняются **до** проверки списка серверов. Истёкшая подписка
  отдаёт ноль серверов, но срок и объявление в ответе есть — их и нужно
  показать.
- Пустое значение не стирает сохранённое. Исключение — `announce`: это
  сообщение «на сейчас» (см. «Принятые решения», п. 5).
- `profile-web-page-url` сохраняется только с `https` и хостом,
  `support-url` — `http`, `https` или `tg`. Фильтр стоит и здесь, и при показе:
  в файле профилей не должно лежать то, что приложение не откроет.
- `profile-title` переименовывает группу, только если её имя всё ещё равно
  хосту адреса. После первого применения имя уже не хост, и следующая смена
  title у провайдера группу не переименует — так же в Android.

**Files:**
- Modify: `src/db/profiles.py` (`ProfileGroup`, ~стр. 44–52)
- Modify: `src/sub/metadata.py` (импорты, конец файла)
- Modify: `src/sub/updater.py` (`FetchedSubscription`, `fetch_response`, `_response_headers`, `update`)
- Test: `tests/test_sub_metadata.py`, `tests/test_sub_updater.py`

**Step 1: Написать падающие тесты**

```diff
--- a/tests/test_sub_metadata.py
+++ b/tests/test_sub_metadata.py
@@ -198,3 +198,119 @@ def test_body_values_override_headers():
 
     assert metadata.title == "Из тела"
     assert metadata.support_url == "https://t.me/from_header"
+
+
+# --- применение к группе ------------------------------------------------------
+
+
+def _group(name: str = "provider.example", url: str = "https://provider.example/sub/token"):
+    from src.db.profiles import ProfileGroup
+
+    return ProfileGroup(id=1, name=name, is_subscription=True, subscription_url=url)
+
+
+@pytest.mark.parametrize(
+    ("url", "expected"),
+    [
+        ("https://provider.example/sub/token", "provider.example"),
+        ("http://provider.example:8443/sub", "provider.example"),
+        ("not a url", "not a url"),
+        ("", ""),
+    ],
+)
+def test_default_subscription_name_is_the_host(url, expected):
+    from src.sub.metadata import default_subscription_name
+
+    assert default_subscription_name(url) == expected
+
+
+def test_metadata_is_stored_on_the_group():
+    from src.sub.metadata import apply_metadata
+
+    group = _group()
+    apply_metadata(
+        group,
+        SubscriptionMetadata(
+            user_info=SubscriptionUserInfo(upload=1, download=2, total=3, expire=4),
+            update_interval_hours=12,
+            announce="Техработы",
+            support_url="tg://resolve?domain=provider",
+            web_page_url="https://provider.example/account",
+        ),
+    )
+
+    assert group.sub_user_info == "upload=1; download=2; total=3; expire=4"
+    assert group.sub_update_interval == 12
+    assert group.sub_announce == "Техработы"
+    assert group.sub_support_url == "tg://resolve?domain=provider"
+    assert group.sub_web_page_url == "https://provider.example/account"
+
+
+def test_title_renames_a_group_still_named_after_the_host():
+    from src.sub.metadata import apply_metadata
+
+    group = _group(name="provider.example")
+    apply_metadata(group, SubscriptionMetadata(title="Быстрый VPN"))
+
+    assert group.name == "Быстрый VPN"
+
+
+def test_title_does_not_overwrite_a_name_chosen_by_the_user():
+    from src.sub.metadata import apply_metadata
+
+    group = _group(name="Рабочая")
+    apply_metadata(group, SubscriptionMetadata(title="Быстрый VPN"))
+
+    assert group.name == "Рабочая"
+
+
+def test_missing_values_keep_the_last_known_ones():
+    """Заголовки режет CDN: один ответ без них не должен стирать остаток трафика."""
+    from src.sub.metadata import apply_metadata
+
+    group = _group()
+    group.sub_user_info = "upload=1; download=2; total=3; expire=4"
+    group.sub_update_interval = 12
+    group.sub_support_url = "https://t.me/x"
+    group.sub_web_page_url = "https://provider.example/account"
+
+    apply_metadata(group, SubscriptionMetadata())
+
+    assert group.sub_user_info == "upload=1; download=2; total=3; expire=4"
+    assert group.sub_update_interval == 12
+    assert group.sub_support_url == "https://t.me/x"
+    assert group.sub_web_page_url == "https://provider.example/account"
+
+
+def test_announce_disappears_when_the_provider_removes_it():
+    """Объявление — сообщение «на сейчас»: вчерашние техработы показывать незачем."""
+    from src.sub.metadata import apply_metadata
+
+    group = _group()
+    group.sub_announce = "Техработы до 12:00"
+
+    apply_metadata(group, SubscriptionMetadata())
+
+    assert group.sub_announce == ""
+
+
+@pytest.mark.parametrize(
+    "url", ["http://provider.example/account", "javascript:alert(1)", "https://", "file:///etc"]
+)
+def test_web_page_link_must_be_https(url):
+    from src.sub.metadata import apply_metadata
+
+    group = _group()
+    apply_metadata(group, SubscriptionMetadata(web_page_url=url))
+
+    assert group.sub_web_page_url == ""
+
+
+@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd", "ftp://x", "t.me/x"])
+def test_support_link_must_be_http_or_telegram(url):
+    from src.sub.metadata import apply_metadata
+
+    group = _group()
+    apply_metadata(group, SubscriptionMetadata(support_url=url))
+
+    assert group.sub_support_url == ""
```

```diff
--- a/tests/test_sub_updater.py
+++ b/tests/test_sub_updater.py
@@ -276,3 +276,64 @@ def test_an_empty_response_does_not_count_as_a_refresh(tmp_path):
         updater.update("http://example.com/sub", group_id=group.id)
 
     assert group.last_updated == 1_700_000_000
+
+
+# --- Метаданные ---------------------------------------------------------------
+
+
+def _response_with_headers(text: str, headers: dict[str, str]) -> Mock:
+    response = _text_response(text)
+    response.headers = headers
+    response.content = text.encode("utf-8")
+    response.encoding = None
+    return response
+
+
+def test_update_saves_what_the_provider_says_about_the_subscription(tmp_path):
+    profiles, group = _subscription(tmp_path)
+    group.subscription_url = "https://provider.example/sub/token"
+    group.name = "provider.example"
+    response = _response_with_headers(
+        f"#announce: Техработы\n{LINK_NL}",
+        {
+            "Subscription-Userinfo": "upload=1; download=2; total=3; expire=4",
+            "Profile-Title": "Быстрый VPN",
+            "Content-Type": "text/plain",
+        },
+    )
+
+    with patch("src.sub.updater.requests.get", return_value=response):
+        SubscriptionUpdater(profiles=profiles).update(group.subscription_url, group_id=group.id)
+
+    assert group.sub_user_info == "upload=1; download=2; total=3; expire=4"
+    assert group.sub_announce == "Техработы"
+    assert group.name == "Быстрый VPN"
+
+
+def test_metadata_is_saved_even_when_the_response_has_no_servers(tmp_path):
+    """Истёкшая подписка отдаёт пустой список, но срок и объявление — в заголовках."""
+    profiles, group = _subscription(tmp_path)
+    response = _response_with_headers(
+        "", {"subscription-userinfo": "upload=5; download=5; total=10; expire=1700000000"}
+    )
+
+    with patch("src.sub.updater.requests.get", return_value=response):
+        SubscriptionUpdater(profiles=profiles).update("http://example.com/sub", group_id=group.id)
+
+    from src.db.profiles import ProfileManager
+
+    reloaded = ProfileManager(profiles_dir=tmp_path)
+    reloaded.load()
+    assert reloaded.get_group(group.id).sub_user_info == (
+        "upload=5; download=5; total=10; expire=1700000000"
+    )
+
+
+def test_fetch_response_returns_the_headers_next_to_the_text():
+    response = _response_with_headers(LINK_NL, {"profile-update-interval": "6"})
+
+    with patch("src.sub.updater.requests.get", return_value=response):
+        fetched = SubscriptionUpdater().fetch_response("http://example.com/sub")
+
+    assert fetched.content == LINK_NL
+    assert fetched.headers["profile-update-interval"] == "6"
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_sub_metadata.py tests/test_sub_updater.py -q`
Expected: 20 failed, 49 passed. В сообщениях —
`cannot import name 'apply_metadata'`, `cannot import name
'default_subscription_name'`, `has no attribute 'fetch_response'`.

**Step 3: Реализовать**

```diff
--- a/src/db/profiles.py
+++ b/src/db/profiles.py
@@ -68,7 +68,12 @@ class ProfileGroup(ConfigBase):
     is_subscription: bool = False
     subscription_url: str = ""
     last_updated: int = 0  # timestamp
-    sub_user_info: str = ""
+    # Метаданные провайдера (src/sub/metadata.py). Все — только для показа.
+    sub_user_info: str = ""  # "upload=N; download=N; total=N; expire=N"
+    sub_update_interval: int = 0  # часы
+    sub_announce: str = ""
+    sub_support_url: str = ""
+    sub_web_page_url: str = ""
 
 
 @dataclass
```

```diff
--- a/src/sub/metadata.py
+++ b/src/sub/metadata.py
@@ -12,9 +12,14 @@ import binascii
 import re
 from collections.abc import Mapping
 from dataclasses import dataclass, fields
+from typing import TYPE_CHECKING
+from urllib.parse import urlsplit
 
 from src.fmt.parsers import decode_base64
 
+if TYPE_CHECKING:
+    from src.db.profiles import ProfileGroup
+
 KEY_USERINFO = "subscription-userinfo"
 KEY_UPDATE_INTERVAL = "profile-update-interval"
 KEY_ANNOUNCE = "announce"
@@ -43,6 +48,7 @@ _CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
 # управляющие символы означают, что декодировали не base64, а обычное слово.
 _BINARY_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
 _USERINFO_FIELDS = ("upload", "download", "total", "expire")
+_SUPPORT_SCHEMES = ("http", "https", "tg")
 
 
 @dataclass(frozen=True)
@@ -200,3 +206,60 @@ def metadata_from_body(content: str) -> SubscriptionMetadata:
 def read_metadata(headers: Mapping[str, str] | None, content: str) -> SubscriptionMetadata:
     """Headers overridden by the body: the body is what the provider fully controls."""
     return metadata_from_headers(headers).overridden_by(metadata_from_body(content))
+
+
+def default_subscription_name(url: str) -> str:
+    """Имя подписки по умолчанию — хост адреса.
+
+    По нему же отличаем «имя никто не задавал» от имени, выбранного
+    пользователем: ``profile-title`` переименовывает только первое.
+    """
+    try:
+        host = urlsplit(url.strip()).hostname
+    except ValueError:
+        host = None
+    return host or url.strip()
+
+
+def _scheme_and_host(url: str) -> tuple[str, str]:
+    try:
+        parts = urlsplit(url.strip())
+        return parts.scheme.lower(), parts.hostname or ""
+    except ValueError:
+        return "", ""
+
+
+def is_safe_web_page_url(url: str) -> bool:
+    """Страница продления открывается в браузере: только https с хостом."""
+    scheme, host = _scheme_and_host(url)
+    return scheme == "https" and bool(host)
+
+
+def is_safe_support_url(url: str) -> bool:
+    """Ссылка поддержки: сайт или Telegram, но не ``javascript:`` и не ``file:``."""
+    scheme, _host = _scheme_and_host(url)
+    return scheme in _SUPPORT_SCHEMES
+
+
+def apply_metadata(group: ProfileGroup, metadata: SubscriptionMetadata) -> None:
+    """Store provider metadata on the subscription group.
+
+    Пустое значение не стирает сохранённое: нестандартные заголовки режет CDN,
+    и один ответ без них не должен обнулять остаток трафика. Исключение —
+    объявление: это сообщение «на сейчас», вчерашнее показывать незачем.
+    """
+    if metadata.user_info is not None:
+        group.sub_user_info = metadata.user_info.to_header()
+    if metadata.update_interval_hours > 0:
+        group.sub_update_interval = metadata.update_interval_hours
+    group.sub_announce = metadata.announce
+    # Ссылки фильтруются и здесь, и при показе: в файле профилей не должно
+    # лежать то, что приложение не откроет.
+    if is_safe_support_url(metadata.support_url):
+        group.sub_support_url = metadata.support_url.strip()
+    if is_safe_web_page_url(metadata.web_page_url):
+        group.sub_web_page_url = metadata.web_page_url.strip()
+
+    title = metadata.title
+    if title and group.name == default_subscription_name(group.subscription_url):
+        group.name = title
```

```diff
--- a/src/sub/updater.py
+++ b/src/sub/updater.py
@@ -2,6 +2,8 @@ from __future__ import annotations
 
 import logging
 import time
+from collections.abc import Mapping
+from dataclasses import dataclass, field
 from typing import TYPE_CHECKING
 
 import requests
@@ -14,6 +16,7 @@ from src.sub.errors import (
     SubscriptionTooLargeError,
     snippet_of,
 )
+from src.sub.metadata import apply_metadata, read_metadata
 
 if TYPE_CHECKING:
     from src.db.profiles import ProfileManager
@@ -21,6 +24,14 @@ if TYPE_CHECKING:
 logger = logging.getLogger("tenga.sub.updater")
 
 
+@dataclass(frozen=True)
+class FetchedSubscription:
+    """Тело ответа и его заголовки: в заголовках провайдер передаёт метаданные."""
+
+    content: str
+    headers: Mapping[str, str] = field(default_factory=dict)
+
+
 class SubscriptionUpdater:
     """Subscription update manager."""
 
@@ -37,6 +48,10 @@ class SubscriptionUpdater:
 
     def fetch(self, url: str) -> str:
         """Fetch subscription content."""
+        return self.fetch_response(url).content
+
+    def fetch_response(self, url: str) -> FetchedSubscription:
+        """Fetch subscription content together with the response headers."""
         headers = {}
 
         if self._config:
@@ -58,7 +73,7 @@ class SubscriptionUpdater:
                 # от гигантского ответа, но не саму загрузку.
                 if len(content) > MAX_RESPONSE_SIZE:
                     raise SubscriptionTooLargeError(len(content))
-                return content
+                return FetchedSubscription(content, self._response_headers(response))
             except requests.RequestException as e:
                 # Повторяем только сетевые сбои: HTTP-код — окончательный ответ
                 # сервера, повтор лишь задержит обновление.
@@ -78,6 +93,12 @@ class SubscriptionUpdater:
         # Недостижимо: последняя попытка либо возвращает результат, либо бросает.
         raise last_error or requests.RequestException("Не удалось загрузить подписку")
 
+    @staticmethod
+    def _response_headers(response: requests.Response) -> Mapping[str, str]:
+        headers = getattr(response, "headers", None)
+        # Заглушки ответов в тестах заголовков не имеют.
+        return headers if isinstance(headers, Mapping) else {}
+
     @classmethod
     def _raise_for_status(cls, response: requests.Response) -> None:
         """Turn an HTTP error into one carrying the start of the response body."""
@@ -142,14 +163,21 @@ class SubscriptionUpdater:
             List of added profiles
         """
 
-        content = self.fetch(url)
+        fetched = self.fetch_response(url)
+        beans = self.parse(fetched.content)
+        if not self._profiles:
+            return beans
+
+        if group_id is None:
+            group_id = self._profiles.current_group_id
+        group = self._profiles.get_group(group_id)
 
-        beans = self.parse(content)
-        # Add to profiles
-        if self._profiles and beans:
-            if group_id is None:
-                group_id = self._profiles.current_group_id
+        # До проверки списка: истёкшая подписка отдаёт ноль серверов, но срок и
+        # объявление провайдера в ответе есть — их и нужно показать.
+        if group is not None:
+            apply_metadata(group, read_metadata(fetched.headers, fetched.content))
 
+        if beans:
             if clear_existing:
                 # Не clear_group + add_profile: так профили получали новые id, и
                 # подключённый профиль, замеры и персональные настройки терялись.
@@ -158,10 +186,10 @@ class SubscriptionUpdater:
                 for bean in beans:
                     self._profiles.add_profile(bean, group_id)
 
-            group = self._profiles.get_group(group_id)
             if group is not None:
                 group.last_updated = int(time.time())
 
+        if beans or group is not None:
             self._profiles.save()
 
         return beans
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest -q`
Expected: `722 passed`.

**Step 5: Commit**

```bash
git add src/db/profiles.py src/sub/metadata.py src/sub/updater.py \
        tests/test_sub_metadata.py tests/test_sub_updater.py
git commit -m "feat(sub): сохранять метаданные провайдера в группе подписки"
```

---

### Task 7: Название подписки по умолчанию — хост

Диалог требует название, поэтому имя группы никогда не равно хосту, и
`profile-title` из задачи 6 не применился бы ни разу. Теперь пустое название
заменяется хостом адреса. GTK-код диалога не меняется: он берёт готовую пару из
`validate_subscription`.

**Files:**
- Modify: `src/ui/logic/forms.py` (`validate_subscription`, ~стр. 55; константа `EMPTY_SUBSCRIPTION_NAME`)
- Test: `tests/test_ui_logic_forms.py`, `tests/test_ui_dialogs_subscription.py` (GTK)

**Step 1: Переписать тесты**

```diff
--- a/tests/test_ui_logic_forms.py
+++ b/tests/test_ui_logic_forms.py
@@ -53,10 +53,11 @@ def test_a_valid_link_reports_the_protocol():
     assert "VLESS" in result.message
 
 
-def test_a_subscription_needs_a_name():
-    result = validate_subscription("", "https://example.com/sub")
-    assert not result.ok
-    assert "название" in result.message.lower()
+def test_a_subscription_without_a_name_is_named_after_the_host():
+    """Имя-хост — признак «имя никто не задавал»: его заменит profile-title провайдера."""
+    result = validate_subscription("  ", "https://provider.example:8443/sub/token")
+    assert result.ok
+    assert result.value == ("provider.example", "https://provider.example:8443/sub/token")
 
 
 def test_a_subscription_needs_a_url():
```

```diff
--- a/tests/test_ui_dialogs_subscription.py
+++ b/tests/test_ui_dialogs_subscription.py
@@ -50,10 +50,11 @@ def test_a_non_http_url_blocks_saving(gtk_ready):
     assert not dialog.save_button.get_sensitive()
 
 
-def test_a_missing_name_blocks_saving(gtk_ready):
+def test_a_missing_name_falls_back_to_the_host(gtk_ready):
     dialog = make_dialog()
     dialog.url_row.set_text("https://e.com/s")
-    assert not dialog.save_button.get_sensitive()
+    assert dialog.save_button.get_sensitive()
+    assert dialog.get_data() == ("e.com", "https://e.com/s")
 
 
 def test_the_hint_explains_a_bad_url(gtk_ready):
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_ui_logic_forms.py -q`
Expected: 1 failed —
`test_a_subscription_without_a_name_is_named_after_the_host` (`assert False`:
форма без названия отвергается).

Run: `gtk_test tests/test_ui_dialogs_subscription.py`
Expected: 1 failed — `test_a_missing_name_falls_back_to_the_host`.

**Step 3: Реализовать**

```diff
--- a/src/ui/logic/forms.py
+++ b/src/ui/logic/forms.py
@@ -13,7 +13,6 @@ from typing import Any
 EMPTY_LINK = "Введите ссылку подключения"
 BAD_LINK = "Не удалось разобрать ссылку"
 EMPTY_GROUP_NAME = "Введите название группы"
-EMPTY_SUBSCRIPTION_NAME = "Введите название подписки"
 EMPTY_SUBSCRIPTION_URL = "Введите URL подписки"
 BAD_SUBSCRIPTION_URL = "URL должен начинаться с http:// или https://"
 
@@ -53,17 +52,26 @@ def validate_profile_link(link: str, *, name: str = "") -> FormResult:
 
 
 def validate_subscription(name: str, url: str) -> FormResult:
-    """Check the name and address of a subscription."""
+    """Check the name and address of a subscription.
+
+    Название необязательно: пустое заменяется хостом адреса. Такое имя —
+    признак «имя никто не задавал», и провайдер вправе заменить его своим
+    ``profile-title``; введённое пользователем он не тронет.
+    """
     clean_name = (name or "").strip()
     clean_url = (url or "").strip()
 
-    if not clean_name:
-        return FormResult(False, EMPTY_SUBSCRIPTION_NAME)
     if not clean_url:
         return FormResult(False, EMPTY_SUBSCRIPTION_URL)
     if not clean_url.startswith(_HTTP_PREFIXES):
         return FormResult(False, BAD_SUBSCRIPTION_URL)
 
+    if not clean_name:
+        # Импорт внутри функции: `src.sub` тянет requests и разбор протоколов.
+        from src.sub.metadata import default_subscription_name
+
+        clean_name = default_subscription_name(clean_url)
+
     return FormResult(True, value=(clean_name, clean_url))
 
 
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_ui_logic_forms.py -q`
Expected: 22 passed.

Run: `gtk_test tests/test_ui_dialogs_subscription.py`
Expected: 13 passed.

**Step 5: Commit**

```bash
git add src/ui/logic/forms.py tests/test_ui_logic_forms.py tests/test_ui_dialogs_subscription.py
git commit -m "feat(ui): называть подписку по хосту, если имя не введено"
```

---

### Task 8: Адрес подписки с амперсандом

Исправление существующей ошибки, отдельным коммитом: следующая задача добавляет
в строку текст от провайдера, и разметка должна быть выключена до неё.

`Adw.ActionRow` трактует заголовок и подзаголовок как разметку Pango. Адрес
вида `https://host/sub?token=a&client=b` разметкой не является: GTK пишет
`Failed to set text … from markup` и оставляет подзаголовок пустым. Свойство
`use-markup` нужно выключить **до** установки текста — в конструкторе порядок
свойств не гарантирован.

**Files:**
- Modify: `src/ui/pages/subscriptions.py` (`_build_row`, ~стр. 91)
- Test: `tests/test_ui_pages_subscriptions.py` (GTK)

**Step 1: Написать падающий тест**

```diff
--- a/tests/test_ui_pages_subscriptions.py
+++ b/tests/test_ui_pages_subscriptions.py
@@ -78,6 +78,15 @@ def test_subtitle_carries_the_full_url(page, data):
     assert long_url in page.get_subtitles()
 
 
+def test_an_address_with_an_ampersand_is_still_shown(page, data):
+    """Подзаголовок строки по умолчанию — разметка Pango: `&` в адресе её ломает."""
+    url = "https://sub.example/list?token=abc&client=tenga"
+    groups, counts = data
+    groups[1].subscription_url = url
+    page.set_data(groups, counts)
+    assert url in page.get_subtitles()
+
+
 def test_update_button_emits_the_group_id(page, data):
     received: list[int] = []
     page.connect("subscription-update", lambda _p, group_id: received.append(group_id))
```

**Step 2: Убедиться, что падает**

Run: `gtk_test tests/test_ui_pages_subscriptions.py`
Expected: 1 failed — `test_an_address_with_an_ampersand_is_still_shown`
(подзаголовок — пустая строка), 12 passed.

**Step 3: Исправить**

```diff
--- a/src/ui/pages/subscriptions.py
+++ b/src/ui/pages/subscriptions.py
@@ -89,7 +89,12 @@ class SubscriptionsPage(Gtk.Box):
         self._stack.set_visible_child_name("list" if self._rows else "empty")
 
     def _build_row(self, row: SubscriptionRow) -> Adw.ActionRow:
-        action_row = Adw.ActionRow(title=row.name, subtitle=row.url)
+        # Разметку выключаем до установки текста: имя и адрес приходят извне, и
+        # `&` в адресе (обычное дело для query-параметров) иначе стирает подзаголовок.
+        action_row = Adw.ActionRow()
+        action_row.set_use_markup(False)
+        action_row.set_title(row.name)
+        action_row.set_subtitle(row.url)
         action_row.set_subtitle_lines(1)
         action_row.set_activatable(True)
         action_row.connect(
```

**Step 4: Убедиться, что проходят**

Run: `gtk_test tests/test_ui_pages_subscriptions.py`
Expected: 13 passed.

**Step 5: Commit**

```bash
git add src/ui/pages/subscriptions.py tests/test_ui_pages_subscriptions.py
git commit -m "fix(ui): показывать адрес подписки с амперсандом"
```

---

### Task 9: Строки для списка подписок (S3, логика)

`SubscriptionRow` получает готовые строки: расход трафика, срок, признак
«истекла», объявление и две ссылки. Всё — в модуле без GTK.

- Трафик: `3.00 GB из 10.00 GB`; при нулевом лимите — `1.00 GB, без лимита`;
  если провайдер ничего не сообщил — пустая строка. Единицы — те же, что на
  странице мониторинга (`format_bytes`).
- Срок: `до 01.12.2026` или `истекла 01.09.2025`; ноль — бессрочная, пусто.
- Ссылки проходят те же фильтры, что при сохранении: файл профилей можно
  поправить руками.
- `now` передаётся параметром, чтобы тесты не зависели от часов.

Заглушки групп в тестах (`FakeGroup`) получают новые поля: строки читаются из
группы напрямую, без `getattr` с запасным значением.

**Files:**
- Modify: `src/ui/logic/subscriptions_view.py` (`SubscriptionRow`, `build_subscription_rows`, новые `format_usage`, `format_expire`)
- Test: `tests/test_ui_logic_subscriptions_view.py`, `tests/test_ui_pages_subscriptions.py` (только `FakeGroup`)

**Step 1: Написать падающие тесты**

```diff
--- a/tests/test_ui_logic_subscriptions_view.py
+++ b/tests/test_ui_logic_subscriptions_view.py
@@ -21,6 +21,10 @@ class FakeGroup:
     is_subscription: bool = True
     subscription_url: str = ""
     last_updated: int = 0
+    sub_user_info: str = ""
+    sub_announce: str = ""
+    sub_support_url: str = ""
+    sub_web_page_url: str = ""
 
 
 @pytest.fixture
@@ -92,6 +96,86 @@ def test_url_is_not_truncated(sample):
     assert rows[0].url == groups[1].subscription_url
 
 
+# --- Метаданные провайдера ----------------------------------------------------
+
+GIB = 1024**3
+NOW = 1_760_000_000  # 09.10.2025
+
+
+def _row(**fields):
+    group = FakeGroup(id=1, name="Основная", subscription_url="https://sub.example/main", **fields)
+    return build_subscription_rows({1: group}, {1: 3}, now=NOW)[0]
+
+
+def test_row_without_metadata_has_no_details():
+    row = _row()
+
+    assert row.details_text == ""
+    assert row.announce == ""
+    assert not row.expired
+
+
+def test_usage_shows_used_and_total():
+    row = _row(sub_user_info=f"upload={GIB}; download={2 * GIB}; total={10 * GIB}; expire=0")
+
+    assert row.usage_text == "3.00 GB из 10.00 GB"
+
+
+def test_unlimited_usage_says_so():
+    row = _row(sub_user_info=f"upload=0; download={GIB}; total=0; expire=0")
+
+    assert row.usage_text == "1.00 GB, без лимита"
+
+
+def test_expiry_in_the_future():
+    expire = NOW + 30 * 86400
+    row = _row(sub_user_info=f"upload=0; download=0; total=0; expire={expire}")
+
+    date = datetime.datetime.fromtimestamp(expire).strftime("%d.%m.%Y")
+    assert row.expire_text == f"до {date}"
+    assert not row.expired
+
+
+def test_expiry_in_the_past_is_flagged():
+    expire = NOW - 86400
+    row = _row(sub_user_info=f"upload=0; download=0; total=0; expire={expire}")
+
+    date = datetime.datetime.fromtimestamp(expire).strftime("%d.%m.%Y")
+    assert row.expire_text == f"истекла {date}"
+    assert row.expired
+
+
+def test_details_join_usage_and_expiry():
+    expire = NOW + 86400
+    row = _row(sub_user_info=f"upload=0; download={GIB}; total={2 * GIB}; expire={expire}")
+
+    assert row.details_text == f"{row.usage_text} · {row.expire_text}"
+
+
+def test_garbage_user_info_is_ignored():
+    assert _row(sub_user_info="what is this").details_text == ""
+
+
+def test_announce_and_links_reach_the_row():
+    row = _row(
+        sub_announce="Техработы до 12:00",
+        sub_support_url="https://t.me/provider",
+        sub_web_page_url="https://provider.example/account",
+    )
+
+    assert row.announce == "Техработы до 12:00"
+    assert row.support_url == "https://t.me/provider"
+    assert row.web_page_url == "https://provider.example/account"
+
+
+def test_unsafe_links_are_not_offered():
+    """Файл профилей можно поправить руками: фильтр стоит и при показе."""
+    row = _row(sub_support_url="javascript:alert(1)", sub_web_page_url="http://provider.example")
+
+    assert row.support_url == ""
+    assert row.web_page_url == ""
+
+
 # --- Сообщение об ошибке обновления -------------------------------------------
 
 
```

```diff
--- a/tests/test_ui_pages_subscriptions.py
+++ b/tests/test_ui_pages_subscriptions.py
@@ -16,6 +16,10 @@ class FakeGroup:
     is_subscription: bool = True
     subscription_url: str = ""
     last_updated: int = 0
+    sub_user_info: str = ""
+    sub_announce: str = ""
+    sub_support_url: str = ""
+    sub_web_page_url: str = ""
 
 
 @pytest.fixture
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_ui_logic_subscriptions_view.py -q`
Expected: 9 failed, 13 passed —
`build_subscription_rows() got an unexpected keyword argument 'now'`.

**Step 3: Реализовать**

```diff
--- a/src/ui/logic/subscriptions_view.py
+++ b/src/ui/logic/subscriptions_view.py
@@ -3,12 +3,16 @@
 from __future__ import annotations
 
 import datetime
+import time
 from collections.abc import Mapping
 from dataclasses import dataclass
 from typing import Any
 
+from src.ui.logic.formatting import format_bytes
+
 NEVER_UPDATED = "Никогда"
 _TIME_FORMAT = "%d.%m.%Y %H:%M"
+_DATE_FORMAT = "%d.%m.%Y"
 
 
 @dataclass(frozen=True)
@@ -20,6 +24,18 @@ class SubscriptionRow:
     url: str
     updated_text: str
     profile_count: int
+    # Метаданные провайдера; пустые строки — провайдер их не сообщил.
+    usage_text: str = ""
+    expire_text: str = ""
+    expired: bool = False
+    announce: str = ""
+    support_url: str = ""
+    web_page_url: str = ""
+
+    @property
+    def details_text(self) -> str:
+        """Usage and expiry on one line."""
+        return " · ".join(part for part in (self.usage_text, self.expire_text) if part)
 
 
 def format_updated(timestamp: int) -> str:
@@ -29,18 +45,43 @@ def format_updated(timestamp: int) -> str:
     return datetime.datetime.fromtimestamp(timestamp).strftime(_TIME_FORMAT)
 
 
+def format_usage(used: int, total: int) -> str:
+    """Render the traffic counter; an unknown one renders as nothing."""
+    if total > 0:
+        return f"{format_bytes(used)} из {format_bytes(total)}"
+    if used > 0:
+        return f"{format_bytes(used)}, без лимита"
+    return ""
+
+
+def format_expire(expire: int, now: int) -> tuple[str, bool]:
+    """Render the expiry date and tell whether it has passed. Zero means "never"."""
+    if expire <= 0:
+        return "", False
+    date = datetime.datetime.fromtimestamp(expire).strftime(_DATE_FORMAT)
+    if expire < now:
+        return f"истекла {date}", True
+    return f"до {date}", False
+
+
 def build_subscription_rows(
     groups: Mapping[int, Any],
     profile_counts: Mapping[int, int],
     *,
     query: str = "",
+    now: int | None = None,
 ) -> list[SubscriptionRow]:
     """Build the subscription list for the given filter.
 
     URL сохраняется целиком: обрезку делает виджет, а фильтр должен искать по
     полному адресу, иначе часть подписок стала бы ненаходимой.
     """
+    # Импорт внутри функции: `src.sub` тянет requests, а модуль нужен при
+    # каждом открытии окна.
+    from src.sub.metadata import SubscriptionUserInfo, is_safe_support_url, is_safe_web_page_url
+
     normalized = query.strip().lower()
+    current_time = int(time.time()) if now is None else now
 
     rows: list[SubscriptionRow] = []
     for group in groups.values():
@@ -57,6 +98,12 @@ def build_subscription_rows(
         ):
             continue
 
+        info = SubscriptionUserInfo.from_header(group.sub_user_info)
+        usage_text = format_usage(info.used, info.total) if info else ""
+        expire_text, expired = format_expire(info.expire, current_time) if info else ("", False)
+        support_url = group.sub_support_url
+        web_page_url = group.sub_web_page_url
+
         rows.append(
             SubscriptionRow(
                 group_id=group.id,
@@ -64,6 +111,12 @@ def build_subscription_rows(
                 url=url,
                 updated_text=updated_text,
                 profile_count=profile_counts.get(group.id, 0),
+                usage_text=usage_text,
+                expire_text=expire_text,
+                expired=expired,
+                announce=group.sub_announce,
+                support_url=support_url if is_safe_support_url(support_url) else "",
+                web_page_url=web_page_url if is_safe_web_page_url(web_page_url) else "",
             )
         )
 
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest -q`
Expected: `731 passed`.

Run: `gtk_test tests/test_ui_pages_subscriptions.py`
Expected: 13 passed.

**Step 5: Commit**

```bash
git add src/ui/logic/subscriptions_view.py tests/test_ui_logic_subscriptions_view.py \
        tests/test_ui_pages_subscriptions.py
git commit -m "feat(ui): готовить для списка подписок трафик, срок и ссылки провайдера"
```

---

### Task 10: Показ метаданных в списке подписок (S3, GTK)

Что меняется в строке подписки:

- под счётчиком «профилей · обновлено» появляется вторая строка — трафик и
  срок; у истёкшей подписки она красная (класс `error`);
- объявление провайдера — кнопка с «i», по нажатию открывается всплывающая
  панель с текстом. Текст — обычная метка, не разметка: его пишет провайдер;
- в меню строки появляются «Страница подписки» и «Поддержка» — только если
  провайдер дал ссылки. «Удалить» остаётся последним.

Ссылки открывает окно (`Gtk.UriLauncher`), и перед открытием проверяет ещё раз.

**Files:**
- Modify: `src/ui/pages/subscriptions.py` (`__init__`, `_rebuild`, `_build_row`, `_menu_model_for`, аксессоры для тестов)
- Modify: `src/ui/window.py` (`_ROW_ACTIONS`, ~стр. 214; новые `_row_open_subscription_*` перед `_on_subscription_edit`, ~стр. 388)
- Test: `tests/test_ui_pages_subscriptions.py`, `tests/test_ui_window.py` (GTK)

**Step 1: Написать падающие тесты**

```diff
--- a/tests/test_ui_pages_subscriptions.py
+++ b/tests/test_ui_pages_subscriptions.py
@@ -141,3 +141,61 @@ def test_the_menu_targets_its_own_row(page, data):
 
     assert first == 1
     assert second == 2
+
+
+# --- метаданные провайдера ---
+
+GIB = 1024**3
+
+
+def test_a_row_without_metadata_has_no_extra_widgets(page, data):
+    page.set_data(*data)
+
+    assert page.get_details_for_test(group_id=1) == ""
+    assert page.get_announce_for_test(group_id=1) == ""
+
+
+def test_usage_and_expiry_are_shown_in_the_row(page, data):
+    groups, counts = data
+    groups[1].sub_user_info = f"upload=0; download={GIB}; total={2 * GIB}; expire=4102444800"
+    page.set_data(groups, counts)
+
+    details = page.get_details_for_test(group_id=1)
+
+    assert "1.00 GB из 2.00 GB" in details
+    assert "до " in details
+    assert not page.is_expired_for_test(group_id=1)
+
+
+def test_an_expired_subscription_is_highlighted(page, data):
+    groups, counts = data
+    groups[1].sub_user_info = "upload=0; download=0; total=0; expire=1000000000"
+    page.set_data(groups, counts)
+
+    assert "истекла" in page.get_details_for_test(group_id=1)
+    assert page.is_expired_for_test(group_id=1)
+
+
+def test_the_announce_is_available_from_the_row(page, data):
+    groups, counts = data
+    groups[1].sub_announce = "Техработы <b>до</b> 12:00 & позже"
+    page.set_data(groups, counts)
+
+    assert page.get_announce_for_test(group_id=1) == "Техработы <b>до</b> 12:00 & позже"
+    assert page.get_announce_for_test(group_id=2) == ""
+
+
+def test_provider_links_extend_the_menu(page, data):
+    groups, counts = data
+    groups[1].sub_web_page_url = "https://provider.example/account"
+    groups[1].sub_support_url = "https://t.me/provider"
+    page.set_data(groups, counts)
+
+    assert page.context_menu_labels_for_test(group_id=1) == [
+        "Обновить",
+        "Редактировать",
+        "Страница подписки",
+        "Поддержка",
+        "Удалить",
+    ]
+    assert page.context_menu_labels_for_test(group_id=2) == ["Обновить", "Редактировать", "Удалить"]
```

```diff
--- a/tests/test_ui_window.py
+++ b/tests/test_ui_window.py
@@ -201,6 +201,51 @@ def test_subscription_update_reaches_the_application(window, adw_app):
     assert updated == [group.id]
 
 
+def _subscription_with_links(adw_app, **links):
+    group = adw_app.context.profiles.add_group("Подписка", is_subscription=True)
+    group.subscription_url = "https://sub.example/list"
+    for name, value in links.items():
+        setattr(group, name, value)
+    return group
+
+
+def test_the_subscription_page_link_is_opened(window, adw_app, monkeypatch):
+    from gi.repository import GLib
+
+    group = _subscription_with_links(adw_app, sub_web_page_url="https://provider.example/account")
+    opened: list[str] = []
+    monkeypatch.setattr(window, "_launch_uri", opened.append)
+
+    window.lookup_action("open-subscription-page").activate(GLib.Variant("i", group.id))
+
+    assert opened == ["https://provider.example/account"]
+
+
+def test_the_support_link_is_opened(window, adw_app, monkeypatch):
+    from gi.repository import GLib
+
+    group = _subscription_with_links(adw_app, sub_support_url="tg://resolve?domain=provider")
+    opened: list[str] = []
+    monkeypatch.setattr(window, "_launch_uri", opened.append)
+
+    window.lookup_action("open-subscription-support").activate(GLib.Variant("i", group.id))
+
+    assert opened == ["tg://resolve?domain=provider"]
+
+
+def test_an_unsafe_link_is_not_opened(window, adw_app, monkeypatch):
+    """profiles.json можно поправить руками: ссылка проверяется и перед открытием."""
+    from gi.repository import GLib
+
+    group = _subscription_with_links(adw_app, sub_web_page_url="file:///etc/passwd")
+    opened: list[str] = []
+    monkeypatch.setattr(window, "_launch_uri", opened.append)
+
+    window.lookup_action("open-subscription-page").activate(GLib.Variant("i", group.id))
+
+    assert opened == []
+
+
 # --- действия строк (этап 3) ---
 
 ROW_ACTIONS = {
@@ -215,6 +260,8 @@ ROW_ACTIONS = {
     "update-subscription",
     "edit-subscription",
     "delete-subscription",
+    "open-subscription-page",
+    "open-subscription-support",
 }
 
 
```

**Step 2: Убедиться, что падают**

Run: `gtk_test tests/test_ui_pages_subscriptions.py tests/test_ui_window.py -k "metadata or usage or expired or announce or link or row_actions"`
Expected: 9 failed, 2 passed. В сообщениях —
`has no attribute 'get_details_for_test'`,
`'NoneType' object has no attribute 'activate'` (действия ещё не
зарегистрированы).

**Step 3: Реализовать**

```diff
--- a/src/ui/pages/subscriptions.py
+++ b/src/ui/pages/subscriptions.py
@@ -35,6 +35,8 @@ class SubscriptionsPage(Gtk.Box):
         self._row_widgets: dict[int, Adw.ActionRow] = {}
         self._update_buttons: dict[int, Gtk.Button] = {}
         self._menu_buttons: dict[int, Gtk.MenuButton] = {}
+        self._details_labels: dict[int, Gtk.Label] = {}
+        self._announce_labels: dict[int, Gtk.Label] = {}
 
         self._build_search_bar()
         self._build_stack()
@@ -80,6 +82,8 @@ class SubscriptionsPage(Gtk.Box):
         self._row_widgets.clear()
         self._update_buttons.clear()
         self._menu_buttons.clear()
+        self._details_labels.clear()
+        self._announce_labels.clear()
 
         self._rows = build_subscription_rows(self._groups, self._counts, query=self._query)
 
@@ -101,10 +105,22 @@ class SubscriptionsPage(Gtk.Box):
             "activated", lambda _row, gid=row.group_id: self.emit("subscription-activated", gid)
         )
 
-        meta = Gtk.Label(label=f"{row.profile_count} · {row.updated_text}")
+        if row.announce:
+            action_row.add_suffix(self._build_announce_button(row))
+
+        meta_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
+        meta = Gtk.Label(label=f"{row.profile_count} · {row.updated_text}", xalign=1.0)
         meta.add_css_class("dim-label")
         meta.add_css_class("caption")
-        action_row.add_suffix(meta)
+        meta_box.append(meta)
+        if row.details_text:
+            details = Gtk.Label(label=row.details_text, xalign=1.0)
+            details.add_css_class("caption")
+            # Истёкшую подписку видно сразу: серверов в ней обычно уже нет.
+            details.add_css_class("error" if row.expired else "dim-label")
+            meta_box.append(details)
+            self._details_labels[row.group_id] = details
+        action_row.add_suffix(meta_box)
 
         button = Gtk.Button(icon_name="view-refresh-symbolic")
         button.set_valign(Gtk.Align.CENTER)
@@ -119,7 +135,7 @@ class SubscriptionsPage(Gtk.Box):
         menu_button.set_valign(Gtk.Align.CENTER)
         menu_button.set_tooltip_text("Действия")
         menu_button.add_css_class("flat")
-        menu_button.set_menu_model(self._menu_model_for(row.group_id))
+        menu_button.set_menu_model(self._menu_model_for(row))
         action_row.add_suffix(menu_button)
 
         self._row_widgets[row.group_id] = action_row
@@ -127,17 +143,43 @@ class SubscriptionsPage(Gtk.Box):
         self._menu_buttons[row.group_id] = menu_button
         return action_row
 
+    def _build_announce_button(self, row: SubscriptionRow) -> Gtk.MenuButton:
+        """A button revealing the provider's announcement in a popover."""
+        # Обычная метка, не разметка: текст объявления пишет провайдер.
+        label = Gtk.Label(label=row.announce, wrap=True, max_width_chars=40, xalign=0.0)
+        label.set_selectable(True)
+        for side in ("top", "bottom", "start", "end"):
+            getattr(label, f"set_margin_{side}")(6)
+
+        popover = Gtk.Popover()
+        popover.set_child(label)
+
+        button = Gtk.MenuButton(icon_name="dialog-information-symbolic")
+        button.set_valign(Gtk.Align.CENTER)
+        button.set_tooltip_text("Объявление провайдера")
+        button.add_css_class("flat")
+        button.set_popover(popover)
+
+        self._announce_labels[row.group_id] = label
+        return button
+
     @staticmethod
-    def _menu_model_for(group_id: int) -> Gio.Menu:
+    def _menu_model_for(row: SubscriptionRow) -> Gio.Menu:
         """Build the menu of one subscription row.
 
         Идентификатор группы вшит в каждое действие: у строк общий набор
         пунктов, и без параметра действие ушло бы в текущее выделение, а не в
         ту подписку, у которой открыли меню.
         """
+        group_id = row.group_id
         menu = Gio.Menu()
         menu.append("Обновить", f"win.update-subscription({group_id})")
         menu.append("Редактировать", f"win.edit-subscription({group_id})")
+        # Ссылки провайдера есть не у каждой подписки: пустой пункт не показываем.
+        if row.web_page_url:
+            menu.append("Страница подписки", f"win.open-subscription-page({group_id})")
+        if row.support_url:
+            menu.append("Поддержка", f"win.open-subscription-support({group_id})")
         menu.append("Удалить", f"win.delete-subscription({group_id})")
         return menu
 
@@ -176,6 +218,18 @@ class SubscriptionsPage(Gtk.Box):
     def get_subtitles(self) -> list[str]:
         return [widget.get_subtitle() for widget in self._row_widgets.values()]
 
+    def get_details_for_test(self, *, group_id: int) -> str:
+        label = self._details_labels.get(group_id)
+        return label.get_text() if label is not None else ""
+
+    def is_expired_for_test(self, *, group_id: int) -> bool:
+        label = self._details_labels.get(group_id)
+        return label is not None and label.has_css_class("error")
+
+    def get_announce_for_test(self, *, group_id: int) -> str:
+        label = self._announce_labels.get(group_id)
+        return label.get_text() if label is not None else ""
+
     def click_update_for_test(self, *, group_id: int) -> None:
         self._update_buttons[group_id].emit("clicked")
 
```

```diff
--- a/src/ui/window.py
+++ b/src/ui/window.py
@@ -224,6 +224,8 @@ class MainWindow(Adw.ApplicationWindow):
         "update-subscription",
         "edit-subscription",
         "delete-subscription",
+        "open-subscription-page",
+        "open-subscription-support",
     )
 
     def _register_row_actions(self) -> None:
@@ -385,6 +387,32 @@ class MainWindow(Adw.ApplicationWindow):
     def _row_delete_subscription(self, group_id: int) -> None:
         self._row_delete_group(group_id)
 
+    def _row_open_subscription_page(self, group_id: int) -> None:
+        from src.sub.metadata import is_safe_web_page_url
+
+        self._open_subscription_link(group_id, "sub_web_page_url", is_safe_web_page_url)
+
+    def _row_open_subscription_support(self, group_id: int) -> None:
+        from src.sub.metadata import is_safe_support_url
+
+        self._open_subscription_link(group_id, "sub_support_url", is_safe_support_url)
+
+    def _open_subscription_link(self, group_id: int, field: str, is_safe) -> None:
+        """Open a link the provider attached to the subscription.
+
+        Проверка повторяется перед самым открытием: ссылка лежит в файле
+        профилей, который можно изменить в обход приложения.
+        """
+        group = self._context.profiles.get_group(group_id)
+        url = getattr(group, field, "") if group is not None else ""
+        if not url or not is_safe(url):
+            self.toast("Ссылка недоступна")
+            return
+        self._launch_uri(url)
+
+    def _launch_uri(self, uri: str) -> None:
+        Gtk.UriLauncher.new(uri).launch(self, None, None)
+
     def _on_subscription_edit(self, _page, group_id: int) -> None:
         self._row_edit_subscription(group_id)
 
```

**Step 4: Убедиться, что проходят**

Run: `gtk_test tests/test_ui_pages_subscriptions.py`
Expected: 18 passed.

Run: `gtk_test tests/test_ui_window.py --deselect tests/test_ui_window.py::test_narrow_window_moves_the_switcher_down --deselect tests/test_ui_window.py::test_default_size_comes_from_saved_geometry`
Expected: 23 passed.

**Step 5: Commit**

```bash
git add src/ui/pages/subscriptions.py src/ui/window.py \
        tests/test_ui_pages_subscriptions.py tests/test_ui_window.py
git commit -m "feat(ui): показывать трафик, срок, объявление и ссылки провайдера в списке подписок"
```

---

### Task 11: Загрузка через работающий прокси с откатом (S4)

Сервер подписки часто заблокирован так же, как и всё остальное. В режиме
системного прокси `requests` настроек рабочего стола не видит (он читает только
переменные окружения) и ходит напрямую.

Порядок (как `SubscriptionFetcher` в Android):

1. Профиль подключён в режиме системного прокси — сначала через локальный
   HTTP-inbound (`inbound_socks_port + 1`), со всеми повторами.
2. Сетевая **или HTTP**-ошибка через прокси — пробуем напрямую. HTTP-ошибка
   через прокси не окончательна: провайдер может не отдавать подписку адресу
   выхода (403 по стране).
3. Обе попытки не удались: если через прокси был ответ сервера, а напрямую —
   обрыв, показываем ответ сервера: он объясняет больше.
4. Слишком большой ответ через прокси — окончательный.
5. Не подключено или режим TUN — только напрямую, как раньше.

`SubscriptionUpdater` не знает про состояние подключения: он получает функцию
`proxy_url`, которая возвращает адрес прокси или `None`. Решение принимает
`src/sub/route.py`.

Заодно из журнала уходит текст ошибок `requests` (в нём адрес с токеном) —
пишется только тип ошибки.

**Ограничения, о которых нужно знать:**

- Запрос через локальный inbound подчиняется правилам маршрутизации
  пользователя. Если сервер подписки попал в direct-список или выбран режим
  «напрямую, кроме списка», запрос уйдёт напрямую уже из xray. Выделенный
  inbound с правилом «всегда в прокси» — задача P4 этапа 4; когда он появится,
  `local_proxy_url` стоит переключить на него.
- Мёртвый прокси стоит трёх попыток по 30 секунд до отката. Так же в Android.

Поле `sub_use_proxy` удаляется (см. «Принятые решения», п. 2). Старые
`settings.json` с этим ключом читаются без ошибок: `ConfigBase.from_dict`
пропускает неизвестные ключи.

**Files:**
- Create: `src/sub/route.py`
- Modify: `src/sub/updater.py` (`__init__`, `fetch_response`, новый `_fetch_with_retries`, `update_subscription`)
- Modify: `src/db/data_store.py` (удалить `sub_use_proxy`)
- Modify: `src/ui/application.py` (`_default_subscription_updater`, ~стр. 565)
- Test: `tests/test_sub_route.py` (новый), `tests/test_ui_application.py` (GTK)

**Step 1: Написать падающие тесты**

Создать файл `tests/test_sub_route.py`:

```python
"""Маршрут загрузки подписки: сначала через работающий прокси, потом напрямую."""

from unittest.mock import Mock, patch

import pytest
import requests

from src.core.context import ProxyState
from src.db.config import ProxyMode
from src.db.data_store import DataStore
from src.sub.errors import MAX_RESPONSE_SIZE, SubscriptionHttpError, SubscriptionTooLargeError
from src.sub.route import local_proxy_url
from src.sub.updater import SubscriptionUpdater

PROXY = "http://127.0.0.1:2081"
URL = "https://provider.example/sub/secret-token"


def _ok(text: str = "ok") -> Mock:
    response = Mock()
    response.text = text
    response.raise_for_status = Mock()
    return response


def _http_error(status: int, body: str = "") -> Mock:
    response = Mock()
    response.status_code = status
    response.text = body
    response.raise_for_status = Mock(side_effect=requests.HTTPError(str(status)))
    return response


def _via_proxy(call) -> bool:
    return "proxies" in call.kwargs


# --- когда есть через что качать ----------------------------------------------


def _state(running: bool, mode: str) -> ProxyState:
    state = ProxyState()
    if running:
        state.set_running(1, mode=mode)
    return state


def test_no_local_proxy_while_disconnected():
    assert local_proxy_url(DataStore(), _state(False, ProxyMode.SYSTEM_PROXY)) is None


def test_no_local_proxy_in_tun_mode():
    """В TUN запросы приложения и так идут через туннель, а HTTP-inbound не поднят."""
    assert local_proxy_url(DataStore(), _state(True, ProxyMode.TUN)) is None


def test_local_proxy_is_the_http_inbound_next_to_socks():
    assert local_proxy_url(DataStore(), _state(True, ProxyMode.SYSTEM_PROXY)) == PROXY


def test_local_proxy_follows_the_configured_address_and_port():
    config = DataStore(inbound_address="127.0.0.2", inbound_socks_port=3000)

    assert local_proxy_url(config, _state(True, ProxyMode.SYSTEM_PROXY)) == "http://127.0.0.2:3001"


@pytest.mark.parametrize("address", ["0.0.0.0", "::", ""])
def test_wildcard_listen_address_is_reached_through_loopback(address):
    config = DataStore(inbound_address=address)

    assert local_proxy_url(config, _state(True, ProxyMode.SYSTEM_PROXY)) == PROXY


# --- порядок маршрутов --------------------------------------------------------


def test_without_a_proxy_the_request_goes_directly():
    with patch("src.sub.updater.requests.get", return_value=_ok()) as mock_get:
        SubscriptionUpdater(proxy_url=lambda: None).fetch(URL)

    assert mock_get.call_count == 1
    assert not _via_proxy(mock_get.call_args)


def test_a_connected_proxy_is_tried_first():
    with patch("src.sub.updater.requests.get", return_value=_ok("via proxy")) as mock_get:
        result = SubscriptionUpdater(proxy_url=lambda: PROXY).fetch(URL)

    assert result == "via proxy"
    assert mock_get.call_count == 1
    assert mock_get.call_args.kwargs["proxies"] == {"http": PROXY, "https": PROXY}


def test_network_failure_through_the_proxy_falls_back_to_direct():
    def get(_url, **kwargs):
        if "proxies" in kwargs:
            raise requests.ConnectionError("proxy is dead")
        return _ok("direct")

    with (
        patch("src.sub.updater.requests.get", side_effect=get) as mock_get,
        patch("src.sub.updater.time.sleep"),
    ):
        result = SubscriptionUpdater(proxy_url=lambda: PROXY).fetch(URL)

    assert result == "direct"
    routes = [_via_proxy(call) for call in mock_get.call_args_list]
    assert routes == [True] * SubscriptionUpdater.MAX_ATTEMPTS + [False]


def test_http_error_through_the_proxy_is_not_final():
    """Провайдер может не отдавать подписку адресу выхода прокси (403 по стране)."""
    with patch("src.sub.updater.requests.get") as mock_get:
        mock_get.side_effect = [_http_error(403, "country code: US"), _ok("direct")]
        result = SubscriptionUpdater(proxy_url=lambda: PROXY).fetch(URL)

    assert result == "direct"
    assert [_via_proxy(call) for call in mock_get.call_args_list] == [True, False]


def test_the_servers_answer_beats_a_dropped_direct_connection():
    """Ответ сервера через прокси объясняет больше, чем обрыв напрямую."""

    def get(_url, **kwargs):
        if "proxies" in kwargs:
            return _http_error(403, "Device limit reached")
        raise requests.ConnectionError("blocked")

    with (
        patch("src.sub.updater.requests.get", side_effect=get),
        patch("src.sub.updater.time.sleep"),
        pytest.raises(SubscriptionHttpError) as caught,
    ):
        SubscriptionUpdater(proxy_url=lambda: PROXY).fetch(URL)

    assert caught.value.body_snippet == "Device limit reached"


def test_two_http_errors_report_the_direct_one():
    answers = [_http_error(403), _http_error(404)]
    with (
        patch("src.sub.updater.requests.get", side_effect=answers),
        pytest.raises(SubscriptionHttpError) as caught,
    ):
        SubscriptionUpdater(proxy_url=lambda: PROXY).fetch(URL)

    assert caught.value.status_code == 404


def test_an_oversized_response_through_the_proxy_is_final():
    huge = _ok("x" * (MAX_RESPONSE_SIZE + 1))
    with (
        patch("src.sub.updater.requests.get", return_value=huge) as mock_get,
        pytest.raises(SubscriptionTooLargeError),
    ):
        SubscriptionUpdater(proxy_url=lambda: PROXY).fetch(URL)

    assert mock_get.call_count == 1


def test_the_subscription_address_never_reaches_the_log(caplog):
    """В адресе — токен пользователя, а текст ошибок requests содержит URL целиком."""

    def get(url, **kwargs):
        if "proxies" in kwargs:
            raise requests.ConnectionError(f"Max retries exceeded with url: {url}")
        return _ok()

    with (
        patch("src.sub.updater.requests.get", side_effect=get),
        patch("src.sub.updater.time.sleep"),
        caplog.at_level("DEBUG", logger="tenga.sub.updater"),
    ):
        SubscriptionUpdater(proxy_url=lambda: PROXY).fetch(URL)

    assert caplog.records
    assert "secret-token" not in caplog.text


# --- настройки ----------------------------------------------------------------


def test_the_dead_sub_use_proxy_setting_is_gone():
    """Поле осталось от NekoRay и нигде не читалось: маршрут выбирается сам."""
    assert not hasattr(DataStore(), "sub_use_proxy")
    assert DataStore.from_dict({"sub_use_proxy": False, "inbound_socks_port": 3000}) == DataStore(
        inbound_socks_port=3000
    )
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_sub_route.py -q`
Expected: ошибка сборки `No module named 'src.sub.route'`.

**Step 3: Реализовать маршрут**

Создать файл `src/sub/route.py`:

```python
"""Через что загружать подписку."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.proxy_mode import normalize_proxy_mode
from src.db.config import ProxyMode

if TYPE_CHECKING:
    from src.core.context import ProxyState
    from src.db.data_store import DataStore

_WILDCARD_ADDRESSES = ("", "0.0.0.0", "::")


def local_proxy_url(config: DataStore, proxy_state: ProxyState) -> str | None:
    """Адрес локального HTTP-inbound, если подписку стоит качать через него.

    Сервер подписки часто заблокирован так же, как всё остальное. В режиме
    системного прокси ``requests`` настроек рабочего стола не видит и ходит
    напрямую, поэтому прокси ему нужно указать явно. В TUN запросы приложения
    и так идут через туннель — там ничего делать не нужно.
    """
    if not proxy_state.is_running:
        return None
    if normalize_proxy_mode(proxy_state.started_mode) != ProxyMode.SYSTEM_PROXY:
        return None

    address = (config.inbound_address or "").strip()
    if address in _WILDCARD_ADDRESSES:
        address = "127.0.0.1"
    # HTTP-inbound стоит на следующем порту после SOCKS (src/core/proxy_mode.py).
    return f"http://{address}:{config.inbound_socks_port + 1}"
```

```diff
--- a/src/sub/updater.py
+++ b/src/sub/updater.py
@@ -2,7 +2,7 @@ from __future__ import annotations
 
 import logging
 import time
-from collections.abc import Mapping
+from collections.abc import Callable, Mapping
 from dataclasses import dataclass, field
 from typing import TYPE_CHECKING
 
@@ -42,9 +42,13 @@ class SubscriptionUpdater:
         self,
         config: DataStore | None = None,
         profiles: ProfileManager | None = None,
+        proxy_url: Callable[[], str | None] | None = None,
     ):
         self._config = config
         self._profiles = profiles
+        # Возвращает адрес локального прокси, через который стоит попробовать
+        # сначала (src/sub/route.py), или None — тогда запрос идёт напрямую.
+        self._proxy_url = proxy_url
 
     def fetch(self, url: str) -> str:
         """Fetch subscription content."""
@@ -63,10 +67,52 @@ class SubscriptionUpdater:
         if self._config and self._config.sub_insecure:
             verify = False
 
+        proxy = self._proxy_url() if self._proxy_url is not None else None
+        if not proxy:
+            return self._fetch_with_retries(url, headers, verify)
+
+        # Сначала через работающий прокси: при подключённом профиле прямой путь
+        # чаще заблокирован, а мёртвая прямая попытка стоит трёх таймаутов.
+        try:
+            return self._fetch_with_retries(
+                url, headers, verify, proxies={"http": proxy, "https": proxy}
+            )
+        except SubscriptionTooLargeError:
+            # Слишком большой ответ окончателен: напрямую придёт то же самое.
+            raise
+        except requests.RequestException as proxy_error:
+            # HTTP-ошибка через прокси не окончательна: провайдер может не
+            # отдавать подписку адресу выхода (403 по стране).
+            logger.warning(
+                "Загрузка подписки через прокси не удалась (%s), пробую напрямую",
+                type(proxy_error).__name__,
+            )
+            try:
+                return self._fetch_with_retries(url, headers, verify)
+            except requests.RequestException as direct_error:
+                # Ответ сервера через прокси объясняет больше, чем обрыв напрямую.
+                if isinstance(proxy_error, SubscriptionHttpError) and not isinstance(
+                    direct_error, SubscriptionHttpError
+                ):
+                    raise proxy_error from direct_error
+                raise
+
+    def _fetch_with_retries(
+        self,
+        url: str,
+        headers: dict[str, str],
+        verify: bool,
+        proxies: dict[str, str] | None = None,
+    ) -> FetchedSubscription:
+        """One route: several attempts on network failures, none on a server answer."""
+        # proxies передаётся только для маршрута через прокси: без аргумента
+        # requests ведёт себя как раньше (в том числе читает переменные окружения).
+        route = {"proxies": proxies} if proxies else {}
+
         last_error: requests.RequestException | None = None
         for attempt in range(self.MAX_ATTEMPTS):
             try:
-                response = requests.get(url, headers=headers, timeout=30, verify=verify)
+                response = requests.get(url, headers=headers, timeout=30, verify=verify, **route)
                 self._raise_for_status(response)
                 content = self._decode(response)
                 # Как в Android: проверяется уже прочитанное тело. Защищает разбор
@@ -81,11 +127,13 @@ class SubscriptionUpdater:
                     raise
                 last_error = e
                 delay = self.RETRY_BASE_DELAY_SEC * (2**attempt)
+                # В журнал — тип ошибки, а не её текст: в тексте requests лежит
+                # полный адрес подписки вместе с токеном.
                 logger.warning(
                     "Попытка %d/%d загрузить подписку не удалась (%s), повтор через %.1f с",
                     attempt + 1,
                     self.MAX_ATTEMPTS,
-                    e,
+                    type(e).__name__,
                     delay,
                 )
                 time.sleep(delay)
@@ -201,6 +249,7 @@ def update_subscription(
     profiles: ProfileManager | None = None,
     group_id: int | None = None,
     clear_existing: bool = True,
+    proxy_url: Callable[[], str | None] | None = None,
 ) -> list[ProxyBean]:
     """
     Update subscription (helper function).
@@ -211,9 +260,10 @@ def update_subscription(
         profiles: Profile manager
         group_id: Group ID
         clear_existing: Clear existing profiles
+        proxy_url: Returns the local proxy to try first, or None
 
     Returns:
         List of added profiles
     """
-    updater = SubscriptionUpdater(config=config, profiles=profiles)
+    updater = SubscriptionUpdater(config=config, profiles=profiles, proxy_url=proxy_url)
     return updater.update(url, group_id, clear_existing)
```

```diff
--- a/src/db/data_store.py
+++ b/src/db/data_store.py
@@ -59,7 +59,6 @@ class DataStore(ConfigBase):
     start_minimal: bool = False
     # Subscriptions
     user_agent: str = ""
-    sub_use_proxy: bool = False
     sub_clear: bool = False
     sub_insecure: bool = False
     sub_auto_update: int = -30
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_sub_route.py tests/test_sub_updater.py tests/test_sub_updater_retry_json.py tests/test_sub_errors.py -q`
Expected: 59 passed.

**Step 5: Написать GTK-тест связки**

```diff
--- a/tests/test_ui_application.py
+++ b/tests/test_ui_application.py
@@ -197,6 +197,29 @@ def test_a_denied_update_shows_the_providers_explanation(adw_app):
     assert "403: Превышен лимит устройств" in adw_app.last_toast_for_test
 
 
+def test_the_default_updater_goes_through_the_running_proxy(adw_app):
+    """В режиме системного прокси requests сам его не видит: адрес передаётся явно."""
+    from unittest.mock import Mock, patch
+
+    from src.db.config import ProxyMode
+
+    group = adw_app.context.profiles.add_group("Подписка", is_subscription=True)
+    adw_app.context.proxy_state.set_running(1, mode=ProxyMode.SYSTEM_PROXY)
+
+    response = Mock()
+    response.text = "vless://11111111-1111-1111-1111-111111111111@h.example:443?type=tcp#A"
+    response.raise_for_status = Mock()
+
+    with patch("src.sub.updater.requests.get", return_value=response) as mock_get:
+        count = adw_app._default_subscription_updater(group.id, "https://sub.example/list")
+
+    assert count == 1
+    assert mock_get.call_args.kwargs["proxies"] == {
+        "http": "http://127.0.0.1:2081",
+        "https": "http://127.0.0.1:2081",
+    }
+
+
 # --- подключение и диалоги (этап 3) ---
 
 LINK = "vless://11111111-1111-1111-1111-111111111111@host.example:443?type=tcp#Новый"
```

**Step 6: Убедиться, что падает**

Run: `gtk_test tests/test_ui_application.py -k "default_updater"`
Expected: 1 failed — `KeyError: 'proxies'`.

**Step 7: Передать маршрут из приложения**

```diff
--- a/src/ui/application.py
+++ b/src/ui/application.py
@@ -564,13 +564,16 @@ class TengaApplication(Adw.Application):
                 logger.debug("Latency probe cleanup failed", exc_info=True)
 
     def _default_subscription_updater(self, group_id: int, url: str) -> int:
+        from src.sub.route import local_proxy_url
         from src.sub.updater import update_subscription
 
+        context = self.context
         beans = update_subscription(
             url,
-            config=self.context.config,
-            profiles=self.context.profiles,
+            config=context.config,
+            profiles=context.profiles,
             group_id=group_id,
+            proxy_url=lambda: local_proxy_url(context.config, context.proxy_state),
         )
         return len(beans)
 
```

**Step 8: Убедиться, что проходят**

Run: `gtk_test tests/test_ui_application.py -k "default_updater"`
Expected: 1 passed.

Run: `uv run pytest -q`
Expected: `747 passed`.

**Step 9: Commit**

```bash
git add src/sub/route.py src/sub/updater.py src/db/data_store.py src/ui/application.py \
        tests/test_sub_route.py tests/test_ui_application.py
git commit -m "feat(sub): загружать подписку через работающий прокси с откатом напрямую"
```

---

### Task 12: Страница настроек «Подписки»

У настройки `user_agent` до сих пор нет поля в интерфейсе. Новая страница
«Подписки» с группой «Запрос к провайдеру» и строкой User-Agent: пустое поле —
значение по умолчанию. Прежнее значение по умолчанию показывается как пустое.

Страница вставляется между «DNS» и «О программе». **Сверь с кодом:** этап 1
(задача 6) добавляет в `SettingsDialog.__init__` свою страницу, а этапы 3 и 4
могут добавить ещё — контекст вокруг вызовов `_build_*_page()` в diff может не
совпасть. Нужна одна строка `self._build_subscriptions_page()` перед
`self._build_about_page()`.

**Files:**
- Modify: `src/ui/dialogs/settings.py` (импорт, `__init__`, новый `_build_subscriptions_page`, `_load`, `save`)
- Test: `tests/test_ui_dialogs_settings.py` (GTK)

**Step 1: Написать падающие тесты**

```diff
--- a/tests/test_ui_dialogs_settings.py
+++ b/tests/test_ui_dialogs_settings.py
@@ -128,3 +128,29 @@ def test_the_dns_through_proxy_switch_round_trips(gtk_ready):
     dialog.dns_proxy_row.set_active(False)
     dialog.save()
     assert config.dns.use_proxy is False
+
+
+# --- подписки ---
+
+
+def test_the_user_agent_round_trips(gtk_ready):
+    config = make_config()
+    dialog = make_dialog(config)
+    assert dialog.user_agent_row.get_text() == ""
+
+    dialog.user_agent_row.set_text("  MyClient/2.0  ")
+    dialog.save()
+
+    assert config.user_agent == "MyClient/2.0"
+    assert config.get_user_agent() == "MyClient/2.0"
+
+
+def test_the_old_default_user_agent_is_shown_as_unset(gtk_ready):
+    """Прежнее значение по умолчанию — не выбор пользователя: поле остаётся пустым."""
+    config = make_config()
+    config.user_agent = "Tenga-proxy/1.0 (Prefer ClashMeta Format)"
+    dialog = make_dialog(config)
+
+    assert dialog.user_agent_row.get_text() == ""
+    dialog.save()
+    assert config.user_agent == ""
```

**Step 2: Убедиться, что падают**

Run: `gtk_test tests/test_ui_dialogs_settings.py`
Expected: 2 failed —
`'SettingsDialog' object has no attribute 'user_agent_row'`.

**Step 3: Реализовать**

```diff
--- a/src/ui/dialogs/settings.py
+++ b/src/ui/dialogs/settings.py
@@ -10,6 +10,7 @@ gi.require_version("Adw", "1")
 from gi.repository import Adw, GObject, Gtk
 
 from src.db.config import DnsProvider, ProxyMode
+from src.db.data_store import DEFAULT_USER_AGENT, LEGACY_USER_AGENT
 from src.ui.logic.version import UNKNOWN, app_version, core_version
 
 LOG_LEVELS = ["debug", "info", "warning", "error", "none"]
@@ -65,6 +66,7 @@ class SettingsDialog(Adw.PreferencesDialog):
         self._build_general_page()
         self._build_monitoring_page()
         self._build_dns_page()
+        self._build_subscriptions_page()
         self._build_about_page()
 
         self._load()
@@ -164,6 +166,20 @@ class SettingsDialog(Adw.PreferencesDialog):
         )
         options.add(self.dns_proxy_row)
 
+    def _build_subscriptions_page(self) -> None:
+        page = Adw.PreferencesPage(title="Подписки", icon_name="folder-download-symbolic")
+        self.add(page)
+
+        request = Adw.PreferencesGroup(
+            title="Запрос к провайдеру",
+            description=f"Пустое поле — {DEFAULT_USER_AGENT}: так представляется большинство "
+            "клиентов, и провайдеры отдают ему обычный список серверов.",
+        )
+        page.add(request)
+
+        self.user_agent_row = Adw.EntryRow(title="User-Agent")
+        request.add(self.user_agent_row)
+
     def _build_about_page(self) -> None:
         page = Adw.PreferencesPage(title="О программе", icon_name="help-about-symbolic")
         self.add(page)
@@ -231,6 +247,9 @@ class SettingsDialog(Adw.PreferencesDialog):
         self.dns_url_row.set_text(dns.custom_url)
         self.dns_proxy_row.set_active(dns.use_proxy)
 
+        user_agent = config.user_agent.strip()
+        self.user_agent_row.set_text("" if user_agent == LEGACY_USER_AGENT else user_agent)
+
     def save(self) -> None:
         """Write the form back into the configuration object."""
         config = self._config
@@ -252,6 +271,8 @@ class SettingsDialog(Adw.PreferencesDialog):
         config.dns.custom_url = self.dns_url_row.get_text().strip()
         config.dns.use_proxy = self.dns_proxy_row.get_active()
 
+        config.user_agent = self.user_agent_row.get_text().strip()
+
         self.emit("settings-saved")
 
     # --- вспомогательное для тестов и внешнего кода ---
```

**Step 4: Убедиться, что проходят**

Run: `gtk_test tests/test_ui_dialogs_settings.py`
Expected: 16 passed.

Run: `uv run pytest -q`
Expected: `747 passed`.

**Step 5: Commit**

```bash
git add src/ui/dialogs/settings.py tests/test_ui_dialogs_settings.py
git commit -m "feat(ui): страница настроек «Подписки» с полем User-Agent"
```

---

### Task 13: Данные устройства в запросе подписки (S7)

> **Необязательная.** Можно вычеркнуть без последствий для остальных задач.
> Тогда в задаче 15 убери из документации абзац «Отправлять данные устройства».

Часть провайдеров считает лимит устройств по заголовку `x-hwid` и без него
отвечает 403. По флагу «Отправлять данные устройства» (выключен) уходят:

| Заголовок | Значение |
|---|---|
| `x-hwid` | случайный UUID установки |
| `x-device-os` | `Linux` |
| `x-ver-os` | `NAME VERSION_ID` из `/etc/os-release`, иначе версия ядра |
| `x-device-model` | `/sys/class/dmi/id/product_name`, иначе `PC` |
| `Accept-Language` | язык системы из `LC_ALL`/`LANG` (`ru-RU`) |

Правила:

- При выключенном флаге HWID не создаётся вовсе.
- HWID создаётся в диалоге настроек, в момент включения флага: сразу после
  этого настройки пишутся на диск. Создавать его при запросе нельзя —
  несохранённый идентификатор менялся бы при каждом запуске, и провайдер
  считал бы каждый запуск новым устройством. Поэтому при включённом флаге, но
  пустом HWID (настройки правили руками) заголовки не отправляются.
- Значения фильтруются до печатного ASCII: иначе `requests` откажется
  отправлять заголовок.
- HWID скрыт из `repr` настроек и не пишется в журнал.
- Имя хоста не отправляется: в нём часто имя владельца.
- При отказе 403/429 и выключенном флаге к сообщению добавляется подсказка про
  настройку.

**Files:**
- Create: `src/sub/device.py`
- Modify: `src/db/data_store.py` (поля рядом с `user_agent`)
- Modify: `src/sub/updater.py` (`fetch_response`)
- Modify: `src/ui/logic/subscriptions_view.py` (`describe_update_error`)
- Modify: `src/ui/application.py` (`_on_subscriptions_failed`)
- Modify: `src/ui/dialogs/settings.py` (страница «Подписки» из задачи 12)
- Test: `tests/test_sub_device.py` (новый), `tests/test_ui_logic_subscriptions_view.py`, `tests/test_ui_dialogs_settings.py` (GTK)

**Step 1: Написать падающие тесты**

Создать файл `tests/test_sub_device.py`:

```python
"""Данные устройства в запросе подписки: только по явному согласию."""

import uuid
from unittest.mock import Mock, patch

from src.db.data_store import DataStore
from src.sub.device import DeviceInfo, device_headers, ensure_hwid, read_device_info
from src.sub.updater import SubscriptionUpdater

INFO = DeviceInfo(os_version="Ubuntu 26.04", model="ThinkPad X1", language="ru-RU")


def _enabled() -> DataStore:
    config = DataStore()
    config.sub_send_device_info = True
    ensure_hwid(config)
    return config


def test_nothing_is_sent_by_default():
    config = DataStore()

    assert device_headers(config, INFO) == {}
    # Без согласия идентификатор не должен даже появляться.
    assert config.sub_hwid == ""


def test_hwid_is_created_once_and_stays_the_same():
    config = DataStore()

    first = ensure_hwid(config)
    second = ensure_hwid(config)

    assert first == second == config.sub_hwid
    assert str(uuid.UUID(first)) == first


def test_enabled_flag_sends_the_device_headers():
    config = _enabled()

    assert device_headers(config, INFO) == {
        "x-hwid": config.sub_hwid,
        "x-device-os": "Linux",
        "x-ver-os": "Ubuntu 26.04",
        "x-device-model": "ThinkPad X1",
        "Accept-Language": "ru-RU",
    }


def test_no_headers_without_a_stored_hwid():
    """Несохранённый идентификатор менялся бы при каждом запуске — «новое устройство»."""
    config = DataStore()
    config.sub_send_device_info = True

    assert device_headers(config, INFO) == {}


def test_header_values_are_printable_ascii():
    """requests отказывается отправлять заголовок с не-latin-1 символами."""
    config = _enabled()
    info = DeviceInfo(os_version="Альт 11", model="Ноутбук\r\nX: 1", language="")

    headers = device_headers(config, info)

    assert headers["x-ver-os"] == "11"
    assert headers["x-device-model"] == "X: 1"
    assert "Accept-Language" not in headers


def test_hwid_is_hidden_from_repr():
    """repr настроек попадает в журнал при отладке."""
    config = _enabled()

    assert config.sub_hwid not in repr(config)


def test_hwid_survives_saving_and_loading(tmp_path):
    config = _enabled()
    config.save(tmp_path / "settings.json")

    assert DataStore.load(tmp_path / "settings.json").sub_hwid == config.sub_hwid


def test_real_device_info_is_readable():
    info = read_device_info()

    assert info.os_version
    assert info.model


def _ok() -> Mock:
    response = Mock()
    response.text = "ok"
    response.raise_for_status = Mock()
    return response


def test_updater_adds_device_headers_when_enabled():
    config = _enabled()

    with patch("src.sub.updater.requests.get", return_value=_ok()) as mock_get:
        SubscriptionUpdater(config=config).fetch("https://example.com/sub")

    sent = mock_get.call_args.kwargs["headers"]
    assert sent["x-hwid"] == config.sub_hwid
    assert sent["x-device-os"] == "Linux"
    assert sent["User-Agent"]


def test_updater_sends_no_device_headers_by_default():
    with patch("src.sub.updater.requests.get", return_value=_ok()) as mock_get:
        SubscriptionUpdater(config=DataStore()).fetch("https://example.com/sub")

    assert set(mock_get.call_args.kwargs["headers"]) == {"User-Agent"}
```

```diff
--- a/tests/test_ui_logic_subscriptions_view.py
+++ b/tests/test_ui_logic_subscriptions_view.py
@@ -221,3 +221,26 @@ def test_unknown_errors_fall_back_to_their_text():
     from src.ui.logic.subscriptions_view import describe_update_error
 
     assert describe_update_error(ValueError("boom")) == "boom"
+
+
+def test_access_denied_without_device_data_suggests_enabling_it():
+    from src.sub.errors import SubscriptionHttpError
+    from src.ui.logic.subscriptions_view import describe_update_error
+
+    text = describe_update_error(
+        SubscriptionHttpError(403, "HWID required"), device_info_sent=False
+    )
+
+    assert text.startswith("сервер ответил 403: HWID required")
+    assert "Настройки → Подписки" in text
+
+
+def test_no_hint_when_device_data_is_already_sent_or_the_error_is_different():
+    from src.sub.errors import SubscriptionHttpError
+    from src.ui.logic.subscriptions_view import describe_update_error
+
+    denied = describe_update_error(SubscriptionHttpError(403, "x"), device_info_sent=True)
+    missing = describe_update_error(SubscriptionHttpError(404), device_info_sent=False)
+
+    assert "Настройки" not in denied
+    assert "Настройки" not in missing
```

```diff
--- a/tests/test_ui_dialogs_settings.py
+++ b/tests/test_ui_dialogs_settings.py
@@ -154,3 +154,25 @@ def test_the_old_default_user_agent_is_shown_as_unset(gtk_ready):
     assert dialog.user_agent_row.get_text() == ""
     dialog.save()
     assert config.user_agent == ""
+
+
+def test_device_info_is_off_by_default(gtk_ready):
+    config = make_config()
+    dialog = make_dialog(config)
+
+    assert not dialog.device_info_row.get_active()
+    dialog.save()
+    assert not config.sub_send_device_info
+    assert config.sub_hwid == ""
+
+
+def test_enabling_device_info_creates_the_hwid(gtk_ready):
+    """Идентификатор создаётся здесь, чтобы сохраниться вместе с настройками."""
+    config = make_config()
+    dialog = make_dialog(config)
+
+    dialog.device_info_row.set_active(True)
+    dialog.save()
+
+    assert config.sub_send_device_info
+    assert config.sub_hwid
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_sub_device.py tests/test_ui_logic_subscriptions_view.py -q`
Expected: ошибка сборки `No module named 'src.sub.device'` — на ней pytest
останавливается. Два новых теста описания ошибки, запущенные отдельно, падают
на `got an unexpected keyword argument 'device_info_sent'`.

Run: `gtk_test tests/test_ui_dialogs_settings.py`
Expected: 2 failed, 16 passed —
`'SettingsDialog' object has no attribute 'device_info_row'`.

**Step 3: Реализовать**

Создать файл `src/sub/device.py`:

```python
"""Данные устройства в запросе подписки.

Часть провайдеров считает лимит устройств по ``x-hwid`` и без него отвечает
403. HWID — стабильный идентификатор, поэтому уходит только по явному флагу
пользователя; при выключенном флаге он даже не создаётся.
"""

from __future__ import annotations

import os
import platform
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.data_store import DataStore

HEADER_HWID = "x-hwid"
HEADER_DEVICE_OS = "x-device-os"
HEADER_OS_VERSION = "x-ver-os"
HEADER_DEVICE_MODEL = "x-device-model"
HEADER_LANGUAGE = "Accept-Language"

OS_NAME = "Linux"
UNKNOWN_MODEL = "PC"

_DMI_PRODUCT_NAME = Path("/sys/class/dmi/id/product_name")
# Язык системы, а не интерфейса: LC_MESSAGES приложение подменяет само
# (src/ui/logic/locale.py).
_LANGUAGE_VARS = ("LC_ALL", "LANG")


@dataclass(frozen=True)
class DeviceInfo:
    """Что сообщается провайдеру об устройстве помимо HWID."""

    os_version: str
    model: str
    language: str


def ascii_header_value(raw: str) -> str:
    """Оставить печатный ASCII: остальное requests в заголовок не пропустит."""
    return "".join(ch for ch in raw if " " <= ch <= "~").strip()


def _os_version() -> str:
    try:
        release = platform.freedesktop_os_release()
    except OSError:
        return platform.release()
    name = release.get("NAME", "").strip()
    version = release.get("VERSION_ID", "").strip()
    return f"{name} {version}".strip() or platform.release()


def _model() -> str:
    try:
        return _DMI_PRODUCT_NAME.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""


def _language() -> str:
    for name in _LANGUAGE_VARS:
        # "ru_RU.UTF-8" -> "ru-RU"; "C" и "POSIX" языком не являются.
        value = os.environ.get(name, "").split(".")[0].split("@")[0]
        if value and value not in ("C", "POSIX"):
            return value.replace("_", "-")
    return ""


def read_device_info() -> DeviceInfo:
    """Collect the device description from the running system."""
    return DeviceInfo(
        os_version=_os_version(),
        model=_model() or UNKNOWN_MODEL,
        language=_language(),
    )


def ensure_hwid(config: DataStore) -> str:
    """Return the stored HWID, creating it on first use.

    Вызывается там, где настройки затем сохраняются на диск (диалог настроек):
    несохранённый идентификатор менялся бы при каждом запуске, и провайдер
    считал бы каждый запуск новым устройством.
    """
    if not config.sub_hwid:
        config.sub_hwid = str(uuid.uuid4())
    return config.sub_hwid


def device_headers(config: DataStore, info: DeviceInfo | None = None) -> dict[str, str]:
    """Headers describing the device; empty unless the user opted in."""
    if not config.sub_send_device_info or not config.sub_hwid:
        return {}

    info = info or read_device_info()
    headers = {
        HEADER_HWID: config.sub_hwid,
        HEADER_DEVICE_OS: OS_NAME,
        HEADER_OS_VERSION: info.os_version,
        HEADER_DEVICE_MODEL: info.model,
        HEADER_LANGUAGE: info.language,
    }
    cleaned = {name: ascii_header_value(value) for name, value in headers.items()}
    return {name: value for name, value in cleaned.items() if value}
```

```diff
--- a/src/db/data_store.py
+++ b/src/db/data_store.py
@@ -59,6 +59,10 @@ class DataStore(ConfigBase):
     start_minimal: bool = False
     # Subscriptions
     user_agent: str = ""
+    # Данные устройства в запросе подписки (src/sub/device.py). HWID создаётся
+    # только при включении флага и не попадает в repr: тот уходит в журнал.
+    sub_send_device_info: bool = False
+    sub_hwid: str = field(default="", repr=False)
     sub_clear: bool = False
     sub_insecure: bool = False
     sub_auto_update: int = -30
```

```diff
--- a/src/sub/updater.py
+++ b/src/sub/updater.py
@@ -10,6 +10,7 @@ import requests
 
 from src.db import DataStore
 from src.fmt import ProxyBean, parse_subscription_content
+from src.sub.device import device_headers
 from src.sub.errors import (
     MAX_RESPONSE_SIZE,
     SubscriptionHttpError,
@@ -62,6 +63,8 @@ class SubscriptionUpdater:
             user_agent = self._config.get_user_agent()
             if user_agent:
                 headers["User-Agent"] = user_agent
+            # Не логировать: при включённом флаге здесь лежит HWID.
+            headers.update(device_headers(self._config))
 
         verify = True
         if self._config and self._config.sub_insecure:
```

```diff
--- a/src/ui/logic/subscriptions_view.py
+++ b/src/ui/logic/subscriptions_view.py
@@ -123,11 +123,16 @@ def build_subscription_rows(
     return rows
 
 
-def describe_update_error(error: BaseException) -> str:
+DEVICE_INFO_HINT = "Возможно, провайдеру нужны данные устройства: Настройки → Подписки."
+
+
+def describe_update_error(error: BaseException, *, device_info_sent: bool = True) -> str:
     """Explain a failed update without quoting the subscription address.
 
     Текст ошибок requests содержит полный URL, а в нём — токен подписки:
     сообщение уходит в уведомление и в журнал, поэтому собирается заново.
+    ``device_info_sent=False`` добавляет к отказу 403/429 подсказку про флаг
+    «Отправлять данные устройства»: без HWID часть провайдеров отвечает именно так.
     """
     # Импорт внутри функции: модуль списка подписок не должен тянуть requests
     # при каждом открытии окна.
@@ -139,6 +144,8 @@ def describe_update_error(error: BaseException) -> str:
         text = f"сервер ответил {error.status_code}"
         if error.is_access_denied and error.body_snippet:
             text += f": {error.body_snippet}"
+        if error.is_access_denied and not device_info_sent:
+            text = f"{text.rstrip('.')}. {DEVICE_INFO_HINT}"
         return text
     if isinstance(error, SubscriptionTooLargeError):
         return "ответ сервера больше 10 МБ"
```

```diff
--- a/src/ui/application.py
+++ b/src/ui/application.py
@@ -730,7 +730,9 @@ class TengaApplication(Adw.Application):
         self.toast(f"Обновлено профилей: {total}")
 
     def _on_subscriptions_failed(self, error: BaseException) -> None:
-        self.toast(f"Не удалось обновить подписки: {describe_update_error(error)}")
+        sent = self.context.config.sub_send_device_info
+        reason = describe_update_error(error, device_info_sent=sent)
+        self.toast(f"Не удалось обновить подписки: {reason}")
 
     def _toggle_search(self) -> None:
         if self._window is not None:
```

```diff
--- a/src/ui/dialogs/settings.py
+++ b/src/ui/dialogs/settings.py
@@ -11,6 +11,7 @@ from gi.repository import Adw, GObject, Gtk
 
 from src.db.config import DnsProvider, ProxyMode
 from src.db.data_store import DEFAULT_USER_AGENT, LEGACY_USER_AGENT
+from src.sub.device import ensure_hwid
 from src.ui.logic.version import UNKNOWN, app_version, core_version
 
 LOG_LEVELS = ["debug", "info", "warning", "error", "none"]
@@ -180,6 +181,13 @@ class SettingsDialog(Adw.PreferencesDialog):
         self.user_agent_row = Adw.EntryRow(title="User-Agent")
         request.add(self.user_agent_row)
 
+        self.device_info_row = Adw.SwitchRow(
+            title="Отправлять данные устройства",
+            subtitle="Идентификатор, система и модель. Нужны провайдерам, "
+            "которые считают лимит устройств",
+        )
+        request.add(self.device_info_row)
+
     def _build_about_page(self) -> None:
         page = Adw.PreferencesPage(title="О программе", icon_name="help-about-symbolic")
         self.add(page)
@@ -249,6 +257,7 @@ class SettingsDialog(Adw.PreferencesDialog):
 
         user_agent = config.user_agent.strip()
         self.user_agent_row.set_text("" if user_agent == LEGACY_USER_AGENT else user_agent)
+        self.device_info_row.set_active(config.sub_send_device_info)
 
     def save(self) -> None:
         """Write the form back into the configuration object."""
@@ -272,6 +281,11 @@ class SettingsDialog(Adw.PreferencesDialog):
         config.dns.use_proxy = self.dns_proxy_row.get_active()
 
         config.user_agent = self.user_agent_row.get_text().strip()
+        config.sub_send_device_info = self.device_info_row.get_active()
+        if config.sub_send_device_info:
+            # Создаётся здесь, а не при запросе: настройки сейчас уйдут на диск,
+            # и идентификатор не будет меняться от запуска к запуску.
+            ensure_hwid(config)
 
         self.emit("settings-saved")
 
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest -q`
Expected: `759 passed`.

Run: `gtk_test tests/test_ui_dialogs_settings.py tests/test_ui_application.py -k "settings or subscription or update or device"`
Expected: 28 passed.

**Step 5: Commit**

```bash
git add src/sub/device.py src/db/data_store.py src/sub/updater.py \
        src/ui/logic/subscriptions_view.py src/ui/application.py src/ui/dialogs/settings.py \
        tests/test_sub_device.py tests/test_ui_logic_subscriptions_view.py \
        tests/test_ui_dialogs_settings.py
git commit -m "feat(sub): отправлять данные устройства провайдеру по явному флагу"
```

---

### Task 14: Предложение сменить адрес подписки (S8)

> **Необязательная.** Можно вычеркнуть без последствий для остальных задач.
> Тогда в задаче 15 убери из таблицы документации строку `new-url`,
> `fallback-url`.

Провайдер может сообщить два адреса (заголовком или строкой `#key:` в теле):

- `new-url` — «подписка переехала». Предлагается после удачного обновления, в
  файл профилей не сохраняется.
- `fallback-url` — запасной адрес. Сохраняется в группе и предлагается, когда
  обновление не удалось.

**Адрес меняется только после подтверждения в диалоге.** Автозамена отдала бы
серверу подписки право молча перенаправить клиента куда угодно. Кандидат
отбрасывается, если совпадает с текущим адресом, имеет не `http(s)`-схему или
указывает на локальный адрес (`localhost`, частные и link-local сети, `.local`).
Enter и Escape в диалоге оставляют прежний адрес.

После подтверждения подписка сразу обновляется с нового адреса. За одно
обновление показывается одно предложение; остальные придут со следующим.

**Files:**
- Create: `src/sub/url_change.py`
- Modify: `src/sub/metadata.py` (ключи, поля `SubscriptionMetadata`, `parse_metadata`, `apply_metadata`)
- Modify: `src/db/profiles.py` (`ProfileGroup.sub_fallback_url`)
- Modify: `src/sub/updater.py` (`__init__`, `update`)
- Modify: `src/ui/logic/subscriptions_view.py` (`describe_url_change`)
- Modify: `src/ui/dialogs/confirm.py` (`build_url_change_confirmation`)
- Modify: `src/ui/application.py` (`__init__`, `update_subscription`, `_default_subscription_updater`, новые `_propose_fallback_url`, `_offer_url_change`, `_apply_url_change`, `_refresh_subscriptions`, `_on_subscriptions_updated`, `_on_subscriptions_failed`, `reset_for_tests`)
- Test: `tests/test_sub_url_change.py` (новый), `tests/test_ui_logic_subscriptions_view.py`, `tests/test_ui_application.py` (GTK)

**Step 1: Написать падающие тесты логики**

Создать файл `tests/test_sub_url_change.py`:

```python
"""Смена адреса подписки по подсказке провайдера: только предложение, без автозамены."""

from unittest.mock import Mock, patch

import pytest

from src.sub.metadata import SubscriptionMetadata, apply_metadata, metadata_from_headers
from src.sub.updater import SubscriptionUpdater
from src.sub.url_change import (
    REASON_FALLBACK_URL,
    REASON_NEW_URL,
    UrlChangeProposal,
    is_acceptable_subscription_url,
    propose_url_change,
)

CURRENT = "https://provider.example/sub/token"
LINK = "vless://11111111-1111-1111-1111-111111111111@nl.example.org:443?type=tcp#NL-1"


@pytest.mark.parametrize(
    "url",
    ["https://new.example/sub/token", "http://new.example:8080/sub", "https://93.184.216.34/sub"],
)
def test_public_http_addresses_are_acceptable(url):
    assert is_acceptable_subscription_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "vless://uuid@host:443",
        "ftp://new.example/sub",
        "https://",
        "https://localhost/sub",
        "https://router.local/sub",
        "http://127.0.0.1:8080/sub",
        "http://10.0.0.5/sub",
        "http://172.16.3.1/sub",
        "http://192.168.1.1/sub",
        "http://169.254.1.1/sub",
        "http://[::1]/sub",
        "http://[fe80::1]/sub",
        "http://[fc00::1]/sub",
        "https://new.example/" + "x" * 2048,
    ],
)
def test_other_addresses_are_not(url):
    """Провайдер не должен отправлять клиента на локальные адреса и чужие схемы."""
    assert not is_acceptable_subscription_url(url)


def test_a_different_acceptable_address_becomes_a_proposal():
    proposal = propose_url_change(7, CURRENT, "  https://new.example/sub  ", REASON_NEW_URL)

    assert proposal == UrlChangeProposal(
        group_id=7, new_url="https://new.example/sub", reason=REASON_NEW_URL
    )


@pytest.mark.parametrize("candidate", ["", None, CURRENT, f"  {CURRENT} ", "http://192.168.1.1/s"])
def test_nothing_is_proposed_for_an_empty_same_or_unsafe_address(candidate):
    assert propose_url_change(7, CURRENT, candidate, REASON_NEW_URL) is None


def test_both_addresses_are_read_from_the_response():
    metadata = metadata_from_headers(
        {"New-Url": "https://new.example/sub", "Fallback-Url": "https://backup.example/sub"}
    )

    assert metadata.new_url == "https://new.example/sub"
    assert metadata.fallback_url == "https://backup.example/sub"


def _group():
    from src.db.profiles import ProfileGroup

    return ProfileGroup(id=1, name="Sub", is_subscription=True, subscription_url=CURRENT)


def test_the_fallback_address_is_kept_for_a_failed_update():
    group = _group()
    apply_metadata(group, SubscriptionMetadata(fallback_url="https://backup.example/sub"))

    assert group.sub_fallback_url == "https://backup.example/sub"


def test_an_unsafe_fallback_address_is_not_stored():
    group = _group()
    apply_metadata(group, SubscriptionMetadata(fallback_url="http://192.168.1.1/sub"))

    assert group.sub_fallback_url == ""


def test_the_new_address_never_replaces_the_current_one_by_itself():
    group = _group()
    apply_metadata(group, SubscriptionMetadata(new_url="https://new.example/sub"))

    assert group.subscription_url == CURRENT


def test_updater_reports_the_new_address_of_the_last_update(tmp_path):
    from src.db.profiles import ProfileManager

    profiles = ProfileManager(profiles_dir=tmp_path)
    group = profiles.add_group("Sub", is_subscription=True)
    group.subscription_url = CURRENT
    updater = SubscriptionUpdater(profiles=profiles)

    def response(headers: dict[str, str]) -> Mock:
        mock = Mock()
        mock.text = LINK
        mock.content = LINK.encode("utf-8")
        mock.headers = headers
        mock.raise_for_status = Mock()
        return mock

    with patch("src.sub.updater.requests.get") as mock_get:
        mock_get.return_value = response({"new-url": "https://new.example/sub"})
        updater.update(CURRENT, group_id=group.id)
        assert updater.new_url == "https://new.example/sub"
        assert group.subscription_url == CURRENT

        mock_get.return_value = response({})
        updater.update(CURRENT, group_id=group.id)
        assert updater.new_url == ""
```

```diff
--- a/tests/test_ui_logic_subscriptions_view.py
+++ b/tests/test_ui_logic_subscriptions_view.py
@@ -244,3 +244,31 @@ def test_no_hint_when_device_data_is_already_sent_or_the_error_is_different():
 
     assert "Настройки" not in denied
     assert "Настройки" not in missing
+
+
+# --- Предложение сменить адрес ------------------------------------------------
+
+
+def test_new_address_question_names_the_subscription_and_both_addresses():
+    from src.sub.url_change import REASON_NEW_URL, UrlChangeProposal
+    from src.ui.logic.subscriptions_view import describe_url_change
+
+    proposal = UrlChangeProposal(1, "https://new.example/sub", REASON_NEW_URL)
+    heading, body = describe_url_change("Основная", "https://old.example/sub", proposal)
+
+    assert heading == "Сменить адрес подписки?"
+    assert "«Основная»" in body
+    assert "новый адрес" in body
+    assert "https://new.example/sub" in body
+    assert "https://old.example/sub" in body
+
+
+def test_fallback_address_question_mentions_the_failed_update():
+    from src.sub.url_change import REASON_FALLBACK_URL, UrlChangeProposal
+    from src.ui.logic.subscriptions_view import describe_url_change
+
+    proposal = UrlChangeProposal(1, "https://backup.example/sub", REASON_FALLBACK_URL)
+    _heading, body = describe_url_change("Основная", "https://old.example/sub", proposal)
+
+    assert "не удалось" in body
+    assert "запасной адрес" in body
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_sub_url_change.py tests/test_ui_logic_subscriptions_view.py -q`
Expected: ошибка сборки `No module named 'src.sub.url_change'`.

**Step 3: Реализовать логику**

Создать файл `src/sub/url_change.py`:

```python
"""Смена адреса подписки по подсказке провайдера.

Адрес меняется только после подтверждения пользователя: автозамена отдала бы
серверу подписки право молча перенаправить клиента куда угодно.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit

REASON_NEW_URL = "new-url"  # провайдер сообщил новый адрес при удачном обновлении
REASON_FALLBACK_URL = "fallback-url"  # обновление не удалось, есть запасной адрес

MAX_URL_LENGTH = 2048

_LOCAL_SUFFIXES = (".localhost", ".local", ".lan", ".internal")


@dataclass(frozen=True)
class UrlChangeProposal:
    """Предложение, которое пользователь подтверждает или отклоняет."""

    group_id: int
    new_url: str
    reason: str


def _is_local_host(host: str) -> bool:
    lowered = host.lower()
    if lowered == "localhost" or lowered.endswith(_LOCAL_SUFFIXES):
        return True
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        return False
    return not address.is_global


def is_acceptable_subscription_url(url: str) -> bool:
    """Годится ли адрес как адрес подписки: http(s) с публичным хостом."""
    if not url or len(url) > MAX_URL_LENGTH:
        return False
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
    except ValueError:
        return False
    if parts.scheme.lower() not in ("http", "https") or not host:
        return False
    return not _is_local_host(host)


def propose_url_change(
    group_id: int, current_url: str, candidate: str | None, reason: str
) -> UrlChangeProposal | None:
    """Build a proposal, or None when there is nothing safe and new to offer."""
    url = (candidate or "").strip()
    if not url or url == current_url.strip():
        return None
    if not is_acceptable_subscription_url(url):
        return None
    return UrlChangeProposal(group_id=group_id, new_url=url, reason=reason)
```

```diff
--- a/src/sub/metadata.py
+++ b/src/sub/metadata.py
@@ -16,6 +16,7 @@ from typing import TYPE_CHECKING
 from urllib.parse import urlsplit
 
 from src.fmt.parsers import decode_base64
+from src.sub.url_change import is_acceptable_subscription_url
 
 if TYPE_CHECKING:
     from src.db.profiles import ProfileGroup
@@ -26,6 +27,8 @@ KEY_ANNOUNCE = "announce"
 KEY_SUPPORT_URL = "support-url"
 KEY_PROFILE_TITLE = "profile-title"
 KEY_WEB_PAGE_URL = "profile-web-page-url"
+KEY_NEW_URL = "new-url"
+KEY_FALLBACK_URL = "fallback-url"
 
 KNOWN_KEYS = frozenset(
     {
@@ -35,6 +38,8 @@ KNOWN_KEYS = frozenset(
         KEY_SUPPORT_URL,
         KEY_PROFILE_TITLE,
         KEY_WEB_PAGE_URL,
+        KEY_NEW_URL,
+        KEY_FALLBACK_URL,
     }
 )
 
@@ -97,6 +102,9 @@ class SubscriptionMetadata:
     support_url: str = ""
     title: str = ""
     web_page_url: str = ""
+    # Только предложения: адрес подписки меняет пользователь (src/sub/url_change.py).
+    new_url: str = ""
+    fallback_url: str = ""
 
     def overridden_by(self, body: SubscriptionMetadata) -> SubscriptionMetadata:
         """Values from the body win over headers; empty ones do not erase anything."""
@@ -163,6 +171,8 @@ def parse_metadata(values: Mapping[str, str]) -> SubscriptionMetadata:
         support_url=text(KEY_SUPPORT_URL),
         title=_sanitize_title(text(KEY_PROFILE_TITLE)),
         web_page_url=text(KEY_WEB_PAGE_URL),
+        new_url=text(KEY_NEW_URL),
+        fallback_url=text(KEY_FALLBACK_URL),
     )
 
 
@@ -259,6 +269,10 @@ def apply_metadata(group: ProfileGroup, metadata: SubscriptionMetadata) -> None:
         group.sub_support_url = metadata.support_url.strip()
     if is_safe_web_page_url(metadata.web_page_url):
         group.sub_web_page_url = metadata.web_page_url.strip()
+    # new_url не сохраняется: это одноразовое предложение по итогам обновления.
+    # Запасной адрес нужен позже — когда обновление не удастся.
+    if is_acceptable_subscription_url(metadata.fallback_url.strip()):
+        group.sub_fallback_url = metadata.fallback_url.strip()
 
     title = metadata.title
     if title and group.name == default_subscription_name(group.subscription_url):
```

```diff
--- a/src/db/profiles.py
+++ b/src/db/profiles.py
@@ -74,6 +74,7 @@ class ProfileGroup(ConfigBase):
     sub_announce: str = ""
     sub_support_url: str = ""
     sub_web_page_url: str = ""
+    sub_fallback_url: str = ""  # предлагается, если обновление не удалось
 
 
 @dataclass
```

```diff
--- a/src/sub/updater.py
+++ b/src/sub/updater.py
@@ -50,6 +50,9 @@ class SubscriptionUpdater:
         # Возвращает адрес локального прокси, через который стоит попробовать
         # сначала (src/sub/route.py), или None — тогда запрос идёт напрямую.
         self._proxy_url = proxy_url
+        # Новый адрес, который провайдер сообщил при последнем update(). Сам
+        # адрес подписки не меняется: это решает пользователь.
+        self.new_url = ""
 
     def fetch(self, url: str) -> str:
         """Fetch subscription content."""
@@ -214,8 +217,11 @@ class SubscriptionUpdater:
             List of added profiles
         """
 
+        self.new_url = ""
         fetched = self.fetch_response(url)
         beans = self.parse(fetched.content)
+        metadata = read_metadata(fetched.headers, fetched.content)
+        self.new_url = metadata.new_url
         if not self._profiles:
             return beans
 
@@ -226,7 +232,7 @@ class SubscriptionUpdater:
         # До проверки списка: истёкшая подписка отдаёт ноль серверов, но срок и
         # объявление провайдера в ответе есть — их и нужно показать.
         if group is not None:
-            apply_metadata(group, read_metadata(fetched.headers, fetched.content))
+            apply_metadata(group, metadata)
 
         if beans:
             if clear_existing:
```

```diff
--- a/src/ui/logic/subscriptions_view.py
+++ b/src/ui/logic/subscriptions_view.py
@@ -154,3 +154,15 @@ def describe_update_error(error: BaseException, *, device_info_sent: bool = True
     if isinstance(error, requests.ConnectionError):
         return "нет связи с сервером подписки"
     return str(error)
+
+
+def describe_url_change(name: str, current_url: str, proposal: Any) -> tuple[str, str]:
+    """Heading and body of the "change the subscription address?" question."""
+    from src.sub.url_change import REASON_FALLBACK_URL
+
+    if proposal.reason == REASON_FALLBACK_URL:
+        lead = f"Обновить подписку «{name}» не удалось. Провайдер оставил запасной адрес:"
+    else:
+        lead = f"Провайдер подписки «{name}» сообщил новый адрес:"
+    body = f"{lead}\n{proposal.new_url}\n\nСейчас используется:\n{current_url}"
+    return "Сменить адрес подписки?", body
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_sub_url_change.py tests/test_ui_logic_subscriptions_view.py tests/test_sub_metadata.py tests/test_sub_updater.py -q`
Expected: 124 passed.

**Step 5: Написать GTK-тесты диалога**

```diff
--- a/tests/test_ui_application.py
+++ b/tests/test_ui_application.py
@@ -220,6 +220,88 @@ def test_the_default_updater_goes_through_the_running_proxy(adw_app):
     }
 
 
+# --- предложение сменить адрес подписки ---
+
+OLD_URL = "https://old.example/sub"
+NEW_URL = "https://new.example/sub"
+
+
+def _update_with_response_headers(adw_app, headers: dict[str, str]):
+    """Run the real updater against a canned HTTP response."""
+    from unittest.mock import Mock, patch
+
+    adw_app.activate()
+    group = adw_app.context.profiles.add_group("Подписка", is_subscription=True)
+    group.subscription_url = OLD_URL
+
+    body = "vless://11111111-1111-1111-1111-111111111111@h.example:443?type=tcp#A"
+    response = Mock()
+    response.text = body
+    response.content = body.encode("utf-8")
+    response.headers = headers
+    response.raise_for_status = Mock()
+
+    with patch("src.sub.updater.requests.get", return_value=response):
+        adw_app.update_subscription(group.id)
+        adw_app.wait_for_subscriptions_for_test()
+    return group
+
+
+def test_a_new_address_is_offered_but_not_applied(adw_app):
+    group = _update_with_response_headers(adw_app, {"new-url": NEW_URL})
+
+    assert adw_app.current_dialog is not None
+    assert NEW_URL in adw_app.current_dialog.get_body()
+    assert group.subscription_url == OLD_URL
+
+
+def test_confirming_switches_the_subscription_to_the_new_address(adw_app):
+    group = _update_with_response_headers(adw_app, {"new-url": NEW_URL})
+    updated: list[str] = []
+    adw_app.set_subscription_updater(lambda _gid, url: updated.append(url) or 1)
+
+    adw_app.current_dialog.emit("response", "change")
+    adw_app.wait_for_subscriptions_for_test()
+
+    assert group.subscription_url == NEW_URL
+    # После смены подписка сразу обновляется уже с нового адреса.
+    assert updated == [NEW_URL]
+
+
+def test_declining_keeps_the_old_address(adw_app):
+    group = _update_with_response_headers(adw_app, {"new-url": NEW_URL})
+
+    adw_app.current_dialog.emit("response", "cancel")
+
+    assert group.subscription_url == OLD_URL
+
+
+def test_an_ordinary_update_asks_nothing(adw_app):
+    _update_with_response_headers(adw_app, {})
+
+    assert adw_app.current_dialog is None
+
+
+def test_a_failed_update_offers_the_fallback_address(adw_app):
+    import requests
+
+    adw_app.activate()
+    group = adw_app.context.profiles.add_group("Подписка", is_subscription=True)
+    group.subscription_url = OLD_URL
+    group.sub_fallback_url = "https://backup.example/sub"
+
+    def failing(_group_id: int, _url: str) -> int:
+        raise requests.ConnectionError("blocked")
+
+    adw_app.set_subscription_updater(failing)
+    adw_app.update_subscription(group.id)
+    adw_app.wait_for_subscriptions_for_test()
+
+    assert adw_app.current_dialog is not None
+    assert "https://backup.example/sub" in adw_app.current_dialog.get_body()
+    assert group.subscription_url == OLD_URL
+
+
 # --- подключение и диалоги (этап 3) ---
 
 LINK = "vless://11111111-1111-1111-1111-111111111111@host.example:443?type=tcp#Новый"
```

**Step 6: Убедиться, что падают**

Run: `gtk_test tests/test_ui_application.py -k "address"`
Expected: 4 failed, 1 passed — диалог не появляется
(`assert None is not None`, `'NoneType' object has no attribute 'emit'`). `test_an_ordinary_update_asks_nothing` проходит
сразу.

**Step 7: Реализовать диалог и связку**

```diff
--- a/src/ui/dialogs/confirm.py
+++ b/src/ui/dialogs/confirm.py
@@ -1,4 +1,4 @@
-"""Destructive-action confirmation (GTK4)."""
+"""Confirmation dialogs (GTK4)."""
 
 from __future__ import annotations
 
@@ -12,6 +12,7 @@ gi.require_version("Adw", "1")
 from gi.repository import Adw
 
 DELETE = "delete"
+CHANGE = "change"
 CANCEL = "cancel"
 
 
@@ -42,3 +43,27 @@ def build_delete_confirmation(
 
     dialog.connect("response", responded)
     return dialog
+
+
+def build_url_change_confirmation(
+    heading: str,
+    body: str,
+    on_confirm: Callable[[], None],
+) -> Adw.AlertDialog:
+    """Ask whether to switch a subscription to the address its provider suggests."""
+    # Текст — не разметка (body-use-markup выключен по умолчанию): адрес
+    # приходит от провайдера.
+    dialog = Adw.AlertDialog(heading=heading, body=body)
+    dialog.add_response(CANCEL, "Оставить")
+    dialog.add_response(CHANGE, "Сменить")
+    dialog.set_response_appearance(CHANGE, Adw.ResponseAppearance.SUGGESTED)
+    # Адрес меняется только осознанно: Enter и Escape оставляют прежний.
+    dialog.set_default_response(CANCEL)
+    dialog.set_close_response(CANCEL)
+
+    def responded(_dialog, response: str) -> None:
+        if response == CHANGE:
+            on_confirm()
+
+    dialog.connect("response", responded)
+    return dialog
```

```diff
--- a/src/ui/application.py
+++ b/src/ui/application.py
@@ -18,7 +18,7 @@ from src.ui.logic.async_utils import run_in_background
 from src.ui.logic.latency import LatencyRunner
 from src.ui.logic.profiles_view import SortKey
 from src.ui.logic.status import ConnectionState
-from src.ui.logic.subscriptions_view import describe_update_error
+from src.ui.logic.subscriptions_view import describe_update_error, describe_url_change
 from src.ui.logic.version import app_version, core_version
 from src.ui.window import APP_ICON, MainWindow, load_css, load_icons
 
@@ -67,6 +67,9 @@ class TengaApplication(Adw.Application):
         self._latency_probe: Callable[[int], int] | None = None
         self._subscription_updater: Callable[[int, str], int] | None = None
         self._subscriptions_thread = None
+        # Предложения сменить адрес подписки: копятся в фоновом потоке,
+        # показываются в главном, по одному и только с подтверждением.
+        self._url_proposals: list = []
         self._profile_activation_handler: Callable[[int], None] | None = None
         self._connection_service = None
         self._connection_thread = None
@@ -526,9 +529,16 @@ class TengaApplication(Adw.Application):
         updater = self._subscription_updater or self._default_subscription_updater
         url = group.subscription_url
 
+        def work() -> int:
+            try:
+                return updater(group_id, url)
+            except Exception:
+                self._propose_fallback_url(group_id, url)
+                raise
+
         self.toast(f"Обновляю: {group.name}")
         self._subscriptions_thread = run_in_background(
-            lambda: updater(group_id, url),
+            work,
             on_done=self._on_subscriptions_updated,
             on_error=self._on_subscriptions_failed,
             name="tenga-subscription",
@@ -565,18 +575,59 @@ class TengaApplication(Adw.Application):
 
     def _default_subscription_updater(self, group_id: int, url: str) -> int:
         from src.sub.route import local_proxy_url
-        from src.sub.updater import update_subscription
+        from src.sub.updater import SubscriptionUpdater
+        from src.sub.url_change import REASON_NEW_URL, propose_url_change
 
         context = self.context
-        beans = update_subscription(
-            url,
+        updater = SubscriptionUpdater(
             config=context.config,
             profiles=context.profiles,
-            group_id=group_id,
             proxy_url=lambda: local_proxy_url(context.config, context.proxy_state),
         )
+        beans = updater.update(url, group_id)
+
+        proposal = propose_url_change(group_id, url, updater.new_url, REASON_NEW_URL)
+        if proposal is not None:
+            self._url_proposals.append(proposal)
         return len(beans)
 
+    def _propose_fallback_url(self, group_id: int, url: str) -> None:
+        """Queue the provider's fallback address after a failed update."""
+        from src.sub.url_change import REASON_FALLBACK_URL, propose_url_change
+
+        group = self.context.profiles.get_group(group_id)
+        if group is None:
+            return
+        proposal = propose_url_change(group_id, url, group.sub_fallback_url, REASON_FALLBACK_URL)
+        if proposal is not None:
+            self._url_proposals.append(proposal)
+
+    def _offer_url_change(self) -> None:
+        """Ask about one queued address change; the rest come back with the next update."""
+        if not self._url_proposals:
+            return
+        proposal = self._url_proposals[0]
+        self._url_proposals.clear()
+
+        group = self.context.profiles.get_group(proposal.group_id)
+        if group is None or self._window is None:
+            return
+
+        from src.ui.dialogs.confirm import build_url_change_confirmation
+
+        heading, body = describe_url_change(group.name, group.subscription_url, proposal)
+        self.present_dialog(
+            build_url_change_confirmation(heading, body, lambda: self._apply_url_change(proposal))
+        )
+
+    def _apply_url_change(self, proposal) -> None:
+        """Switch the subscription to the confirmed address and refresh it."""
+        group = self.context.profiles.get_group(proposal.group_id)
+        if group is None:
+            return
+        self.update_group(proposal.group_id, name=group.name, url=proposal.new_url)
+        self.update_subscription(proposal.group_id)
+
     def _ensure_latency_runner(self) -> LatencyRunner:
         if self._latency_runner is None:
             self._latency_runner = LatencyRunner(self._latency_probe or self._default_latency_probe)
@@ -709,6 +760,7 @@ class TengaApplication(Adw.Application):
                     total += updater(group_id, url)
                 except Exception as e:
                     logger.warning("Subscription %s failed: %s", group_id, describe_update_error(e))
+                    self._propose_fallback_url(group_id, url)
             return total
 
         self.toast(f"Обновляю подписки: {len(targets)}")
@@ -728,11 +780,13 @@ class TengaApplication(Adw.Application):
         if self._window is not None:
             self._window.refresh_pages()
         self.toast(f"Обновлено профилей: {total}")
+        self._offer_url_change()
 
     def _on_subscriptions_failed(self, error: BaseException) -> None:
         sent = self.context.config.sub_send_device_info
         reason = describe_update_error(error, device_info_sent=sent)
         self.toast(f"Не удалось обновить подписки: {reason}")
+        self._offer_url_change()
 
     def _toggle_search(self) -> None:
         if self._window is not None:
@@ -808,6 +862,7 @@ class TengaApplication(Adw.Application):
         self._latency_probe = None
         self._subscription_updater = None
         self._subscriptions_thread = None
+        self._url_proposals = []
         self._profile_activation_handler = None
         self._connection_service = None
         self._connection_thread = None
```

**Step 8: Убедиться, что проходят**

Run: `gtk_test tests/test_ui_application.py`
Expected: 62 passed.

Run: `uv run pytest -q`
Expected: `790 passed`.

**Step 9: Commit**

```bash
git add src/sub/url_change.py src/sub/metadata.py src/db/profiles.py src/sub/updater.py \
        src/ui/logic/subscriptions_view.py src/ui/dialogs/confirm.py src/ui/application.py \
        tests/test_sub_url_change.py tests/test_ui_logic_subscriptions_view.py \
        tests/test_ui_application.py
git commit -m "feat(sub): предлагать смену адреса подписки по подсказке провайдера"
```

---

### Task 15: Документация и итоговая проверка

**Files:**
- Modify: `docs/ru/profiles.md`, `docs/en/profiles.md` (раздел «Из подписки»)

**Step 1: Обновить документацию**

В документации сейчас написано, что подписки обновляются «по расписанию» —
такого в приложении нет. Если задачи 13 или 14 вычеркнуты, убери
соответствующие строки (про данные устройства; про `new-url`, `fallback-url`).

```diff
--- a/docs/ru/profiles.md
+++ b/docs/ru/profiles.md
@@ -31,9 +31,46 @@ python cli.py add "vless://..."
 
 Профили могут автоматически создаваться из подписок:
 
-- Подписки могут быть в формате base64 или plain text
+- Подписки могут быть в формате base64, plain text или готовым конфигом xray (JSON)
 - Профили группируются в специальные группы подписок
-- Подписки можно обновлять вручную или по расписанию
+- Подписки обновляются только вручную: кнопкой в строке подписки или `F5`
+
+#### Что происходит при обновлении
+
+- Профиль, который остался в ответе провайдера (то же имя, тип, сервер и порт),
+  обновляется на месте: его замер задержки, персональные настройки
+  маршрутизации и VPN сохраняются, подключённый профиль остаётся подключённым.
+  Пропавшие из ответа профили удаляются. Пустой ответ ничего не трогает.
+- Если подключён профиль в режиме системного прокси, подписка загружается
+  сначала через него, а при неудаче — напрямую. В режиме TUN запросы
+  приложения и так идут через туннель.
+- Название подписки можно не вводить: подставится хост адреса, а провайдер
+  сможет заменить его своим (`profile-title`). Введённое вручную название
+  провайдер не меняет.
+
+#### Сведения от провайдера
+
+Из заголовков ответа и строк `#ключ: значение` в теле читаются:
+
+| Ключ | Что показывается |
+|---|---|
+| `subscription-userinfo` | израсходованный трафик, лимит и срок действия |
+| `announce` | объявление провайдера (кнопка с «i» в строке подписки) |
+| `support-url` | пункт меню «Поддержка» (http, https или tg) |
+| `profile-web-page-url` | пункт меню «Страница подписки» (только https) |
+| `profile-title` | название подписки, если его не задал пользователь |
+| `new-url`, `fallback-url` | предложение сменить адрес — только с подтверждением |
+
+Значение может быть закодировано с префиксом `base64:`. Ключи, которыми
+провайдер управлял бы настройками клиента, не распознаются.
+
+#### Настройки → Подписки
+
+- **User-Agent.** По умолчанию `v2rayNG/1.8.23`: его узнают все провайдеры.
+- **Отправлять данные устройства.** Выключено. При включении провайдеру уходят
+  случайный идентификатор установки (`x-hwid`), название и версия системы,
+  модель компьютера. Нужны провайдерам, которые считают лимит устройств: без
+  них такой провайдер отвечает 403.
 
 ## Управление профилями
 
```

```diff
--- a/docs/en/profiles.md
+++ b/docs/en/profiles.md
@@ -31,9 +31,46 @@ python cli.py add "vless://..."
 
 Profiles can be automatically created from subscriptions:
 
-- Subscriptions can be in base64 or plain text format
+- Subscriptions can be base64, plain text or a ready xray config (JSON)
 - Profiles are grouped into special subscription groups
-- Subscriptions can be updated manually or on schedule
+- Subscriptions are updated manually only: the button in the subscription row or `F5`
+
+#### What an update does
+
+- A profile still present in the provider's response (same name, type, server
+  and port) is updated in place: its latency, per-profile routing and VPN
+  settings are kept, and a connected profile stays connected. Profiles missing
+  from the response are removed. An empty response changes nothing.
+- When a profile is connected in system proxy mode, the subscription is fetched
+  through it first and directly on failure. In TUN mode application requests
+  already go through the tunnel.
+- The subscription name is optional: the host of the address is used, and the
+  provider may replace it with its own (`profile-title`). A name typed by the
+  user is never replaced.
+
+#### Provider information
+
+Read from response headers and from `#key: value` lines in the body:
+
+| Key | What is shown |
+|---|---|
+| `subscription-userinfo` | used traffic, limit and expiry date |
+| `announce` | provider announcement (the "i" button in the subscription row) |
+| `support-url` | "Support" menu item (http, https or tg) |
+| `profile-web-page-url` | "Subscription page" menu item (https only) |
+| `profile-title` | subscription name, unless the user set one |
+| `new-url`, `fallback-url` | an offer to change the address, applied only after confirmation |
+
+A value may be encoded with the `base64:` prefix. Keys that would let the
+provider control client settings are not recognised.
+
+#### Settings → Subscriptions
+
+- **User-Agent.** `v2rayNG/1.8.23` by default: every provider recognises it.
+- **Send device information.** Off. When enabled, the provider receives a random
+  installation identifier (`x-hwid`), the OS name and version and the computer
+  model. Needed by providers that enforce a device limit: without it they
+  answer 403.
 
 ## Profile Management
 
```

**Step 2: Полный прогон**

Run: `uv run pytest -q`
Expected: `790 passed`.

Run: `python cli.py lint-all`
Expected: без замечаний.

Run:

```bash
gtk_test tests/test_ui_application.py tests/test_ui_window.py \
  tests/test_ui_pages_subscriptions.py tests/test_ui_dialogs_subscription.py \
  tests/test_ui_dialogs_settings.py \
  --deselect tests/test_ui_window.py::test_narrow_window_moves_the_switcher_down \
  --deselect tests/test_ui_window.py::test_default_size_comes_from_saved_geometry
```

Expected: 134 passed, 2 deselected.

**Step 3: Проверить руками**

Автотесты этого не покрывают. Что не удалось проверить — запиши в статус этапа
в дорожной карте.

1. **Обновление без смены id.** Подключиться к профилю из подписки, обновить
   подписку. Профиль остаётся подключённым и выделенным, его задержка в списке
   не сбросилась.
2. **Время обновления.** У подписки вместо «Никогда» — время.
3. **Метаданные.** На подписке, которая отдаёт `subscription-userinfo`: в
   строке видны трафик и срок; строка читается и в узком окне. Объявление
   открывается кнопкой «i»; пункты «Страница подписки» и «Поддержка» открывают
   браузер.
4. **Адрес с `&`.** Подписка с адресом вида `…?a=1&b=2` показывает адрес в
   подзаголовке.
5. **Маршрут.** В режиме системного прокси, с подключённым профилем: обновить
   подписку, в журнале xray (`logs/`) виден запрос к серверу подписки через
   inbound HTTP. Отключиться — обновление идёт напрямую.
6. **Отказ провайдера.** Если есть подписка с лимитом устройств — уведомление
   показывает текст провайдера, без адреса подписки.
7. **Настройки → Подписки.** Поле User-Agent пустое; введённое значение
   переживает перезапуск. (Задача 13) Включение «Отправлять данные устройства»
   записывает `sub_hwid` в `settings.json`, значение не меняется после
   перезапуска.
8. **(Задача 14) Смена адреса.** Проверяется только на провайдере, который
   отдаёт `new-url`; иначе — пометить как непроверенное.

**Step 4: Commit**

```bash
git add docs/ru/profiles.md docs/en/profiles.md
git commit -m "docs: описать обновление подписок и сведения от провайдера"
```

**Step 5: Обновить дорожную карту**

В `docs/plans/2026-10-03-network-parity-roadmap.md` — статус этапа 2, список
непроверенного из шага 3 и строка в журнале.

---

## Итог воспроизведения

Воспроизведение выполнено 2026-10-03 на чистом клоне базы (состояние после
этапа 1, 634 теста). Два скрипта:

- первый применял блоки «Создать файл» и `diff` из этого файла по порядку
  задач; после каждой задачи сверял дерево с коммитом прототипа, гонял
  `pytest`, `ruff check` и `ruff format --check`;
- второй для каждого шага `Run:` собирал состояние «предыдущая задача + файлы,
  которые к этому шагу уже изменены» и сверял итог pytest и сообщения об
  ошибках с `Expected:`.

| Проверка | Результат |
|---|---|
| Фрагменты `diff` | все легли `git apply` без правок |
| Дерево после каждой задачи | совпадает с прототипом, 15 из 15 |
| Красные шаги | все упали с указанными в плане числами и сообщениями (обычные и GTK) |
| Зелёные шаги | все прошли с указанными числами |
| `uv run pytest -q` | 643 → 645 → 648 → 667 → 702 → 722 → 722 → 722 → 731 → 731 → 747 → 747 → 759 → 790 → 790 passed по задачам (было 634) |
| Все GTK-тесты под Broadway в конце | 227 passed, 2 failed — те же два теста геометрии окна, что и на базе (там 206 passed, 2 failed) |
| `ruff check`, `ruff format --check` | чисто после каждой задачи |

Что не проверено и остаётся на ручную проверку (задача 15, шаг 3):

- живой провайдер: заголовки, тело с `#key:`, отказ 403/429, `new-url` —
  только заглушки `requests` в тестах;
- загрузка через настоящий HTTP-inbound ядра: маршрут проверен на заглушках,
  настоящее ядро в этих тестах не запускается;
- внешний вид строки подписки, кнопки объявления и страницы настроек — тесты
  проверяют виджеты, но не на экране;
- открытие ссылок в браузере (в тестах подменён `_launch_uri` окна).

Оговорки:

- Числа `passed` верны для состояния после этапа 1. После этапов 3 и 4 в общих
  файлах тестов станет больше; для новых файлов этого плана числа останутся
  теми же.
- Этапы 3 и 4 при воспроизведении применены не были: совместимость планов
  проверяется отдельно, слиянием веток прототипов.
