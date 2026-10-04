# Сетевой слой, этап 1: протоколы и транспорт — план реализации

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Довести разбор ссылок и сборку outbound'ов до уровня Android-версии:
починить Shadowsocks, убрать несовместимый ALPN, добавить port hopping и brutal
для hysteria2, фрагментацию TLS и mux.

**Architecture:** Всё, что относится к одному профилю, остаётся в его bean'е
(`src/fmt/`): разбор ссылки и `build_outbound()`. Всё, что накладывается на любой
профиль из общих настроек (фрагментация, mux), живёт в новом модуле
`src/core/transport_tweaks.py` и вызывается из `build_session_config` — через
него же строится конфиг замера задержки, поэтому рабочее подключение и замер
не расходятся. Схему конфига знает только ядро, поэтому каждое изменение
закрепляется тестом, который прогоняет результат через настоящий `xray -test`.

**Tech Stack:** Python 3.11, xray-core 26.9.9 (обновляется в задаче 3), pytest,
ruff, GTK 4 + libadwaita (только задача 6).

Дорожная карта всех этапов — `2026-10-03-network-parity-roadmap.md`.

---

## Что проверено до написания плана

Проверено 2026-10-03 запуском, а не предположено.

1. **Весь код этого плана, кроме задачи 6, прототипирован** во временной копии
   проекта и затем применён из этого файла к чистой копии: 634 теста проходят
   на ядре 26.9.9, `ruff check` и `ruff format`
   чистые. Фрагменты ниже — выгрузка из прототипа, а не набросок.
2. **Ядро.** `core/bin/xray` — 26.3.27, это последний *стабильный* релиз
   (`/releases/latest`). Всё новее — пререлизы. Android собран на 26.9.9
   (коммит `52a412d`).

   | Конфиг | 26.3.27 | 26.9.9 |
   |---|---|---|
   | маска `fragment`, mux | принят | принят |
   | hysteria2 с `udphop` | `unknown config id: udphop` | принят |
   | Shadowsocks `none` / `plain` | принят | отвергнут |
   | Shadowsocks с потоковым шифром | отвергнут | отвергнут |
   | 2022-blake3 с ключом не той длины | отвергнут | отвергнут |

   Поэтому обновление ядра стоит **перед** задачей про hysteria2 и после
   Shadowsocks: задачи 1–2 от версии не зависят.
3. **Парсер Shadowsocks сломан сильнее, чем казалось.** Самая частая форма
   ссылки, SIP002 (`ss://base64(method:password)@host:port`), разбирается так:
   метод — сама base64-строка, пароль пустой. Ключ 2022-blake3 с `+`, `/`, `=`
   не разбирается вовсе, а percent-кодированный попадает в конфиг
   закодированным. Работает только legacy-форма, где закодирована вся ссылка.
4. **Hysteria2.** Ссылка `host:443,20000-50000` не разбирается: `urlparse`
   бросает при чтении порта. `mport`, `upmbps`, `downmbps` игнорируются. При
   наличии `?fm=` параметр `obfs` отбрасывается целиком.
5. **`xray -test` на TUN-конфиге трогает систему.** На 26.3.27 он пытается
   создать интерфейс. На машине разработчика обычно запущен установленный Tenga
   с интерфейсом `xray0` — тесты этого плана используют только SOCKS-inbound.

## Соглашения

- Рабочая ветка: `feature/network-phase1` от `develop`.
- Тесты: `uv run pytest <путь> -q`. Полный набор: `uv run pytest -q`.
- Перед каждым коммитом: `python cli.py lint-all`.
- Сообщения коммитов — как в истории: `fix(fmt): …`, `feat(core): …`, по-русски.
- Фрагменты `diff` ниже применяются к файлу в том виде, в каком он лежит после
  задачи 0. Если контекст не совпал — файл изменился, сверяйся с кодом.

---

### Task 0: Зафиксировать уже сделанные исправления

В рабочем дереве лежат незакоммиченные правки предыдущего шага: `allowInsecure`,
транспорт h2, TCP с HTTP-заголовком, `spiderX`, DoH и QUIC-sniffing. План
строится поверх них.

**Step 1: Создать ветку**

```bash
git switch -c feature/network-phase1
```

**Step 2: Убедиться, что набор зелёный**

Run: `uv run pytest -q`
Expected: `534 passed`.

**Step 3: Закоммитить двумя коммитами**

```bash
git add src/fmt/stream.py tests/test_fmt_stream.py tests/test_fmt_xray_config_valid.py
git commit -m "fix(fmt): не отдавать ядру allowInsecure, h2 и битый spiderX"

git add src/core/config_builder.py src/core/proxy_mode.py src/ui/dialogs/settings.py \
        tests/test_core_config_builder.py tests/test_core_proxy_mode.py
git commit -m "fix(core): писать DoH URL-строкой и разбирать QUIC в sniffing"
```

---

### Task 1: ALPN для ws и httpupgrade

WebSocket и HTTP Upgrade работают только поверх HTTP/1.1. Подписки часто отдают
`alpn=h2,http/1.1` для ws-профилей; если сервер согласует h2, апгрейд не
состоится. Фильтр ставится при сборке конфига: в профиле и в share-ссылке ALPN
остаётся исходным.

**Files:**
- Modify: `src/fmt/stream.py` (`build_tls`)
- Test: `tests/test_fmt_stream.py`

**Step 1: Написать падающие тесты**

Дописать в конец `tests/test_fmt_stream.py`:

```python
@pytest.mark.parametrize("network", ["ws", "httpupgrade"])
def test_build_tls_drops_h2_alpn_for_http1_only_transports(network):
    """ws и httpupgrade работают только поверх HTTP/1.1: h2 в ALPN ломает апгрейд."""
    stream = StreamSettings(network=network, security="tls", alpn="h2,http/1.1,h3")
    tls = stream.build_tls()
    assert tls is not None
    assert tls["alpn"] == ["http/1.1"]


def test_build_tls_omits_alpn_when_nothing_is_left():
    stream = StreamSettings(network="ws", security="tls", alpn="h2")
    tls = stream.build_tls()
    assert tls is not None
    assert "alpn" not in tls


@pytest.mark.parametrize("network", ["tcp", "grpc", "xhttp"])
def test_build_tls_keeps_h2_alpn_for_other_transports(network):
    stream = StreamSettings(network=network, security="tls", alpn="h2,http/1.1")
    tls = stream.build_tls()
    assert tls is not None
    assert tls["alpn"] == ["h2", "http/1.1"]
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_fmt_stream.py -q`
Expected: 3 failed (`ws`, `httpupgrade`, `omits_alpn`), остальные passed. В
сообщении — `['h2', 'http/1.1', 'h3'] == ['http/1.1']`.

**Step 3: Реализовать**

```diff
--- a/src/fmt/stream.py
+++ b/src/fmt/stream.py
@@ -9,6 +9,9 @@
 
 logger = logging.getLogger("tenga.fmt.stream")
 
+HTTP1_ONLY_NETWORKS = ("ws", "httpupgrade")
+HTTP2_PLUS_ALPN = ("h2", "h3")
+
 
 def parse_json_object(raw: str) -> dict[str, Any]:
     """Разобрать сырой JSON-объект из share-ссылки.
@@ -184,8 +187,14 @@
             # xray-core uses certificates array
             tls_settings["certificates"] = [{"certificate": self.certificate.strip()}]
 
-        if self.alpn.strip():
-            tls_settings["alpn"] = [x.strip() for x in self.alpn.split(",") if x.strip()]
+        alpn = [x.strip() for x in self.alpn.split(",") if x.strip()]
+        # ws и httpupgrade апгрейдятся только поверх HTTP/1.1: если сервер согласует
+        # h2 по ALPN, апгрейд не состоится. Пустой список не пишем — ядро само
+        # выберет http/1.1.
+        if self.network in HTTP1_ONLY_NETWORKS:
+            alpn = [x for x in alpn if x not in HTTP2_PLUS_ALPN]
+        if alpn:
+            tls_settings["alpn"] = alpn
 
         # uTLS fingerprint
         if self.utls_fingerprint:
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_fmt_stream.py -q`
Expected: все passed.

**Step 5: Commit**

```bash
git add src/fmt/stream.py tests/test_fmt_stream.py
git commit -m "fix(fmt): убирать h2 и h3 из ALPN для ws и httpupgrade"
```

---

### Task 2: Парсер Shadowsocks

Разбор переписывается целиком: два прежних метода (`_try_parse_base64_format`,
`_try_parse_url_format`) угадывали формат по косвенным признакам и ошибались на
SIP002.

Правила:

- `@` в теле ссылки — SIP002, иначе legacy (вся ссылка в base64).
- Учётка SIP002: если в ней есть `:` — открытый текст с percent-кодированием,
  иначе base64. `unquote`, а не `unquote_plus`: `+` — символ base64-ключа.
- base64 декодируется **строго**. Нестрогий декодер Python молча выбрасывает
  чужие символы и возвращает мусор вместо ошибки — из-за этого и путались формы.
- Метод приводится к нижнему регистру.
- Ключ 2022-blake3 неверной длины — ссылка не разбирается: ядро на нём отвергает
  весь конфиг. Это испорченная ссылка, показывать такой профиль незачем.
- Неподдерживаемый метод и SIP003-плагин — профиль разбирается, но
  `build_outbound()` бросает `ValueError` с понятной причиной (как транспорт h2).
  `build_core_obj_xray()` превращает её в поле `error`.

**Files:**
- Modify: `src/fmt/protocols/shadowsocks.py`
- Create: `tests/test_fmt_shadowsocks.py`
- Modify: `tests/test_fmt_xray_config_valid.py`

