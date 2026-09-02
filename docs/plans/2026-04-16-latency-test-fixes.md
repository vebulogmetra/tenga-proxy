# Latency Test Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Исправить тест задержки так, чтобы он проверял реальную работоспособность маршрута через Xray (а не только TCP connect до сервера профиля) и перестал показывать ложные 0-1 ms при активном подключении.

**Architecture:** Убираем прямой `socket.connect()` из UI и переводим `Тест задержки` на единый e2e-механизм через локальный HTTP-inbound Xray и запрос к внешнему `generate_204` endpoint. Для теста выбранного профиля поднимаем временный Xray-конфиг без TUN (чтобы не конфликтовать с активной сессией), но с тем же outbound профиля и релевантными routing/DNS параметрами. Результат считаем как медиану нескольких проб.

**Tech Stack:** Python 3.11, GTK UI, xray-core subprocess, requests, pytest.

---

### Task 1: Зафиксировать регрессии тестами (red stage)

**Files:**
- Create: `tests/test_core_latency_probe.py`
- Modify: `src/core/xray_manager.py`

**Step 1: Write failing tests for realistic latency probing**

Покрыть сценарии:
- возвращается `-1`, если Xray не запущен/не отвечает;
- одиночная аномальная проба не доминирует в результате;
- итоговая задержка считается как медиана успешных проб;
- проверка идет через HTTP proxy endpoint, а не raw TCP socket.

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_core_latency_probe.py -v`
Expected: FAIL (новый API/логика еще не реализованы).

**Step 3: Add minimal scaffolding in xray manager**

Добавить заглушки/сигнатуры новых методов для multi-probe задержки.

**Step 4: Re-run tests**

Run: `uv run pytest tests/test_core_latency_probe.py -v`
Expected: часть тестов все еще FAIL, но импорт/инициализация проходят.

**Step 5: Commit (test scaffold)**

```bash
git add tests/test_core_latency_probe.py src/core/xray_manager.py
git commit -m "test: add red tests for real latency probing"
```

### Task 2: Реализовать реальный multi-probe latency в XrayManager

**Files:**
- Modify: `src/core/xray_manager.py`
- Test: `tests/test_core_latency_probe.py`

**Step 1: Implement `test_delay_realistic` (или эквивалент)**

Требования:
- использовать `time.perf_counter_ns()` для измерения;
- выполнять 3 пробы через локальный HTTP proxy (`http://127.0.0.1:<http_port>`);
- к URL добавлять cache-buster query param;
- в расчет брать только успешные HTTP-ответы (2xx-4xx, как сейчас);
- финальное значение = медиана успешных проб, иначе `-1`.

**Step 2: Keep backward compatibility**

Существующий `test_delay(...)` либо:
- делегирует на новый метод с `probes=1`, либо
- помечается internal-only и заменяется вызовами нового API.

**Step 3: Run focused tests**

Run: `uv run pytest tests/test_core_latency_probe.py -v`
Expected: PASS.

**Step 4: Run adjacent tests for safety**

Run: `uv run pytest tests/test_core_context.py tests/test_core_monitor.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/core/xray_manager.py tests/test_core_latency_probe.py
git commit -m "core: implement realistic multi-probe xray latency test"
```

### Task 3: Сделать e2e latency-test для выбранного профиля через временный Xray

**Files:**
- Modify: `src/ui/app.py`
- Modify: `src/core/xray_manager.py`
- Create: `tests/test_ui_app_latency_flow.py`

**Step 1: Write failing tests for app-level latency flow**

Покрыть:
- для неактивного профиля поднимается временный XrayManager;
- временный конфиг не содержит TUN inbound (нет конфликта с `xray0`);
- используется outbound выбранного профиля;
- после теста временный процесс гарантированно останавливается.

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_ui_app_latency_flow.py -v`
Expected: FAIL.

**Step 3: Implement temporary-config latency path**

В `src/ui/app.py`:
- добавить метод сборки облегченного latency-конфига из профиля (reuse текущей логики `_create_config`, но с отдельными inbounds для latency-теста);
- добавить метод `test_profile_latency(profile_id, timeout_ms=..., probes=3) -> int`;
- использовать отдельный `XrayManager` instance для временного прогона.

**Step 4: Re-run tests**

Run: `uv run pytest tests/test_ui_app_latency_flow.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/ui/app.py src/core/xray_manager.py tests/test_ui_app_latency_flow.py
git commit -m "ui: run profile latency test through temporary xray e2e path"
```

### Task 4: Переключить кнопку `Тест задержки` в MainWindow на новый app callback

**Files:**
- Modify: `src/ui/main_window.py`
- Modify: `src/ui/app.py`
- Test: `tests/test_ui_app_latency_flow.py`

**Step 1: Write failing integration-style test**

Проверить, что UI не вызывает больше прямой `socket.connect()` путь.

**Step 2: Replace direct socket latency method**

В `src/ui/main_window.py`:
- удалить/деактивировать `_test_profile_latency` на raw socket;
- добавить callback (например, `set_on_test_latency`) и использовать его в `_on_test_delay_clicked`;
- сохранить текущее поведение UI-индикаторов (`...`, `Ошибка`, `N ms`).

В `src/ui/app.py`:
- прокинуть callback в `MainWindow` рядом с `set_on_connect/set_on_disconnect`.

**Step 3: Run focused tests**

Run: `uv run pytest tests/test_ui_app_latency_flow.py -v`
Expected: PASS.

**Step 4: Run existing tests likely affected by UI wiring**

Run: `uv run pytest tests/test_core_context.py tests/test_db_profiles.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/ui/main_window.py src/ui/app.py tests/test_ui_app_latency_flow.py
git commit -m "ui: route delay button through real app latency callback"
```

### Task 5: Финальная верификация и ручной сценарий по двум багам

**Files:**
- Modify (if needed): `docs/ru/*` или `README` раздел с описанием теста задержки

**Step 1: Run full automated checks**

Run: `make test`
Expected: PASS.

**Step 2: Manual scenario for Bug 1**

Сценарий:
- выбрать проблемный профиль (`Reality VPN#56 + AISO`);
- нажать `Тест задержки`;
- убедиться, что тест использует реальный e2e путь (по логам есть HTTP-запрос через proxy inbound).

Ожидание: при нерабочем профиле результат `Ошибка`/`-1`, а не “успешный” пинг порта.

**Step 3: Manual scenario for Bug 2**

Сценарий:
- подключить рабочий профиль;
- несколько раз нажать `Тест задержки`.

Ожидание: нет систематических 0-1 ms для внешнего endpoint; значения стабильны и правдоподобны.

**Step 4: Final commit**

```bash
git add docs/ru
git commit -m "docs: clarify latency test behavior and expected semantics"
```

**Step 5: Prepare PR summary**

В PR отдельно отметить:
- что `Тест задержки` теперь e2e через Xray;
- что raw TCP connect удален из UI пути;
- что добавлен multi-probe median для устойчивого результата.
