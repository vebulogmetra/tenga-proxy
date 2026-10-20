"""Validate settings before committing a form, independently of GTK."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

from src.db.config import TlsFragmentSettings
from src.sub.url_policy import SubscriptionPolicyError, validate_url


def valid_dns_address(value: str) -> bool:
    if not value or value == "local":
        return True
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        pass
    try:
        parts = urlsplit(value)
        port = parts.port
        return (
            parts.scheme in ("https", "https+local", "tcp", "tcp+local", "udp")
            and bool(parts.hostname)
            and parts.username is None
            and parts.password is None
            and not parts.fragment
            and port != 0
            and not any(c.isspace() for c in value)
        )
    except ValueError:
        return False


def validate_settings(config) -> dict[str, str]:
    errors = {}
    try:
        ipaddress.ip_address(config.inbound_address)
    except ValueError:
        if config.inbound_address != "localhost":
            errors["address"] = "Введите IP-адрес или localhost"
    for name, value, low, high in (
        ("port", config.inbound_socks_port, 1, 65534),
        ("tun_mtu", config.tun_mtu, 576, 9000),
        ("interval", config.monitoring.check_interval_seconds, 1, 3600),
        ("failover_threshold", config.monitoring.failover_threshold, 1, 100),
    ):
        if type(value) is not int or not low <= value <= high:
            errors[name] = f"Введите число от {low} до {high}"
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,15}", config.tun_name):
        errors["tun_name"] = "Имя интерфейса: 1–15 букв, цифр, _, . или -"
    if not valid_dns_address(config.dns.custom_url):
        errors["dns_url"] = "Введите IP или адрес DNS с поддерживаемой схемой"
    if config.dns.additional_url == "local" or not valid_dns_address(config.dns.additional_url):
        errors["dns_additional"] = "Дополнительный DNS должен быть явным адресом сервера"
    if config.dns.additional_url and config.dns.get_dns_url() == "local":
        errors["dns_additional"] = "Для дополнительного DNS выберите удалённый основной сервер"
    for field in ("packets", "length", "delay"):
        if not getattr(TlsFragmentSettings, f"is_valid_{field}")(
            getattr(config.tls_fragment, field)
        ):
            errors[f"fragment_{field}"] = "Некорректный диапазон фрагментации"
    for url in config.sub_source_exceptions:
        try:
            validate_url(url, exceptions=[url])
        except SubscriptionPolicyError:
            errors["sub_exceptions"] = "Исключение должно содержать полный URL без логина и пароля"
    return errors
