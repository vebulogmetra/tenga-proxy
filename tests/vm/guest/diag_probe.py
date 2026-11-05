"""Полная проверка сети из установленного пакета; отчёт — JSON в stdout. Запускает `checks.py`.

Источники те же, что у GUI (`context_sources`), кроме сеанса: туннель виден по маршруту, а
блокировка передаётся аргументом, потому что отдельный процесс настроек сеанса не знает.
"""

from __future__ import annotations

import errno
import json
import socket
import sys

sys.path.insert(0, "/usr/lib/tenga-proxy")

from src.diag.models import DiagnosticRequest
from src.diag.network import DirectPolicy
from src.diag.runner import DiagnosticSources, Finished, desktop_runner
from src.sys import netbind

SITE = "203.0.113.80"


def bound_get(address: str, interface: str | None) -> str:
    """Обращение мимо диагностики. Эхо-сервер отвечает адресом клиента, ошибка — кодом errno."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(3)
            netbind.socket_binder(interface or "")(sock)
            sock.connect((address, 80))
            sock.sendall(b"GET / HTTP/1.0\r\nHost: lab\r\n\r\n")
            answer = b""
            while chunk := sock.recv(4096):
                answer += chunk
    except OSError as error:
        return errno.errorcode.get(error.errno or 0, type(error).__name__)
    return answer.decode(errors="replace").split("\r\n\r\n", 1)[-1].strip()


def main() -> None:
    kill_switch = "--kill-switch" in sys.argv
    policy = DirectPolicy(netbind.active_tunnel_interface(), kill_switch)
    runner = desktop_runner(DiagnosticSources(lambda: policy, lambda: None), "0.0.0")
    result: dict = {}

    def on_event(event) -> None:
        if isinstance(event, Finished):
            result["report"] = event.report

    runner.run(DiagnosticRequest(compare_active_tunnel=False), on_event)
    report = result["report"]
    bound = {}
    if "--bound" in sys.argv:
        interface = netbind.physical_interface([policy.tun_interface or ""])
        bound = {"site": bound_get(SITE, interface)}
    print(
        json.dumps(
            {
                "tunnel": policy.tun_interface,
                "termination": report.termination.name,
                "bound": bound,
                "observations": [
                    {
                        "id": item.id,
                        "target": item.target_id,
                        "route": item.route.name,
                        "stage": item.stage.name,
                        "status": item.status.name,
                        "failure": item.failure_code.name if item.failure_code else None,
                        "family": item.address_family.name if item.address_family else None,
                    }
                    for item in report.observations
                ],
            }
        )
    )


if __name__ == "__main__":
    main()
