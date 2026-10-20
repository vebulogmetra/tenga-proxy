"""Fingerprint names supported by xray 26.9.9 transport/internet/tls/tls.go."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

FINGERPRINTS = frozenset(
    [
        "chrome",
        "firefox",
        "safari",
        "ios",
        "android",
        "edge",
        "360",
        "qq",
        "random",
        "randomized",
        "randomizednoalpn",
        "hellofirefox_120",
        "hellofirefox_148",
        "hellochrome_120",
        "hellochrome_131",
        "hellochrome_133",
        "helloios_13",
        "helloios_14",
        "helloedge_106",
        "hellosafari_26_3",
        "hello360_11_0",
        "helloqq_11_1",
        "hellogolang",
        "hellorandomized",
        "hellorandomizedalpn",
        "hellorandomizednoalpn",
        "hellofirefox_auto",
        "hellofirefox_55",
        "hellofirefox_56",
        "hellofirefox_63",
        "hellofirefox_65",
        "hellofirefox_99",
        "hellofirefox_102",
        "hellofirefox_105",
        "hellochrome_auto",
        "hellochrome_58",
        "hellochrome_62",
        "hellochrome_70",
        "hellochrome_72",
        "hellochrome_83",
        "hellochrome_87",
        "hellochrome_96",
        "hellochrome_100",
        "hellochrome_102",
        "hellochrome_106_shuffle",
        "helloios_auto",
        "helloios_11_1",
        "helloios_12_1",
        "helloandroid_11_okhttp",
        "helloedge_85",
        "helloedge_auto",
        "hellosafari_16_0",
        "hellosafari_auto",
        "hello360_auto",
        "hello360_7_5",
        "helloqq_auto",
        "hellochrome_100_psk",
        "hellochrome_112_psk_shuf",
        "hellochrome_114_padding_psk_shuf",
        "hellochrome_115_pq",
        "hellochrome_115_pq_psk",
        "hellochrome_120_pq",
    ]
)
UNKNOWN_FINGERPRINT = "Неизвестный TLS fingerprint: будет использован Chrome"
IGNORED_INSECURE = "Отключение проверки сертификата из ссылки не применяется"


def normalize_fingerprint(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized or normalized in FINGERPRINTS:
        return normalized
    logger.warning(UNKNOWN_FINGERPRINT)
    return "chrome"


def tls_warnings(stream) -> tuple[str, ...]:
    warnings = []
    if stream.utls_fingerprint.strip().lower() not in FINGERPRINTS | {""}:
        warnings.append(UNKNOWN_FINGERPRINT)
    if stream.allow_insecure:
        warnings.append(IGNORED_INSECURE)
    return tuple(warnings)
