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