**Step 1: Написать падающие тесты**

Создать `tests/test_fmt_shadowsocks.py`:

```python
"""Разбор ссылок Shadowsocks: SIP002, legacy и 2022-blake3."""

import base64

import pytest

from src.fmt import parse_link
from src.fmt.protocols import ShadowsocksBean

KEY_16 = base64.b64encode(bytes(range(16))).decode()
# Ключ подобран так, чтобы в base64 были «+», «/» и «=»: на них и ломался разбор.
KEY_32 = base64.b64encode(bytes([0xFB, 0xEF, 0xFF] * 10 + [1, 2])).decode()


def b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def parse(link: str) -> ShadowsocksBean:
    bean = parse_link(link)
    assert isinstance(bean, ShadowsocksBean), link
    return bean


def test_key_fixture_exercises_special_characters():
    assert "+" in KEY_32 and "/" in KEY_32 and KEY_32.endswith("=")


def test_sip002_base64_userinfo():
    """Самая частая форма: ss://base64(method:password)@host:port#name."""
    bean = parse(f"ss://{b64url('aes-256-gcm:pass')}@1.2.3.4:8388#My%20Server")

    assert bean.method == "aes-256-gcm"
    assert bean.password == "pass"
    assert bean.server_address == "1.2.3.4"
    assert bean.server_port == 8388
    assert bean.name == "My Server"


def test_sip002_userinfo_in_standard_base64_with_padding():
    userinfo = base64.b64encode(b"chacha20-ietf-poly1305:p+ss/w?rd").decode()
    bean = parse(f"ss://{userinfo}@example.com:443#n")

    assert bean.method == "chacha20-ietf-poly1305"
    assert bean.password == "p+ss/w?rd"
    assert bean.server_address == "example.com"


def test_legacy_fully_encoded_link():
    bean = parse("ss://" + b64url("aes-256-gcm:pass@1.2.3.4:8388") + "#n")

    assert (bean.method, bean.password) == ("aes-256-gcm", "pass")
    assert (bean.server_address, bean.server_port) == ("1.2.3.4", 8388)


def test_password_may_contain_colon_and_at():
    bean = parse(f"ss://{b64url('aes-256-gcm:p@ss:word')}@1.2.3.4:8388")
    assert bean.password == "p@ss:word"


def test_ipv6_server():
    bean = parse(f"ss://{b64url('aes-256-gcm:pass')}@[2001:db8::1]:8388#n")
    assert (bean.server_address, bean.server_port) == ("2001:db8::1", 8388)


def test_method_is_lowercased():
    bean = parse(f"ss://{b64url('AES-256-GCM:pass')}@1.2.3.4:8388")
    assert bean.method == "aes-256-gcm"


def test_2022_plain_key_keeps_plus():
    """«+» в ключе не должен стать пробелом."""
    bean = parse(f"ss://2022-blake3-aes-256-gcm:{KEY_32}@1.2.3.4:8388#n")

    assert bean.method == "2022-blake3-aes-256-gcm"
    assert bean.password == KEY_32


def test_2022_percent_encoded_key_is_decoded():
    from urllib.parse import quote

    bean = parse(f"ss://2022-blake3-aes-256-gcm:{quote(KEY_32, safe='')}@1.2.3.4:8388#n")
    assert bean.password == KEY_32


def test_2022_base64_userinfo():
    bean = parse(f"ss://{b64url('2022-blake3-aes-128-gcm:' + KEY_16)}@1.2.3.4:8388")
    assert (bean.method, bean.password) == ("2022-blake3-aes-128-gcm", KEY_16)


def test_2022_multi_user_key():
    password = f"{KEY_32}:{KEY_32}"
    bean = parse(f"ss://2022-blake3-aes-256-gcm:{password}@1.2.3.4:8388")
    assert bean.password == password


@pytest.mark.parametrize(
    "password",
    [KEY_16, "not-base64!", f"{KEY_32}:{KEY_16}"],
    ids=["wrong-length", "not-base64", "second-key-wrong-length"],
)
def test_2022_broken_key_is_rejected(password):
    """Ядро на таком ключе отвергает весь конфиг («bad key»)."""
    assert parse_link(f"ss://2022-blake3-aes-256-gcm:{password}@1.2.3.4:8388") is None


@pytest.mark.parametrize(
    "link",
    [
        "ss://",
        "ss://@1.2.3.4:8388",
        f"ss://{b64url('aes-256-gcm')}@1.2.3.4:8388",
        f"ss://{b64url('aes-256-gcm:')}@1.2.3.4:8388",
        f"ss://{b64url('aes-256-gcm:pass')}@1.2.3.4",
        f"ss://{b64url('aes-256-gcm:pass')}@1.2.3.4:port",
    ],
    ids=["empty", "no-userinfo", "no-password-part", "empty-password", "no-port", "bad-port"],
)
def test_malformed_links_are_rejected(link):
    assert parse_link(link) is None


def test_plugin_is_parsed():
    bean = parse(
        f"ss://{b64url('aes-256-gcm:pass')}@1.2.3.4:8388/?plugin=obfs-local%3Bobfs%3Dhttp#n"
    )
    assert bean.plugin == "obfs-local;obfs=http"
    assert bean.server_port == 8388


@pytest.mark.parametrize("method", ["aes-256-cfb", "rc4-md5", "none", "plain"])
def test_unsupported_method_reports_build_error(method):
    bean = parse(f"ss://{b64url(method + ':pass')}@1.2.3.4:8388")

    result = bean.build_core_obj_xray()

    assert method in result["error"]
    assert result["outbound"] == {}


def test_plugin_reports_build_error():
    bean = parse(f"ss://{b64url('aes-256-gcm:pass')}@1.2.3.4:8388?plugin=v2ray-plugin")
    assert "SIP003" in bean.build_core_obj_xray()["error"]


@pytest.mark.parametrize(
    "link",
    [
        f"ss://{b64url('aes-256-gcm:pass')}@1.2.3.4:8388#Name%20One",
        f"ss://2022-blake3-aes-256-gcm:{KEY_32}@example.com:443#n",
    ],
    ids=["aead", "2022"],
)
def test_share_link_roundtrip(link):
    original = parse(link)
    restored = parse(original.to_share_link())

    assert restored.method == original.method
    assert restored.password == original.password
    assert restored.server_address == original.server_address
    assert restored.server_port == original.server_port
    assert restored.name == original.name
```

Добавить ссылки в `tests/test_fmt_xray_config_valid.py`:

```diff
--- a/tests/test_fmt_xray_config_valid.py
+++ b/tests/test_fmt_xray_config_valid.py
@@ -6,4 +6,5 @@
 """
 
+import base64
 import json
 import shutil
@@ -24,4 +25,6 @@
 
 FM = quote('{"salamander":{"password":"secret"}}')
+# 32 байта; в base64 есть «+», «/» и «=» — в ссылке они percent-кодируются.
+SS_2022_KEY = quote(base64.b64encode(bytes([0xFB, 0xEF, 0xFF] * 10 + [1, 2])).decode(), safe="")
 EXTRA = quote('{"scMaxEachPostBytes":1000000,"xmux":{"maxConcurrency":"16-32"},"seqKey":"abc"}')
 
@@ -56,4 +65,6 @@
         "&pbk=7xhH4b_VkliBxGULljcyPOH-bYUA2dl-XAdZAsfhk04&sid=ab&spx=spider&fp=chrome#RS"
     ),
+    "shadowsocks_aead": "ss://YWVzLTI1Ni1nY206cGFzcw@127.0.0.1:8388#SS",
+    "shadowsocks_2022": f"ss://2022-blake3-aes-256-gcm:{SS_2022_KEY}@127.0.0.1:8388#SS22",
     "tcp_http_header": (
         "vless://11111111-1111-1111-1111-111111111111@127.0.0.1:443"
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_fmt_shadowsocks.py tests/test_fmt_xray_config_valid.py -q`
Expected: большинство тестов `test_fmt_shadowsocks.py` failed (legacy-форма и
часть отказов проходят и сейчас), `shadowsocks_aead` и `shadowsocks_2022` failed.

**Step 3: Реализовать**

