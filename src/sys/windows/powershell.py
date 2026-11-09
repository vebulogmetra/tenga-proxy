"""Запуск PowerShell-скрипта с выводом JSON.

Вывод `netsh` и `route print` переведён на язык системы, а объекты PowerShell
сериализуются одинаково на любой локали.
"""

from __future__ import annotations

import json
import logging
import queue
import subprocess
import threading

from src.core.platform_info import no_window

logger = logging.getLogger("tenga.sys.powershell")


def run_json(script: str, timeout: int = 15) -> str:
    """Stdout скрипта; пустая строка при любой ошибке."""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
            **no_window(),
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("PowerShell failed: %s", e)
        return ""
    if result.returncode != 0:
        logger.warning("PowerShell returned %s: %s", result.returncode, result.stderr.strip())
        return ""
    return result.stdout


_NRPT_WORKER = r"""
[Console]::InputEncoding = [Text.Encoding]::UTF8
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
Import-Module DnsClient
while ($null -ne ($line = [Console]::ReadLine())) {
    try {
        $request = $line | ConvertFrom-Json
        $output = & ([ScriptBlock]::Create($request.script)) | Out-String
        $response = @{ok = $true; output = [string]$output}
    } catch {
        $response = @{ok = $false; output = ''}
    }
    [Console]::WriteLine(($response | ConvertTo-Json -Compress))
}
"""


class NrptSession:
    """Один DnsClient runspace на службу; скрипты задаёт только winsvc.netops.

    Не повторяет мутации при таймауте: команда могла успеть выполниться.
    Завершение службы закрывает stdin и освобождает процесс.
    """

    def __init__(self, timeout: float = 15) -> None:
        self._timeout = timeout
        self._lock = threading.Lock()
        self._process = None
        self._responses = None

    def _start(self) -> None:
        responses = queue.Queue()
        process = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _NRPT_WORKER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            **no_window(),
        )
        self._process, self._responses = process, responses

        def read() -> None:
            try:
                for line in process.stdout:
                    responses.put(line)
            except (OSError, ValueError):
                pass
            finally:
                responses.put(None)

        threading.Thread(target=read, name="nrpt-worker", daemon=True).start()

    def run(self, script: str) -> str:
        with self._lock:
            try:
                if self._process is None or self._process.poll() is not None:
                    self._close()
                    self._start()
                self._process.stdin.write(json.dumps({"script": script}) + "\n")
                self._process.stdin.flush()
                line = self._responses.get(timeout=self._timeout)
                if line is None:
                    raise OSError("NRPT worker exited")
                response = json.loads(line)
                if not isinstance(response, dict) or not response.get("ok"):
                    raise OSError("NRPT provider rejected operation")
                output = response.get("output")
                if not isinstance(output, str):
                    raise ValueError("Invalid NRPT worker output")
                return output
            except (OSError, ValueError, queue.Empty, subprocess.SubprocessError) as e:
                self._close()
                raise OSError("NRPT operation failed or timed out") from e

    def _close(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            try:
                process.kill()
                process.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                logger.warning("Could not reap NRPT worker")
            finally:
                for stream in (process.stdin, process.stdout):
                    if stream is not None:
                        try:
                            stream.close()
                        except OSError:
                            pass

    def close(self) -> None:
        with self._lock:
            self._close()
