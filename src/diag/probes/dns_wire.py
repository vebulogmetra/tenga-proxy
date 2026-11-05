"""Узкое подмножество RFC 1035: A/AAAA, CNAME и TXT; порт DnsWire.kt.

Разбор строгий: чужой или испорченный ответ даёт ValueError, а не догадку об адресе.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

from src.diag.models import AddressFamily

TYPE_A = 1
TYPE_CNAME = 5
TYPE_TXT = 16
TYPE_AAAA = 28
CLASS_IN = 1
CLASS_CHAOS = 3
MAX_MESSAGE_BYTES = 16_384
_MAX_TXT_BYTES = 64
_HOST_LABEL = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?")
_WIRE_LABEL = re.compile(rb"[A-Za-z0-9_-]+")


@dataclass(frozen=True)
class DnsAnswer:
    """Адреса — только вход для соединения: в отчёт они не попадают."""

    addresses: tuple[str, ...]
    rcode: int | None
    coverage: str = "family-query"


@dataclass(frozen=True)
class _Record:
    owner: str
    type: int
    record_class: int
    data: bytes
    alias: str | None


def _type_of(family: AddressFamily) -> int:
    return TYPE_A if family is AddressFamily.IPV4 else TYPE_AAAA


def checked_hostname(hostname: str) -> str:
    if not 3 <= len(hostname) <= 253 or "." not in hostname:
        raise ValueError("bad hostname")
    name = hostname.lower()
    if not all(len(part) <= 63 and _HOST_LABEL.fullmatch(part) for part in name.split(".")):
        raise ValueError("bad hostname")
    return name


def query_raw(hostname: str, record_type: int, record_class: int) -> bytes:
    """ID нулевой, как требует DoH; UDP и TCP подставляют свой случайный (with_transaction)."""
    output = bytearray(b"\x00\x00\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00")
    for label in checked_hostname(hostname).split("."):
        output.append(len(label))
        output += label.encode("ascii")
    output += b"\x00" + record_type.to_bytes(2, "big") + record_class.to_bytes(2, "big")
    return bytes(output)


def query(hostname: str, family: AddressFamily) -> bytes:
    return query_raw(hostname, _type_of(family), CLASS_IN)


def with_transaction(message: bytes, transaction: int) -> bytes:
    return transaction.to_bytes(2, "big") + message[2:]


def parse(data: bytes, hostname: str, family: AddressFamily) -> DnsAnswer:
    expected = checked_hostname(hostname)
    wanted = _type_of(family)
    rcode, records = _message(data, expected, wanted, CLASS_IN)
    aliases: dict[str, str] = {}
    found: list[tuple[str, str]] = []
    size = 4 if family is AddressFamily.IPV4 else 16
    for record in records:
        if record.record_class != CLASS_IN:
            continue
        if record.type == TYPE_CNAME:
            if aliases.setdefault(record.owner, record.alias or "") != record.alias:
                raise ValueError("conflicting aliases")
        elif record.type == wanted:
            if len(record.data) != size:
                raise ValueError("bad address length")
            found.append((record.owner, str(ipaddress.ip_address(record.data))))
    reachable: set[str] = set()
    owner: str | None = expected
    while owner is not None:
        if owner in reachable or len(reachable) >= 16:
            raise ValueError("alias chain")
        reachable.add(owner)
        owner = aliases.get(owner)
    if rcode != 0:
        return DnsAnswer((), rcode)
    return DnsAnswer(tuple(dict.fromkeys(ip for name, ip in found if name in reachable)), rcode)


def parse_txt(data: bytes, hostname: str, record_class: int) -> tuple[int, list[str]]:
    expected = checked_hostname(hostname)
    rcode, records = _message(data, expected, TYPE_TXT, record_class)
    texts: list[str] = []
    for record in records:
        if (record.owner, record.type, record.record_class) != (
            expected,
            TYPE_TXT,
            record_class,
        ):
            continue
        at = 0
        while at < len(record.data):
            size = record.data[at]
            if size > _MAX_TXT_BYTES or at + 1 + size > len(record.data):
                raise ValueError("bad txt")
            texts.append(record.data[at + 1 : at + 1 + size].decode("ascii"))
            at += 1 + size
    return rcode, texts


def _u16(data: bytes, at: int) -> int:
    if at < 0 or at + 1 >= len(data):
        raise ValueError("short message")
    return (data[at] << 8) | data[at + 1]


def _name(data: bytes, at: int) -> tuple[str, int]:
    position = at
    end = -1
    visited: set[int] = set()
    labels: list[str] = []
    length = 0
    while True:
        if not 0 <= position < len(data) or position in visited or len(visited) >= 128:
            raise ValueError("bad name")
        visited.add(position)
        size = data[position]
        if size == 0:
            return ".".join(labels), position + 1 if end == -1 else end
        if size & 0xC0 == 0xC0:
            pointer = _u16(data, position) & 0x3FFF
            if pointer >= position:
                raise ValueError("forward pointer")
            if end == -1:
                end = position + 2
            position = pointer
            continue
        label = data[position + 1 : position + 1 + size]
        if size > 63 or len(label) != size or not _WIRE_LABEL.fullmatch(label):
            raise ValueError("bad label")
        labels.append(label.decode("ascii").lower())
        length += size + 1
        if length > 254:
            raise ValueError("long name")
        position += 1 + size


def _message(
    data: bytes, expected: str, question_type: int, question_class: int
) -> tuple[int, list[_Record]]:
    if not 12 <= len(data) <= MAX_MESSAGE_BYTES or _u16(data, 0) != 0:
        raise ValueError("bad message")
    flags = _u16(data, 2)
    if not flags & 0x8000 or flags & 0x7800 or flags & 0x0200 or _u16(data, 4) != 1:
        raise ValueError("bad flags")
    name, position = _name(data, 12)
    if (
        name != expected
        or _u16(data, position) != question_type
        or _u16(data, position + 2) != question_class
    ):
        raise ValueError("foreign question")
    position += 4
    answer_count = _u16(data, 6)
    count = answer_count + _u16(data, 8) + _u16(data, 10)
    if count > 256:
        raise ValueError("too many records")
    records: list[_Record] = []
    for index in range(count):
        owner, position = _name(data, position)
        record_type = _u16(data, position)
        record_class = _u16(data, position + 2)
        size = _u16(data, position + 8)
        position += 10
        if position + size > len(data):
            raise ValueError("short record")
        if index < answer_count:
            alias = None
            if record_type == TYPE_CNAME and record_class == question_class:
                alias, alias_end = _name(data, position)
                if alias_end != position + size:
                    raise ValueError("bad alias")
            records.append(
                _Record(owner, record_type, record_class, data[position : position + size], alias)
            )
        position += size
    if position != len(data):
        raise ValueError("trailing bytes")
    return flags & 15, records