```diff
--- a/src/fmt/protocols/shadowsocks.py
+++ b/src/fmt/protocols/shadowsocks.py
@@ -3,11 +3,61 @@
 import base64
 from dataclasses import dataclass, field
 from typing import Any
-from urllib.parse import parse_qs, quote, unquote, urlparse
+from urllib.parse import parse_qs, quote, unquote, urlsplit
 
 from src.fmt.base import ProxyBean
 from src.fmt.stream import StreamSettings
 
+# Длина ключа 2022-blake3 в байтах. Ядро декодирует ключ при сборке конфига и на
+# ключе другой длины отвергает конфиг целиком («bad key»).
+KEY_LENGTH_2022 = {
+    "2022-blake3-aes-128-gcm": 16,
+    "2022-blake3-aes-256-gcm": 32,
+    "2022-blake3-chacha20-poly1305": 32,
+}
+
+# Методы, которые принимает xray-core: AEAD и 2022-blake3. Потоковые шифры и
+# none/plain ядро отвергает вместе со всем конфигом.
+SUPPORTED_METHODS = frozenset(
+    {
+        "aes-128-gcm",
+        "aes-256-gcm",
+        "chacha20-poly1305",
+        "chacha20-ietf-poly1305",
+        "xchacha20-poly1305",
+        "xchacha20-ietf-poly1305",
+        *KEY_LENGTH_2022,
+    }
+)
+
+
+def _decode_base64(data: str) -> str | None:
+    """Строго декодировать base64 любого из двух алфавитов.
+
+    Чужой символ или битый UTF-8 означают «это не base64»: нестрогий декодер
+    молча выбрасывает лишние символы и возвращает мусор вместо ошибки.
+    """
+    padded = data.replace("-", "+").replace("_", "/")
+    padded += "=" * (-len(padded) % 4)
+    try:
+        return base64.b64decode(padded, validate=True).decode("utf-8")
+    except (ValueError, UnicodeDecodeError):
+        return None
+
+
+def _is_valid_2022_key(method: str, password: str) -> bool:
+    """У 2022-blake3 каждый ключ (их несколько через «:») — base64 нужной длины."""
+    expected = KEY_LENGTH_2022.get(method)
+    if expected is None:
+        return True
+    for key in password.split(":"):
+        try:
+            if len(base64.b64decode(key, validate=True)) != expected:
+                return False
+        except ValueError:
+            return False
+    return True
+
 
 @dataclass
 class ShadowsocksBean(ProxyBean):
@@ -33,111 +83,48 @@
         self.uot_version = value
 
     def try_parse_link(self, link: str) -> bool:
-        """Parse Shadowsocks share link."""
-        if not link.startswith("ss://"):
+        """Parse Shadowsocks share link (SIP002 и legacy)."""
+        if not link.lower().startswith("ss://"):
             return False
 
         try:
-            # Remove prefix
-            link_body = link[5:]
-            if self._try_parse_base64_format(link_body):
-                return True
-            return self._try_parse_url_format(link_body)
-
-        except Exception as e:
-            print(f"Error parsing Shadowsocks link: {e}")
-            return False
+            body, _, fragment = link[5:].partition("#")
+            body, _, query = body.partition("?")
+            body = body.rstrip("/")
+
+            if "@" in body:
+                userinfo, _, hostport = body.rpartition("@")
+                # SIP002: учётка AEAD — base64(method:password), у 2022-blake3 —
+                # открытый текст с percent-кодированием. unquote, а не unquote_plus:
+                # «+» — законный символ base64-ключа, пробелом он стать не должен.
+                credentials = None if ":" in userinfo else _decode_base64(userinfo)
+                if credentials is None or ":" not in credentials:
+                    credentials = unquote(userinfo)
+            else:
+                # Legacy: вся ссылка — base64(method:password@host:port).
+                decoded = _decode_base64(body)
+                if decoded is None or "@" not in decoded:
+                    return False
+                credentials, _, hostport = decoded.rpartition("@")
+
+            if ":" not in credentials:
+                return False
+            method, password = credentials.split(":", 1)
+
+            # urlsplit разбирает и IPv6 в квадратных скобках.
+            address = urlsplit("//" + hostport)
+            if not address.hostname or not address.port:
+                return False
+
+            self.method = method.strip().lower()
+            self.password = password
+            self.server_address = address.hostname
+            self.server_port = address.port
+            self.name = unquote(fragment)
+            self.plugin = parse_qs(query).get("plugin", [""])[0]
 
-    def _try_parse_base64_format(self, link_body: str) -> bool:
-        """Parse base64 format: ss://base64#name."""
-        if "@" in link_body and ":" in link_body[:20]:
-            return False
-
-        try:
-            encoded = link_body
-            if "#" in encoded:
-                parts = encoded.split("#", 1)
-                encoded = parts[0]
-                self.name = unquote(parts[1]) if len(parts) > 1 else ""
-
-            padding = 4 - len(encoded) % 4
-            if padding != 4:
-                encoded += "=" * padding
-
-            decoded = base64.urlsafe_b64decode(encoded).decode("utf-8", errors="ignore")
-
-            # Format: method:password@server:port
-            if "@" in decoded:
-                method_pass, server_port = decoded.rsplit("@", 1)
-                if ":" in method_pass:
-                    self.method, self.password = method_pass.split(":", 1)
-                if ":" in server_port:
-                    self.server_address, port_str = server_port.rsplit(":", 1)
-                    self.server_port = int(port_str)
-                return bool(self.server_address and self.password)
-
-            return False
-        except:
-            return False
-
-    def _try_parse_url_format(self, link_body: str) -> bool:
-        """Parse URL format."""
-        try:
-            url = urlparse("ss://" + link_body)
-
-            if url.hostname:
-                self.server_address = url.hostname
-            if url.port:
-                self.server_port = url.port
-
-            # Username may contain method:password or be base64
-            if url.username:
-                if ":" in url.username:
-                    parts = url.username.split(":", 1)
-                    self.method = parts[0]
-
-                    # For 2022 methods
-                    if self.method.startswith("2022-"):
-                        if url.password:
-                            self.password = url.password
-                    else:
-                        # Standard base64 password decoding
-                        try:
-                            password_encoded = parts[1]
-                            padding = 4 - len(password_encoded) % 4
-                            if padding != 4:
-                                password_encoded += "=" * padding
-                            self.password = base64.urlsafe_b64decode(password_encoded).decode(
-                                "utf-8"
-                            )
-                        except:
-                            self.password = parts[1]
-                else:
-                    # Only method, password separately
-                    self.method = url.username
-                    if url.password:
-                        try:
-                            password_encoded = url.password
-                            padding = 4 - len(password_encoded) % 4
-                            if padding != 4:
-                                password_encoded += "=" * padding
-                            self.password = base64.urlsafe_b64decode(password_encoded).decode(
-                                "utf-8"
-                            )
-                        except:
-                            self.password = url.password
-
-            if url.fragment:
-                self.name = unquote(url.fragment)
-
-            # Plugin from query
-            if url.query:
-                params = parse_qs(url.query)
-                if "plugin" in params:
-                    self.plugin = params["plugin"][0]
-
-            return bool(self.server_address)
-        except:
+            return bool(self.password) and _is_valid_2022_key(self.method, self.password)
+        except Exception:
             return False
 
     def to_share_link(self) -> str:
@@ -166,6 +153,13 @@
 
     def build_outbound(self, skip_cert: bool = False) -> dict[str, Any]:
         """Build outbound for xray-core."""
+        # Неподдерживаемый метод ядро отвергает вместе со всем конфигом, а
+        # SIP003-плагинов в нём нет: без плагина сервер профиля не ответит.
+        if self.method.lower() not in SUPPORTED_METHODS:
+            raise ValueError(f"Метод Shadowsocks «{self.method}» не поддерживается xray-core")
+        if self.plugin:
+            raise ValueError("Плагины Shadowsocks (SIP003) не поддерживаются xray-core")
+
         outbound: dict[str, Any] = {
             "protocol": "shadowsocks",
             "settings": {
@@ -173,7 +167,7 @@
                     {
                         "address": self.server_address,
                         "port": self.server_port,
-                        "method": self.method,
+                        "method": self.method.lower(),
                         "password": self.password,
                     }
                 ]
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_fmt_shadowsocks.py tests/test_fmt_xray_config_valid.py tests/test_fmt_base.py tests/test_db_profiles.py tests/test_sub_updater.py -q`
Expected: все passed.

**Step 5: Commit**

```bash
git add src/fmt/protocols/shadowsocks.py tests/test_fmt_shadowsocks.py tests/test_fmt_xray_config_valid.py
git commit -m "fix(fmt): разбирать SIP002 и ключи 2022-blake3 в ссылках Shadowsocks"
```

---

### Task 3: Обновить xray-core до 26.9.9

26.9.9 — пререлиз, тот же коммит ядра (`52a412d`), что проверен в Android на
устройстве. Нужен ради маски `udphop` (задача 4). Бинарник лежит в git.

**Files:**
- Modify: `core/bin/xray` (бинарник)
- Modify: `core/scripts/install_dev.sh:241-249`

**Step 1: Скачать и сверить контрольную сумму**

```bash
curl -L -o /tmp/xray-26.9.9.zip \
  https://github.com/XTLS/Xray-core/releases/download/v26.9.9/Xray-linux-64.zip
echo "1eb9175d0f0a8f8149c9230a7fc5ae66ce332ed20a53155ce61fe62e3f58b7df  /tmp/xray-26.9.9.zip" \
  | sha256sum -c
```

Expected: `/tmp/xray-26.9.9.zip: OK`. Сумма взята из `Xray-linux-64.zip.dgst`
того же релиза; не сошлась — остановиться, бинарник не заменять.

**Step 2: Заменить бинарник**

```bash
unzip -o -j /tmp/xray-26.9.9.zip xray -d core/bin
core/bin/xray version | head -1
```

Expected: `Xray 26.9.9 (Xray, Penetrates Everything.) 52a412d …`.

`geoip.dat` и `geosite.dat` из архива **не** брать: геобазы — этап 3.

**Step 3: Прогнать весь набор на новом ядре**

Run: `uv run pytest -q`
Expected: все passed. Упавший тест `test_fmt_xray_config_valid.py` означает, что
ядро перестало принимать конфиг, который строит приложение, — разбираться до
продолжения.

**Step 4: Закрепить версию в скрипте установки**

`/releases/latest` отдаёт последний стабильный релиз (26.3.27), а не пререлиз:
на свежей машине скрипт поставил бы ядро без `udphop`.

В начало `core/scripts/install_dev.sh`, рядом с остальными переменными, добавить:

```bash
# Версия закреплена: /releases/latest отдаёт последний стабильный релиз, а нужные
# маски finalmask есть только в пререлизах. Меняется вместе с core/bin/xray.
XRAY_VERSION="26.9.9"
```

В `download_xray()` заменить запрос к API:

```diff
-    info "Получение информации о последней версии xray-core..."
-    LATEST_VERSION=$(curl -s https://api.github.com/repos/XTLS/Xray-core/releases/latest | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/' | sed 's/^v//')
-    
-    if [ -z "$LATEST_VERSION" ]; then
-        error "Не удалось получить версию xray-core"
-        exit 1
-    fi
-    
-    info "Последняя версия: $LATEST_VERSION"
+    LATEST_VERSION="$XRAY_VERSION"
+    info "Версия xray-core: $LATEST_VERSION"
```

