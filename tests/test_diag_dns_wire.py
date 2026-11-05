import socket

import pytest

from src.diag.models import AddressFamily
from src.diag.probes import dns_wire
from tests.support.diag import build_response, encode_name, parse_query

V4 = AddressFamily.IPV4
V6 = AddressFamily.IPV6
HOST = "www.example.com"


def test_query_has_zero_id_and_is_lowercased():
    data = dns_wire.query("WWW.Example.COM", V4)
    assert parse_query(data) == (0, HOST, 1, 1)
    assert parse_query(dns_wire.query(HOST, V6))[2] == 28


@pytest.mark.parametrize("name", ["x", "nodot", "-bad.example", "a..b", "кириллица.рф", "a" * 300])
def test_query_rejects_bad_hostnames(name):
    with pytest.raises(ValueError, match="hostname"):
        dns_wire.query(name, V4)


def test_parse_returns_answer_addresses():
    message = build_response(0, HOST, 1, answers=[socket.inet_aton("8.8.8.8")])
    answer = dns_wire.parse(message, HOST, V4)
    assert answer.addresses == ("8.8.8.8",)
    assert answer.rcode == 0


def test_answers_of_a_foreign_owner_are_ignored():
    # Запись отвечает на другой вопрос: подсунуть адрес без CNAME нельзя.
    raw = _message(HOST, [("evil.example", 1, socket.inet_aton("8.8.8.8"))])
    assert dns_wire.parse(raw, HOST, V4).addresses == ()


def test_cname_makes_alias_reachable():
    raw = _message(
        HOST,
        [
            (HOST, 5, encode_name("edge.example.net")),
            ("edge.example.net", 1, socket.inet_aton("8.8.8.8")),
        ],
    )
    assert dns_wire.parse(raw, HOST, V4).addresses == ("8.8.8.8",)


def test_cname_loop_is_rejected():
    raw = _message(HOST, [(HOST, 5, encode_name("a.example")), ("a.example", 5, encode_name(HOST))])
    with pytest.raises(ValueError, match="alias"):
        dns_wire.parse(raw, HOST, V4)


def test_bad_address_length_is_rejected():
    raw = _message(HOST, [(HOST, 1, b"\1\2\3")])
    with pytest.raises(ValueError, match="length"):
        dns_wire.parse(raw, HOST, V4)


def test_rcode_hides_addresses():
    raw = _message(HOST, [(HOST, 1, socket.inet_aton("8.8.8.8"))], rcode=2)
    answer = dns_wire.parse(raw, HOST, V4)
    assert (answer.addresses, answer.rcode) == ((), 2)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m[:5],
        lambda m: b"\x12\x34" + m[2:],  # чужой ID
        lambda m: m[:2] + bytes([m[2] & 0x7F]) + m[3:],  # не ответ
        lambda m: m + b"x",  # лишние байты
        lambda m: m[:2] + bytes([m[2] | 2]) + m[3:],  # усечён
    ],
)
def test_malformed_messages_are_rejected(mutate):
    raw = _message(HOST, [(HOST, 1, socket.inet_aton("8.8.8.8"))])
    with pytest.raises(ValueError, match=r".+"):
        dns_wire.parse(mutate(raw), HOST, V4)


def test_foreign_question_is_rejected():
    raw = _message("other.example", [])
    with pytest.raises(ValueError, match="foreign"):
        dns_wire.parse(raw, HOST, V4)


def test_compression_pointer_must_go_backwards():
    head = _message(HOST, [])
    forward = head[:6] + b"\0\1" + head[8:] + b"\xc0\xff" + b"\0\1\0\1\0\0\0\0\0\4\1\2\3\4"
    with pytest.raises(ValueError, match="pointer"):
        dns_wire.parse(forward, HOST, V4)


def test_parse_txt_reads_strings():
    raw = _message("id.server", [("id.server", 16, b"\5dme01")], qtype=16, qclass=3, rclass=3)
    assert dns_wire.parse_txt(raw, "id.server", 3) == (0, ["dme01"])
    long = _message(
        "id.server", [("id.server", 16, b"\x7f" + b"x" * 127)], qtype=16, qclass=3, rclass=3
    )
    with pytest.raises(ValueError, match="txt"):
        dns_wire.parse_txt(long, "id.server", 3)


def _message(name, records, *, rcode=0, qtype=1, qclass=1, rclass=1):
    data = bytearray(b"\0\0\x81")
    data.append(0x80 | rcode)
    data += b"\0\1" + len(records).to_bytes(2, "big") + b"\0\0\0\0"
    data += encode_name(name) + qtype.to_bytes(2, "big") + qclass.to_bytes(2, "big")
    for owner, rtype, rdata in records:
        data += encode_name(owner) + rtype.to_bytes(2, "big") + rclass.to_bytes(2, "big")
        data += b"\0\0\0\x3c" + len(rdata).to_bytes(2, "big") + rdata
    return bytes(data)
