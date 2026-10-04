"""Пакетный замер задержки: один процесс ядра на весь набор профилей.

У каждого профиля свой HTTP-inbound `probe-in-N` на 127.0.0.1 и свой outbound
`proxy-N`; правило по `inboundTag` связывает пару. Рабочий билдер конфигурации
здесь не участвует: замеру не нужны ни пользовательские правила, ни DNS, ни TUN.
"""

from __future__ import annotations

import copy
import json
import logging
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.core.http_probe import ProbeCredentials, ProbeEndpoint, build_probe_inbound
from src.core.transport_tweaks import apply_transport_tweaks

if TYPE_CHECKING:
    from src.db.data_store import DataStore
    from src.db.profiles import ProfileEntry

logger = logging.getLogger("tenga.core.batch_probe")

PROBE_INBOUND_PREFIX = "probe-in-"
PROBE_OUTBOUND_PREFIX = "proxy-"
CORE_TEST_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class ProbeTarget:
    """Профиль, готовый к замеру: его id и собранный outbound."""

    profile_id: int
    outbound: dict[str, Any]


def build_probe_outbound(profile: ProfileEntry, settings: DataStore) -> dict[str, Any] | None:
    """Outbound профиля с теми же надстройками транспорта, что и в рабочей сессии.

    None — профиль собрать нельзя: в пакет он не попадает и сразу получает -1.
    """
    try:
        result = profile.bean.build_core_obj_xray()
    except Exception as e:
        logger.warning("Profile %s cannot be built for probing: %s", profile.id, e)
        return None

    if result.get("error") or not result.get("outbound"):
        logger.info("Profile %s skipped by probe: %s", profile.id, result.get("error"))
        return None

    outbound = result["outbound"]
    apply_transport_tweaks(outbound, settings)
    return outbound


def build_batch_probe_config(
    targets: Sequence[ProbeTarget],
    ports: Sequence[int],
    credentials: ProbeCredentials,
    *,
    log_level: str = "warning",
) -> dict[str, Any]:
    """Конфиг ядра для замера: N inbound'ов, N outbound'ов, N правил."""
    if len(ports) != len(targets):
        raise ValueError(f"портов {len(ports)}, а профилей {len(targets)}")

    inbounds: list[dict[str, Any]] = []
    outbounds: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []

    for index, (target, port) in enumerate(zip(targets, ports, strict=True), start=1):
        inbound_tag = f"{PROBE_INBOUND_PREFIX}{index}"
        outbound_tag = f"{PROBE_OUTBOUND_PREFIX}{index}"

        inbounds.append(build_probe_inbound(inbound_tag, ProbeEndpoint(port, credentials)))

        outbound = copy.deepcopy(target.outbound)
        outbound["tag"] = outbound_tag
        outbounds.append(outbound)

        rules.append({"type": "field", "inboundTag": [inbound_tag], "outboundTag": outbound_tag})

    return {
        "log": {"loglevel": log_level},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": {"rules": rules},
    }


def _write_config(config: dict[str, Any]) -> Path:
    # NamedTemporaryFile создаёт файл с правами 0600: в конфиге лежат ключи
    # профилей и учётные данные inbound'ов.
    with tempfile.NamedTemporaryFile(
        mode="w", prefix="tenga-probe-", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(config, f, ensure_ascii=False)
        return Path(f.name)


def core_accepts(binary_path: str, config: dict[str, Any]) -> bool:
    """Спросить у ядра, примет ли оно конфиг (`xray -test`). Портов не занимает."""
    path = _write_config(config)
    try:
        result = subprocess.run(
            [binary_path, "-test", "-config", str(path)],
            capture_output=True,
            timeout=CORE_TEST_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("Core could not check the probe config: %s", e)
        return False
    finally:
        path.unlink(missing_ok=True)

    return result.returncode == 0


def split_accepted(
    targets: Sequence[ProbeTarget],
    accepts: Callable[[Sequence[ProbeTarget]], bool],
) -> tuple[list[ProbeTarget], list[ProbeTarget]]:
    """Разделить профили на принятые ядром и отвергнутые, сохраняя порядок.

    Ядро отвергает конфиг целиком из-за одного outbound'а, а сборка такие
    профили пропускает: ключ REALITY не той длины, неизвестный fingerprint,
    неверный UUID. Пакет делится пополам, пока виновные не останутся по одному:
    на один плохой профиль уходит около 2·log2(N) проверок вместо N.
    """
    batch = list(targets)
    if not batch:
        return [], []
    if accepts(batch):
        return batch, []
    if len(batch) == 1:
        return [], batch

    middle = len(batch) // 2
    left_accepted, left_rejected = split_accepted(batch[:middle], accepts)
    right_accepted, right_rejected = split_accepted(batch[middle:], accepts)
    return left_accepted + right_accepted, left_rejected + right_rejected