Run: `bash -n core/scripts/install_dev.sh`
Expected: без вывода (синтаксис в порядке).

**Step 5: Commit**

```bash
git add core/bin/xray core/scripts/install_dev.sh
git commit -m "chore(core): обновить xray-core до 26.9.9"
```

---

### Task 4: Hysteria2 — port hopping и brutal

Новые поля профиля: `hop_ports`, `hop_interval`, `up_mbps`, `down_mbps`.
Источники: мультипорт в authority (`host:443,20000-50000`), параметры `mport`,
`hop-interval` / `hopInterval`, `upmbps`, `downmbps`.

Сборка `finalmask` меняет правило «`fm` побеждает всё» на слияние:

- основа — сырой `?fm=`;
- `udphop` из `hop_ports` ставится **первым** в `udp`. Ядро требует «outermost
  level», причём ошибка возникает при dial, а не при сборке конфига —
  `xray -test` её не видит;
- `salamander` из `obfs` добавляется в конец `udp`;
- тип маски, уже присутствующий в `fm.udp`, не дублируется;
- brutal: `upmbps > 0` → `quicParams.congestion = "brutal"`, `brutalUp`,
  `brutalDown` (только при `downmbps > 0`). Ключи `quicParams` из `fm` не
  перезаписываются;
- интервал меньше 5 секунд отбрасывается при разборе: ядро отвергает его тоже
  только при dial.

Существующий тест `test_explicit_fm_wins_over_obfs` закрепляет старое поведение
и заменяется двумя: тип из `fm` не дублируется; `obfs` добавляется, если в `fm`
его нет. Старое поведение было ошибкой: `fm` в плоской форме ядро игнорирует, и
профиль оставался без обфускации.

**Files:**
- Modify: `src/fmt/protocols/hysteria2.py`
- Modify: `tests/test_fmt_hysteria2.py`
- Modify: `tests/test_fmt_xray_config_valid.py`

**Step 1: Написать падающие тесты**

`tests/test_fmt_hysteria2.py` — заменить последний тест и дописать новые:

```diff
--- a/tests/test_fmt_hysteria2.py
+++ b/tests/test_fmt_hysteria2.py
@@ -229,7 +229,162 @@
 
-def test_explicit_fm_wins_over_obfs():
-    """Явный ?fm= авторитетнее — это готовое тело finalmask от провайдера."""
+FM_UDP = '{"udp":[{"type":"salamander","settings":{"password":"from-fm"}}]}'
+
+
+def test_mask_type_from_fm_is_not_duplicated():
+    """Явный ?fm= авторитетнее: тип, который в нём уже есть, из obfs не добавляется."""
+    bean = Hysteria2Bean()
+    bean.try_parse_link(make_link(obfs="salamander", fm=quote(FM_UDP)) + "&obfs-password=obfspass")
+    stream = bean.build_outbound()["streamSettings"]
+    assert stream["finalmask"] == json.loads(FM_UDP)
+
+
+def test_obfs_is_added_when_fm_lacks_it():
+    """fm без salamander не отменяет obfs из ссылки: иначе профиль остаётся без обфускации."""
+    fm = '{"quicParams":{"congestion":"bbr"}}'
     bean = Hysteria2Bean()
-    bean.try_parse_link(make_link(obfs="salamander", fm=quote(FM)) + "&obfs-password=obfspass")
+    bean.try_parse_link(make_link(obfs="salamander", fm=quote(fm)) + "&obfs-password=obfspass")
     stream = bean.build_outbound()["streamSettings"]
-    assert stream["finalmask"] == json.loads(FM)
+    assert stream["finalmask"] == {
+        "quicParams": {"congestion": "bbr"},
+        "udp": [{"type": "salamander", "settings": {"password": "obfspass"}}],
+    }
+
+
+# --- port hopping и brutal ---
+
+
+def test_multi_port_authority_is_parsed():
+    """Официальный формат: host:443,20000-50000 — первый порт основной."""
+    bean = Hysteria2Bean()
+    assert bean.try_parse_link("hysteria2://pass123@example.com:443,20000-50000/?sni=a.com#Hop")
+
+    assert bean.server_address == "example.com"
+    assert bean.server_port == 443
+    assert bean.hop_ports == "443,20000-50000"
+    assert bean.auth == "pass123"
+    assert bean.name == "Hop"
+
+
+def test_port_range_only_authority():
+    bean = Hysteria2Bean()
+    assert bean.try_parse_link("hysteria2://pass123@example.com:20000-50000")
+    assert bean.server_port == 20000
+    assert bean.hop_ports == "20000-50000"
+
+
+def test_multi_port_authority_with_ipv6_host():
+    bean = Hysteria2Bean()
+    assert bean.try_parse_link("hysteria2://pass123@[2001:db8::1]:443,5000-6000")
+    assert bean.server_address == "2001:db8::1"
+    assert bean.server_port == 443
+    assert bean.hop_ports == "443,5000-6000"
+
+
+def test_mport_param_sets_hop_ports():
+    bean = Hysteria2Bean()
+    bean.try_parse_link(make_link(mport="20000-50000"))
+    assert bean.server_port == 8443
+    assert bean.hop_ports == "20000-50000"
+
+
+def test_invalid_port_spec_is_dropped():
+    bean = Hysteria2Bean()
+    assert bean.try_parse_link(make_link(mport="50000-20000"))
+    assert bean.hop_ports == ""
+    assert bean.try_parse_link(make_link(mport="0-70000"))
+    assert bean.hop_ports == ""
+
+
+def test_hop_interval_is_parsed_and_validated():
+    bean = Hysteria2Bean()
+    bean.try_parse_link(make_link(mport="20000-50000") + "&hop-interval=20-40")
+    assert bean.hop_interval == "20-40"
+
+    # Меньше 5 секунд ядро отвергает при dial — отбрасываем заранее.
+    bean = Hysteria2Bean()
+    bean.try_parse_link(make_link(mport="20000-50000", hopInterval="3"))
+    assert bean.hop_interval == ""
+
+
+def test_bandwidth_params_are_parsed():
+    bean = Hysteria2Bean()
+    bean.try_parse_link(make_link(upmbps="50", downmbps="100"))
+    assert (bean.up_mbps, bean.down_mbps) == (50, 100)
+
+    bean = Hysteria2Bean()
+    bean.try_parse_link(make_link(upmbps="fast", downmbps="-1"))
+    assert (bean.up_mbps, bean.down_mbps) == (0, 0)
+
+
+def test_hop_ports_become_first_udp_mask():
+    """udphop обязан быть первым в finalmask.udp, salamander — после него."""
+    bean = Hysteria2Bean()
+    bean.try_parse_link(make_link(mport="20000-50000", obfs="salamander") + "&obfs-password=p")
+    udp = bean.build_outbound()["streamSettings"]["finalmask"]["udp"]
+
+    assert udp == [
+        {
+            "type": "udphop",
+            "settings": {
+                "mode": "intervalLocal,intervalRemote",
+                "interval": "30",
+                "remotePorts": "20000-50000",
+            },
+        },
+        {"type": "salamander", "settings": {"password": "p"}},
+    ]
+
+
+def test_hop_goes_before_masks_from_fm():
+    bean = Hysteria2Bean()
+    bean.try_parse_link(make_link(mport="20000-50000", fm=quote(FM_UDP)) + "&hop-interval=10")
+    udp = bean.build_outbound()["streamSettings"]["finalmask"]["udp"]
+
+    assert [m["type"] for m in udp] == ["udphop", "salamander"]
+    assert udp[0]["settings"]["interval"] == "10"
+
+
+def test_bandwidth_becomes_brutal_quic_params():
+    bean = Hysteria2Bean()
+    bean.try_parse_link(make_link(upmbps="50", downmbps="100"))
+    mask = bean.build_outbound()["streamSettings"]["finalmask"]
+    assert mask == {
+        "quicParams": {"congestion": "brutal", "brutalUp": "50 mbps", "brutalDown": "100 mbps"}
+    }
+
+
+def test_brutal_needs_upload_rate():
+    """Без upmbps brutal не включаем: скорость отдачи ему обязательна."""
+    bean = Hysteria2Bean()
+    bean.try_parse_link(make_link(downmbps="100"))
+    assert "finalmask" not in bean.build_outbound()["streamSettings"]
+
+
+def test_quic_params_from_fm_are_not_overwritten():
+    fm = '{"quicParams":{"congestion":"bbr"}}'
+    bean = Hysteria2Bean()
+    bean.try_parse_link(make_link(upmbps="50", fm=quote(fm)))
+    quic = bean.build_outbound()["streamSettings"]["finalmask"]["quicParams"]
+    assert quic == {"congestion": "bbr", "brutalUp": "50 mbps"}
+
+
+def test_hop_and_bandwidth_survive_share_link_roundtrip():
+    bean = Hysteria2Bean()
+    bean.try_parse_link(
+        "hysteria2://pass123@example.com:443,20000-50000/?hop-interval=20-40&upmbps=50&downmbps=100#H"
+    )
+    restored = Hysteria2Bean()
+    assert restored.try_parse_link(bean.to_share_link())
+
+    assert restored.server_port == 443
+    assert restored.hop_ports == "443,20000-50000"
+    assert restored.hop_interval == "20-40"
+    assert (restored.up_mbps, restored.down_mbps) == (50, 100)
+
+
+def test_hop_fields_survive_serialization():
+    bean = Hysteria2Bean()
+    bean.try_parse_link(make_link(mport="20000-50000", upmbps="50"))
+    restored = Hysteria2Bean.from_dict(bean.to_dict())
+    assert restored.hop_ports == "20000-50000"
+    assert restored.up_mbps == 50
```

`tests/test_fmt_xray_config_valid.py`:

```diff
--- a/tests/test_fmt_xray_config_valid.py
+++ b/tests/test_fmt_xray_config_valid.py
@@ -36,4 +39,10 @@
         "hysteria2://pass123@127.0.0.1:8443?obfs=salamander&obfs-password=obfspass#H2O"
     ),
+    # udphop и brutal: нужны ядру новее 26.3.27 (там «unknown config id: udphop»).
+    "hysteria2_hop": (
+        "hysteria2://pass123@127.0.0.1:8443,20000-50000/?sni=cdn.example.com"
+        "&hop-interval=20-40&obfs=salamander&obfs-password=obfspass&upmbps=50&downmbps=100#HH"
+    ),
+    "hysteria2_mport": "hysteria2://pass123@127.0.0.1:8443?mport=20000-50000&upmbps=50#HM",
     "xhttp": (
         "vless://11111111-1111-1111-1111-111111111111@127.0.0.1:443"
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_fmt_hysteria2.py tests/test_fmt_xray_config_valid.py -q`
Expected: новые тесты failed — `AttributeError: 'Hysteria2Bean' object has no
attribute 'hop_ports'`, `ссылка не разобрана: hysteria2://…:8443,20000-50000`.

**Step 3: Реализовать**

```diff
--- a/src/fmt/protocols/hysteria2.py
+++ b/src/fmt/protocols/hysteria2.py
@@ -1,5 +1,6 @@
 from __future__ import annotations
 
+import re
 from dataclasses import dataclass, field
 from typing import Any, ClassVar
 from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse
@@ -7,6 +8,42 @@
 from src.fmt.base import ProxyBean
 from src.fmt.stream import StreamSettings, parse_json_object
 
+# Мультипорт в authority: `host:443,20000-50000` или `host:20000-50000`.
+_MULTI_PORT_AUTHORITY = re.compile(
+    r"^(.+):(\d{1,5}(?:-\d{1,5})?(?:,\d{1,5}(?:-\d{1,5})?)+|\d{1,5}-\d{1,5})$"
+)
+_PORT_SPEC = re.compile(r"^\d{1,5}(?:-\d{1,5})?(?:,\d{1,5}(?:-\d{1,5})?)*$")
+_HOP_INTERVAL = re.compile(r"^(\d{1,4})(?:-(\d{1,4}))?$")
+# Меньший интервал ядро отвергает («invalid interval»), причём только при dial.
+MIN_HOP_INTERVAL_SEC = 5
+# Значение официального клиента Hysteria.
+DEFAULT_HOP_INTERVAL_SEC = "30"
+
+
+def _is_valid_port_spec(spec: str) -> bool:
+    """Спецификация портов xray: `443,20000-50000`."""
+    if not _PORT_SPEC.match(spec):
+        return False
+    for part in spec.split(","):
+        bounds = [int(x) for x in part.split("-")]
+        if not all(1 <= b <= 65535 for b in bounds) or bounds[0] > bounds[-1]:
+            return False
+    return True
+
+
+def _is_valid_hop_interval(value: str) -> bool:
+    """Секунды: `30` или диапазон `20-40`."""
+    match = _HOP_INTERVAL.match(value)
+    if not match:
+        return False
+    low = int(match.group(1))
+    high = int(match.group(2) or match.group(1))
+    return MIN_HOP_INTERVAL_SEC <= low <= high
+
+
+def _positive_int(value: str) -> int:
+    return int(value) if value.isdigit() and int(value) > 0 else 0
+
 
 @dataclass
 class Hysteria2Bean(ProxyBean):
@@ -29,6 +66,13 @@
     # намеренно: масок у форка целое семейство (salamander, sudoku, fragment, noise,
     # mkcp), набор ключей открытый и меняется от сервера к серверу.
     final_mask: str = ""
+    # Port hopping (маска udphop). hop_ports — спецификация портов xray.
+    hop_ports: str = ""
+    # Секунды, "30" или "20-40"; пусто — DEFAULT_HOP_INTERVAL_SEC.
+    hop_interval: str = ""
+    # brutal (finalmask.quicParams), Мбит/с. 0 — не задано, решает ядро.
+    up_mbps: int = 0
+    down_mbps: int = 0
     stream: StreamSettings = field(default_factory=StreamSettings)
 
     @property
@@ -51,6 +95,20 @@
 
         try:
             url = urlparse(link)
+
+            # Официальный формат допускает мультипорт в authority. urlparse на нём
+            # бросает при чтении port, поэтому отрезаем спецификацию сами: первый
+            # порт — основной, вся спецификация — диапазон для хопа.
+            userinfo, _, hostport = url.netloc.rpartition("@")
+            multi_port = _MULTI_PORT_AUTHORITY.match(hostport)
+            hop_ports = ""
+            if multi_port:
+                spec = multi_port.group(2)
+                first_port = re.split("[,-]", spec)[0]
+                url = url._replace(netloc=f"{userinfo}@{multi_port.group(1)}:{first_port}")
+                if _is_valid_port_spec(spec):
+                    hop_ports = spec
+
             if not url.hostname:
                 return False
 
@@ -80,6 +138,15 @@
             self.obfs = query.get("obfs", [""])[0]
             self.obfs_password = query.get("obfs-password", [""])[0]
 
+            mport = query.get("mport", [""])[0]
+            if _is_valid_port_spec(mport):
+                hop_ports = mport
+            self.hop_ports = hop_ports
+            hop_interval = query.get("hop-interval", [""])[0] or query.get("hopInterval", [""])[0]
+            self.hop_interval = hop_interval if _is_valid_hop_interval(hop_interval) else ""
+            self.up_mbps = _positive_int(query.get("upmbps", [""])[0])
+            self.down_mbps = _positive_int(query.get("downmbps", [""])[0])
+
             # Битый fm отбрасываем, а не роняем всю ссылку: try_parse_link не бросает.
             fm = query.get("fm", [""])[0]
             if fm and parse_json_object(fm):
@@ -109,6 +176,16 @@
         # Без fm пересобранная ссылка теряет обфускацию и профиль перестаёт работать.
         if self.final_mask:
             query_params["fm"] = self.final_mask
+        # В authority пишем только основной порт: одиночный порт другие клиенты
+        # разбирают надёжнее, диапазон уходит в mport.
+        if self.hop_ports:
+            query_params["mport"] = self.hop_ports
+        if self.hop_interval:
+            query_params["hop-interval"] = self.hop_interval
+        if self.up_mbps > 0:
+            query_params["upmbps"] = str(self.up_mbps)
+        if self.down_mbps > 0:
+            query_params["downmbps"] = str(self.down_mbps)
 
         if query_params:
             url += "?" + urlencode(query_params)
@@ -165,30 +242,53 @@
     def _build_final_mask(self) -> dict[str, Any]:
         """Собрать тело `streamSettings.finalmask`.
 
-        Явный `?fm=` авторитетнее: это готовое тело от провайдера, кладём как
-        есть — набор масок у форка открытый и разбирать его по полям нельзя.
+        Основа — сырой `?fm=`: это готовое тело от провайдера, набор масок у
+        ядра открытый и разбирать его по полям нельзя. Поверх него достраиваем
+        маски из явных параметров ссылки; тип, который в `fm` уже есть, не
+        дублируем, а ключи `quicParams` из `fm` не перезаписываем.
 
-        Иначе разворачиваем `?obfs=` в udp-маску. Формат именно
-        `{"udp": [{"type": ..., "settings": {...}}]}` (conf.FinalMask →
+        Формат именно `{"udp": [{"type": ..., "settings": {...}}]}` (conf.FinalMask →
         `Tcp`/`Udp []Mask`, Mask = {type, settings}); плоскую форму
         `{"salamander": {...}}` ядро молча игнорирует — обфускации не будет,
         а ошибки в конфиге не увидишь.
         """
-        explicit = parse_json_object(self.final_mask)
-        if explicit:
-            return explicit
-
-        # Только salamander: остальные udp-маски форка не описываются парой
+        mask = parse_json_object(self.final_mask)
+        fm_udp = mask.get("udp")
+        if not isinstance(fm_udp, list):
+            fm_udp = []
+        fm_types = {m.get("type") for m in fm_udp if isinstance(m, dict)}
+
+        udp: list[Any] = []
+        # udphop обязан стоять первым («outermost level»): иначе ядро падает при
+        # dial, а не при сборке конфига — `xray -test` этого не увидит.
+        if self.hop_ports and "udphop" not in fm_types:
+            udp.append(
+                {
+                    "type": "udphop",
+                    "settings": {
+                        # Как у официального клиента: новый сокет и порт на каждом хопе.
+                        "mode": "intervalLocal,intervalRemote",
+                        "interval": self.hop_interval or DEFAULT_HOP_INTERVAL_SEC,
+                        "remotePorts": self.hop_ports,
+                    },
+                }
+            )
+        udp.extend(fm_udp)
+        # Только salamander: остальные udp-маски не описываются парой
         # obfs/obfs-password, а неизвестный type ядро отвергает вместе со всем
         # конфигом — молча пропускаем, как и любой неразобранный параметр.
-        if self.obfs == "salamander":
-            return {
-                "udp": [
-                    {
-                        "type": "salamander",
-                        "settings": {"password": self.obfs_password},
-                    }
-                ]
-            }
+        if self.obfs == "salamander" and "salamander" not in fm_types:
+            udp.append({"type": "salamander", "settings": {"password": self.obfs_password}})
+        if udp:
+            mask["udp"] = udp
+
+        if self.up_mbps > 0:
+            quic = mask.get("quicParams")
+            quic = dict(quic) if isinstance(quic, dict) else {}
+            quic.setdefault("congestion", "brutal")
+            quic.setdefault("brutalUp", f"{self.up_mbps} mbps")
+            if self.down_mbps > 0:
+                quic.setdefault("brutalDown", f"{self.down_mbps} mbps")
+            mask["quicParams"] = quic
 
-        return {}
+        return mask
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_fmt_hysteria2.py tests/test_fmt_xray_config_valid.py tests/test_db_profiles.py -q`
Expected: все passed.

Если `hysteria2_hop` падает с `unknown config id: udphop` — не выполнена задача 3.

**Step 5: Commit**

```bash
git add src/fmt/protocols/hysteria2.py tests/test_fmt_hysteria2.py tests/test_fmt_xray_config_valid.py
git commit -m "feat(fmt): port hopping и brutal для hysteria2"
```

---

### Task 5: Фрагментация TLS и mux

Фрагментация — tcp-маска `fragment` в `streamSettings.finalmask` самого
proxy-outbound'а. Классическая схема v2rayN (отдельный `freedom` с `fragment` и
`sockopt.dialerProxy`) не нужна: порядок outbound'ов и правила маршрутизации не
меняются.

Где ставится маска: `security` — `tls` или `reality`, транспорт не `hysteria`,
в `finalmask.tcp` профиля нет своих масок.

Mux: только `vless` и `trojan`; не `xhttp`/`splithttp` (мультиплексирует сам);
не VLESS с `flow: xtls-rprx-vision*`. На неподходящем профиле общий тумблер молча
не действует. `xudpProxyUDP443: "skip"`: по умолчанию ядро под mux отбрасывает
udp/443, и QUIC перестаёт работать.

Хранение: новое поле `DataStore.tls_fragment` (`TlsFragmentSettings`). Для mux
новых полей не заводим — в `DataStore` уже лежат неиспользуемые `mux_default_on`
и `mux_concurrency`.

Значения по умолчанию (`tlshello` / `100-200` / `10-20` мс) взяты из v2rayN и
Happ. На сети с настоящим DPI они не подбирались ни в Android, ни здесь.

**Files:**
- Modify: `src/db/config.py`
- Modify: `src/db/data_store.py`
- Create: `src/core/transport_tweaks.py`
- Modify: `src/core/config_builder.py:41-43`
- Create: `tests/test_core_transport_tweaks.py`

**Step 1: Написать падающие тесты**

Создать `tests/test_core_transport_tweaks.py`:

```python
"""Фрагментация TLS и mux поверх proxy-outbound'а."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.core.config_builder import build_latency_probe_config, build_session_config
from src.core.context import init_context
from src.core.transport_tweaks import apply_mux, apply_tls_fragment, is_mux_eligible
from src.db.config import TlsFragmentSettings
from src.db.data_store import DataStore
from src.db.profiles import ProfileEntry
from src.fmt import parse_link

XRAY = Path("core/bin/xray")
UUID = "11111111-1111-1111-1111-111111111111"
VLESS_TLS = f"vless://{UUID}@127.0.0.1:443?type=tcp&security=tls&sni=a.example.com#T"
VLESS_WS = f"vless://{UUID}@127.0.0.1:443?type=ws&path=%2Fws&security=tls&sni=a.example.com#W"
VLESS_VISION = (
    f"vless://{UUID}@127.0.0.1:443?type=tcp&security=reality&sni=a.example.com"
    "&pbk=7xhH4b_VkliBxGULljcyPOH-bYUA2dl-XAdZAsfhk04&sid=ab&flow=xtls-rprx-vision#V"
)
VLESS_XHTTP = f"vless://{UUID}@127.0.0.1:443?type=xhttp&security=tls&sni=a.example.com#X"
TROJAN = "trojan://pass123@127.0.0.1:443?type=tcp&sni=a.example.com#TR"
HYSTERIA2 = "hysteria2://pass123@127.0.0.1:8443?sni=a.example.com#H"
SHADOWSOCKS = "ss://YWVzLTI1Ni1nY206cGFzcw@127.0.0.1:8388#SS"
FRAGMENT_ON = TlsFragmentSettings(enabled=True)


def outbound_of(link: str) -> dict:
    bean = parse_link(link)
    assert bean is not None, link
    return bean.build_outbound()


# --- TlsFragmentSettings ---


def test_fragment_is_off_by_default():
    assert DataStore().tls_fragment.enabled is False


def test_fragment_settings_survive_serialization():
    store = DataStore()
    store.tls_fragment = TlsFragmentSettings(
        enabled=True, packets="1-3", length="50-100", delay="5"
    )
    restored = DataStore.from_dict(store.to_dict())
    assert restored.tls_fragment == store.tls_fragment


@pytest.mark.parametrize(
    ("field", "value", "valid"),
    [
        ("packets", "tlshello", True),
        ("packets", "TLSHello", True),
        ("packets", "1-3", True),
        ("packets", "0-3", False),
        ("packets", "hello", False),
        ("length", "100-200", True),
        ("length", "40", True),
        ("length", "0-100", False),
        ("length", "200-100", False),
        ("length", "20000", False),
        ("delay", "0", True),
        ("delay", "10-20", True),
        ("delay", "2000", False),
        ("delay", "", False),
    ],
)
def test_fragment_field_validation(field, value, valid):
    check = getattr(TlsFragmentSettings, f"is_valid_{field}")
    assert check(value) is valid


def test_sanitized_replaces_invalid_fields_with_defaults():
    dirty = TlsFragmentSettings(enabled=True, packets="oops", length=" 50-100 ", delay="-1")
    assert dirty.sanitized() == TlsFragmentSettings(
        enabled=True, packets="tlshello", length="50-100", delay="10-20"
    )


# --- apply_tls_fragment ---


@pytest.mark.parametrize("link", [VLESS_TLS, VLESS_WS, VLESS_VISION, VLESS_XHTTP, TROJAN])
def test_fragment_mask_is_added_to_tls_outbounds(link):
    outbound = outbound_of(link)
    apply_tls_fragment(outbound, FRAGMENT_ON)
    assert outbound["streamSettings"]["finalmask"] == {
        "tcp": [
            {
                "type": "fragment",
                "settings": {"packets": "tlshello", "length": "100-200", "delay": "10-20"},
            }
        ]
    }


def test_fragment_is_skipped_when_disabled():
    outbound = outbound_of(VLESS_TLS)
    apply_tls_fragment(outbound, TlsFragmentSettings(enabled=False))
    assert "finalmask" not in outbound["streamSettings"]


def test_fragment_is_skipped_for_quic():
    """hysteria2 — это QUIC: tcp-масок там нет."""
    outbound = outbound_of(HYSTERIA2)
    apply_tls_fragment(outbound, FRAGMENT_ON)
    assert "finalmask" not in outbound["streamSettings"]


def test_fragment_is_skipped_without_tls():
    outbound = outbound_of(SHADOWSOCKS)
    apply_tls_fragment(outbound, FRAGMENT_ON)
    assert "finalmask" not in outbound.get("streamSettings", {})


def test_fragment_does_not_touch_profile_tcp_masks():
    outbound = outbound_of(VLESS_TLS)
    own = {"tcp": [{"type": "sudoku", "settings": {}}], "udp": [{"type": "noise"}]}
    outbound["streamSettings"]["finalmask"] = json.loads(json.dumps(own))
    apply_tls_fragment(outbound, FRAGMENT_ON)
    assert outbound["streamSettings"]["finalmask"] == own


def test_fragment_keeps_other_finalmask_keys():
    outbound = outbound_of(VLESS_TLS)
    outbound["streamSettings"]["finalmask"] = {"udp": [{"type": "noise"}]}
    apply_tls_fragment(outbound, FRAGMENT_ON)
    mask = outbound["streamSettings"]["finalmask"]
    assert mask["udp"] == [{"type": "noise"}]
    assert mask["tcp"][0]["type"] == "fragment"


# --- mux ---


@pytest.mark.parametrize(
    ("link", "eligible"),
    [
        (VLESS_TLS, True),
        (VLESS_WS, True),
        (TROJAN, True),
        (VLESS_VISION, False),
        (VLESS_XHTTP, False),
        (HYSTERIA2, False),
        (SHADOWSOCKS, False),
    ],
    ids=["vless-tcp", "vless-ws", "trojan", "vision", "xhttp", "hysteria2", "shadowsocks"],
)
def test_mux_eligibility(link, eligible):
    assert is_mux_eligible(outbound_of(link)) is eligible


def test_mux_block_skips_udp_443():
    outbound = outbound_of(VLESS_WS)
    apply_mux(outbound, enabled=True, concurrency=8)
    assert outbound["mux"] == {
        "enabled": True,
        "concurrency": 8,
        "xudpConcurrency": 16,
        "xudpProxyUDP443": "skip",
    }


def test_mux_is_silently_skipped_on_ineligible_outbound():
    outbound = outbound_of(VLESS_VISION)
    apply_mux(outbound, enabled=True)
    assert "mux" not in outbound


def test_mux_is_skipped_when_disabled():
    outbound = outbound_of(VLESS_WS)
    apply_mux(outbound, enabled=False)
    assert "mux" not in outbound


def test_out_of_range_concurrency_falls_back_to_default():
    outbound = outbound_of(VLESS_WS)
    apply_mux(outbound, enabled=True, concurrency=0)
    assert outbound["mux"]["concurrency"] == 8


# --- через билдер конфига ---


@pytest.fixture
def context(tmp_path):
    return init_context(config_dir=tmp_path)


def entry(link: str) -> ProfileEntry:
    bean = parse_link(link)
    assert bean is not None
    return ProfileEntry(id=1, group_id=0, bean=bean)


def test_session_config_has_no_tweaks_by_default(context):
    config = build_session_config(context, entry(VLESS_WS))
    assert config is not None
    proxy = config["outbounds"][0]
    assert "mux" not in proxy
    assert "finalmask" not in proxy["streamSettings"]


def test_session_and_probe_configs_carry_the_same_tweaks(context):
    """Замер задержки обязан идти с теми же tweaks, что и рабочее подключение."""
    context.config.tls_fragment.enabled = True
    context.config.mux_default_on = True
    profile = entry(VLESS_WS)

    session = build_session_config(context, profile)
    probe = build_latency_probe_config(context, profile)

    assert session is not None and probe is not None
    for config in (session, probe[0]):
        proxy = config["outbounds"][0]
        assert proxy["mux"]["enabled"] is True
        assert proxy["streamSettings"]["finalmask"]["tcp"][0]["type"] == "fragment"


@pytest.mark.skipif(
    not XRAY.exists() or not shutil.which(str(XRAY)),
    reason="бинарник xray недоступен (core/bin/xray)",
)
@pytest.mark.parametrize(
    "link",
    [VLESS_TLS, VLESS_WS, VLESS_VISION, VLESS_XHTTP, TROJAN, HYSTERIA2, SHADOWSOCKS],
    ids=["vless-tcp", "vless-ws", "vision", "xhttp", "trojan", "hysteria2", "shadowsocks"],
)
def test_outbound_with_tweaks_is_accepted_by_xray(link, tmp_path):
    outbound = outbound_of(link)
    apply_tls_fragment(outbound, FRAGMENT_ON)
    apply_mux(outbound, enabled=True)
    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [{"port": 10800, "protocol": "socks", "settings": {}}],
        "outbounds": [outbound],
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))

    result = subprocess.run(
        [str(XRAY), "-test", "-config", str(path)], capture_output=True, text=True, timeout=60
    )
    assert "Configuration OK" in result.stdout + result.stderr
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_core_transport_tweaks.py -q`
Expected: ошибка сбора — `ModuleNotFoundError: No module named
'src.core.transport_tweaks'`.

**Step 3: Добавить модель настроек**

`src/db/config.py`:

```diff
--- a/src/db/config.py
+++ b/src/db/config.py
@@ -1,11 +1,13 @@
 from __future__ import annotations
 
 import json
+import re
 from abc import ABC
 from dataclasses import dataclass, field, fields
 from pathlib import Path
 from typing import (
     Any,
+    ClassVar,
     TypeVar,
     Union,
     get_args,
@@ -264,6 +266,66 @@
         return DnsProvider.URLS.get(self.provider, "local")
 
 
+_FRAGMENT_RANGE = re.compile(r"^(\d{1,5})(?:-(\d{1,5}))?$")
+
+
+def _is_valid_range(value: str, low: int, high: int) -> bool:
+    """Число `N` или диапазон `N-M` в пределах [low, high]."""
+    match = _FRAGMENT_RANGE.match(value)
+    if not match:
+        return False
+    start = int(match.group(1))
+    end = int(match.group(2) or match.group(1))
+    return low <= start <= end <= high
+
+
+@dataclass
+class TlsFragmentSettings(ConfigBase):
+    """Фрагментация TLS ClientHello (tcp-маска `fragment` в finalmask).
+
+    Значения — строки в формате ядра. Стартовые взяты из v2rayN/Happ и на сети
+    с DPI не подбирались: на конкретной сети могут понадобиться другие.
+    """
+
+    PACKETS_TLS_HELLO: ClassVar[str] = "tlshello"
+    DEFAULT_LENGTH: ClassVar[str] = "100-200"
+    DEFAULT_DELAY: ClassVar[str] = "10-20"
+
+    enabled: bool = False
+    # "tlshello" режет только ClientHello; иначе номера пакетов, N или N-M.
+    packets: str = PACKETS_TLS_HELLO
+    # Размер фрагмента в байтах.
+    length: str = DEFAULT_LENGTH
+    # Пауза между фрагментами, миллисекунды.
+    delay: str = DEFAULT_DELAY
+
+    @staticmethod
+    def is_valid_packets(value: str) -> bool:
+        value = value.strip()
+        return value.lower() == TlsFragmentSettings.PACKETS_TLS_HELLO or _is_valid_range(
+            value, 1, 65535
+        )
+
+    @staticmethod
+    def is_valid_length(value: str) -> bool:
+        # Нулевую длину ядро отвергает вместе со всем конфигом.
+        return _is_valid_range(value.strip(), 1, 16384)
+
+    @staticmethod
+    def is_valid_delay(value: str) -> bool:
+        return _is_valid_range(value.strip(), 0, 1000)
+
+    def sanitized(self) -> TlsFragmentSettings:
+        """Копия, где невалидное поле заменено значением по умолчанию."""
+        packets, length, delay = self.packets.strip(), self.length.strip(), self.delay.strip()
+        return TlsFragmentSettings(
+            enabled=self.enabled,
+            packets=packets.lower() if self.is_valid_packets(packets) else self.PACKETS_TLS_HELLO,
+            length=length if self.is_valid_length(length) else self.DEFAULT_LENGTH,
+            delay=delay if self.is_valid_delay(delay) else self.DEFAULT_DELAY,
+        )
+
+
 class RoutingMode:
     """Routing modes."""
 
```

`src/db/data_store.py`:

```diff
--- a/src/db/data_store.py
+++ b/src/db/data_store.py
@@ -11,6 +11,7 @@
     MonitoringSettings,
     ProxyMode,
     RoutingSettings,
+    TlsFragmentSettings,
     VpnSettings,
 )
 
@@ -95,6 +96,8 @@
     vpn: VpnSettings = field(default_factory=VpnSettings)
     # Monitoring settings
     monitoring: MonitoringSettings = field(default_factory=MonitoringSettings)
+    # Обход DPI: фрагментация TLS ClientHello. Mux — поля mux_default_on/mux_concurrency.
+    tls_fragment: TlsFragmentSettings = field(default_factory=TlsFragmentSettings)
     # Misc
     old_share_link_format: bool = True
     traffic_loop_interval: int = 1000
```

**Step 4: Добавить модуль**

Создать `src/core/transport_tweaks.py`:

```python
"""Маскировка транспорта поверх готового proxy-outbound: фрагментация TLS и mux.

Единственное место, где эти параметры навешиваются на outbound. Рабочий конфиг и
конфиг замера задержки строит одна функция (`build_session_config`), поэтому
профиль, который жив только с фрагментацией, не выглядит мёртвым при замере.
"""

from __future__ import annotations

from typing import Any

from src.db.config import TlsFragmentSettings

TLS_SECURITIES = ("tls", "reality")
# xhttp мультиплексирует сам (xmux): mux.cool поверх него ломает поток.
SELF_MULTIPLEXING_NETWORKS = ("xhttp", "splithttp")
MUX_PROTOCOLS = ("vless", "trojan")


def apply_tls_fragment(outbound: dict[str, Any], settings: TlsFragmentSettings) -> None:
    """Положить tcp-маску `fragment` в `streamSettings.finalmask` outbound'а.

    Маска оборачивает сырой TCP до TLS/REALITY во всех tcp-транспортах, поэтому
    отдельный freedom-outbound с `dialerProxy` (схема v2rayN) не нужен: порядок
    outbound'ов и правила маршрутизации не меняются.
    """
    if not settings.enabled:
        return
    stream = outbound.get("streamSettings")
    if not isinstance(stream, dict):
        return
    # QUIC: tcp-масок там нет. Без TLS резать нечего.
    if stream.get("network") == "hysteria" or stream.get("security") not in TLS_SECURITIES:
        return

    final_mask = stream.get("finalmask")
    final_mask = dict(final_mask) if isinstance(final_mask, dict) else {}
    # Чужие tcp-маски (sudoku, header/custom) меняют байты потока: фрагмент поверх
    # них не увидит ClientHello, а под ними бессмыслен. Профиль знает лучше.
    if final_mask.get("tcp"):
        return

    clean = settings.sanitized()
    final_mask["tcp"] = [
        {
            "type": "fragment",
            "settings": {"packets": clean.packets, "length": clean.length, "delay": clean.delay},
        }
    ]
    stream["finalmask"] = final_mask


def is_mux_eligible(outbound: dict[str, Any]) -> bool:
    """Где mux.cool безопасен: vless/trojan, не xhttp и не Vision."""
    if outbound.get("protocol") not in MUX_PROTOCOLS:
        return False
    stream = outbound.get("streamSettings")
    network = stream.get("network", "") if isinstance(stream, dict) else ""
    if network in SELF_MULTIPLEXING_NETWORKS:
        return False
    # Vision работает на голом TLS-потоке, mux его выключает.
    for server in (outbound.get("settings") or {}).get("vnext") or []:
        for user in server.get("users") or []:
            if str(user.get("flow", "")).startswith("xtls-rprx-vision"):
                return False
    return True


def apply_mux(outbound: dict[str, Any], enabled: bool, concurrency: int = 8) -> None:
    """Включить mux на подходящем outbound'е; на неподходящем молча ничего не делать."""
    if not enabled or not is_mux_eligible(outbound):
        return
    outbound["mux"] = {
        "enabled": True,
        "concurrency": concurrency if 1 <= concurrency <= 128 else 8,
        "xudpConcurrency": 16,
        # По умолчанию ядро под mux отбрасывает udp/443, и QUIC перестаёт работать.
        # skip пускает его обычным путём протокола, мимо mux.
        "xudpProxyUDP443": "skip",
    }


def apply_transport_tweaks(outbound: dict[str, Any], config: Any) -> None:
    """Применить настройки маскировки из DataStore к proxy-outbound'у."""
    apply_tls_fragment(outbound, config.tls_fragment)
    apply_mux(outbound, config.mux_default_on, config.mux_concurrency)
```

**Step 5: Подключить к билдеру конфига**

```diff
--- a/src/core/config_builder.py
+++ b/src/core/config_builder.py
@@ -13,6 +13,7 @@
 
 from src.core.context import AppContext
 from src.core.proxy_mode import build_inbounds_for_mode
+from src.core.transport_tweaks import apply_transport_tweaks
 from src.db.config import DEFAULT_ROUTING_ORDER, LOCAL_NETWORKS, ProxyMode, RoutingMode
 from src.db.profiles import ProfileEntry
 from src.sys.vpn import (
@@ -41,6 +42,7 @@
         outbound = result["outbound"]
         if "tag" not in outbound:
             outbound["tag"] = "proxy"
+        apply_transport_tweaks(outbound, context.config)
 
         proxy_tag = outbound["tag"]
         port = context.config.inbound_socks_port
```

**Step 6: Убедиться, что проходят**

Run: `uv run pytest tests/test_core_transport_tweaks.py tests/test_core_config_builder.py tests/test_db_data_store.py -q`
Expected: все passed.

**Step 7: Commit**

```bash
git add src/db/config.py src/db/data_store.py src/core/transport_tweaks.py \
        src/core/config_builder.py tests/test_core_transport_tweaks.py
git commit -m "feat(core): фрагментация TLS и mux поверх proxy-outbound"
```

---

### Task 6: Страница настроек «Обход блокировок»

Единственная задача, которую **не прототипировали**: GTK-тесты требуют дисплея
и изолированной шины. Код написан по образцу соседних страниц диалога.

**Files:**
- Modify: `src/ui/dialogs/settings.py`
- Modify: `tests/test_ui_dialogs_settings.py`

**Step 1: Написать падающие тесты**

Дописать в `tests/test_ui_dialogs_settings.py`:

```python
def test_the_fragment_settings_round_trip(gtk_ready):
    config = make_config()
    dialog = make_dialog(config)
    dialog.fragment_row.set_active(True)
    dialog.fragment_packets_row.set_text("1-3")
    dialog.fragment_length_row.set_text("50-100")
    dialog.fragment_delay_row.set_text("5")
    dialog.save()

    assert config.tls_fragment.enabled is True
    assert config.tls_fragment.packets == "1-3"
    assert config.tls_fragment.length == "50-100"
    assert config.tls_fragment.delay == "5"

    reopened = make_dialog(config)
    assert reopened.fragment_row.get_active()
    assert reopened.fragment_length_row.get_text() == "50-100"


def test_invalid_fragment_values_fall_back_to_defaults(gtk_ready):
    """Невалидное значение ядро отвергло бы вместе со всем конфигом."""
    config = make_config()
    dialog = make_dialog(config)
    dialog.fragment_row.set_active(True)
    dialog.fragment_length_row.set_text("0-100")
    dialog.fragment_delay_row.set_text("soon")
    dialog.save()

    assert config.tls_fragment.length == "100-200"
    assert config.tls_fragment.delay == "10-20"


def test_disabled_fragmentation_dims_its_fields(gtk_ready):
    dialog = make_dialog()
    assert not dialog.fragment_length_row.get_sensitive()
    dialog.fragment_row.set_active(True)
    assert dialog.fragment_length_row.get_sensitive()


def test_the_mux_switch_round_trips(gtk_ready):
    config = make_config()
    dialog = make_dialog(config)
    dialog.mux_row.set_active(True)
    dialog.save()
    assert config.mux_default_on is True
    assert make_dialog(config).mux_row.get_active()
```

**Step 2: Убедиться, что падают**

Run: `make test-gtk`
Expected: 4 новых теста failed — `AttributeError: 'SettingsDialog' object has no
attribute 'fragment_row'`.

**Step 3: Реализовать**

В `src/ui/dialogs/settings.py`:

Импорт:

```python
from src.db.config import DnsProvider, ProxyMode, TlsFragmentSettings
```

В `__init__`, после `self._build_dns_page()`:

```python
        self._build_bypass_page()
```

Новый метод после `_build_dns_page`:

```python
    def _build_bypass_page(self) -> None:
        page = Adw.PreferencesPage(title="Обход блокировок", icon_name="security-high-symbolic")
        self.add(page)

        fragment = Adw.PreferencesGroup(
            title="Фрагментация TLS",
            description="Делит начало TLS-соединения на части, чтобы фильтр не разобрал "
            "имя сервера. Действует на профили с TLS и Reality, со следующего подключения.",
        )
        page.add(fragment)

        self.fragment_row = Adw.SwitchRow(title="Включить фрагментацию")
        self.fragment_row.connect("notify::active", lambda *_: self._sync_fragment())
        fragment.add(self.fragment_row)

        self.fragment_packets_row = Adw.EntryRow(title="Пакеты: tlshello или номера, 1-3")
        fragment.add(self.fragment_packets_row)

        self.fragment_length_row = Adw.EntryRow(title="Размер фрагмента, байт: 100-200")
        fragment.add(self.fragment_length_row)

        self.fragment_delay_row = Adw.EntryRow(title="Пауза между фрагментами, мс: 10-20")
        fragment.add(self.fragment_delay_row)

        mux = Adw.PreferencesGroup(title="Мультиплексирование")
        page.add(mux)

        self.mux_row = Adw.SwitchRow(
            title="Включить mux",
            subtitle="Несколько потоков в одном соединении. Только VLESS и Trojan, "
            "кроме XHTTP и Vision",
        )
        mux.add(self.mux_row)
```

Рядом с `_sync_monitoring`:

```python
    def _sync_fragment(self) -> None:
        active = self.fragment_row.get_active()
        self.fragment_packets_row.set_sensitive(active)
        self.fragment_length_row.set_sensitive(active)
        self.fragment_delay_row.set_sensitive(active)
```

В конец `_load`:

```python
        fragment = config.tls_fragment
        self.fragment_row.set_active(fragment.enabled)
        self.fragment_packets_row.set_text(fragment.packets)
        self.fragment_length_row.set_text(fragment.length)
        self.fragment_delay_row.set_text(fragment.delay)
        self._sync_fragment()
        self.mux_row.set_active(config.mux_default_on)
```

В `save`, перед `self.emit("settings-saved")`:

```python
        # sanitized(): невалидное поле ядро отвергло бы вместе со всем конфигом.
        config.tls_fragment = TlsFragmentSettings(
            enabled=self.fragment_row.get_active(),
            packets=self.fragment_packets_row.get_text(),
            length=self.fragment_length_row.get_text(),
            delay=self.fragment_delay_row.get_text(),
        ).sanitized()
        config.mux_default_on = self.mux_row.get_active()
```

**Step 4: Убедиться, что проходят**

Run: `make test-gtk`
Expected: все passed. Если тесты окна пропущены с объяснением про шину сессии —
это штатно (см. `CLAUDE.md`), тесты диалога к ним не относятся.

**Step 5: Проверить глазами**

Run: `python gui.py`
Открыть «Настройки» → «Обход блокировок»: выключенный тумблер гасит три поля,
значения переживают закрытие и повторное открытие диалога.

Проверять на машине, где установленный Tenga остановлен: второй экземпляр
активирует окно первого.

**Step 6: Commit**

```bash
git add src/ui/dialogs/settings.py tests/test_ui_dialogs_settings.py
git commit -m "feat(ui): настройки фрагментации TLS и mux"
```

---

### Task 7: Документация и итоговая проверка

**Files:**
- Modify: `docs/ru/protocols.md`, `docs/en/protocols.md`
- Modify: `docs/plans/2026-10-03-network-parity-roadmap.md`

**Step 1: Обновить описание протоколов**

В обоих файлах:

- Shadowsocks: поддерживаются AEAD (`aes-128-gcm`, `aes-256-gcm`,
  `chacha20-poly1305`, `xchacha20-poly1305` и их `-ietf`-варианты) и
  `2022-blake3-*`; потоковые шифры, `none` и SIP003-плагины — нет.
- Hysteria2: мультипорт в адресе, `mport`, `hop-interval`, `upmbps`, `downmbps`.
- Транспорт h2 не поддерживается (удалён из ядра); `allowInsecure` не действует.
- Новый раздел про фрагментацию TLS и mux: где включается и на какие профили
  действует.

**Step 2: Полная проверка**

```bash
uv run pytest -q
make test-gtk
python cli.py lint-all
```

Expected: всё зелёное, линтер без замечаний.

**Step 3: Проверка на живых серверах**

Юнит-тесты и `xray -test` подтверждают только то, что ядро принимает конфиг.
Проверить подключением, если есть такие профили:

- Shadowsocks по SIP002-ссылке из подписки;
- hysteria2 с диапазоном портов: соединение не рвётся дольше одного интервала
  хопа (30 с). Ошибки `udphop` видны только здесь;
- профиль VLESS+ws с включённым mux: сайт по HTTP/3 открывается в браузере
  (`curl` разницы не покажет);
- фрагментация: профиль с TLS подключается и замер задержки не хуже, чем без неё.

Что проверить не удалось — записать в дорожную карту, в статус этапа 1.

**Step 4: Записать статус в дорожную карту и закоммитить**

```bash
git add docs/
git commit -m "docs: описать протоколы и записать результаты этапа 1"
```

Версию приложения поднимает владелец проекта: `python cli.py bump-version <версия>`.
