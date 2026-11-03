#!/usr/bin/env python3
"""Блокировка трафика на установленном deb в настоящей виртуалке, от начала до конца.

Ставит QEMU, если его нет, собирает пакет, поднимает Ubuntu 24.04, ставит в неё пакет,
гоняет проверки из `guest/checks.py`, выключает виртуалку и удаляет её.

Сеть виртуалки — пользовательский режим QEMU: на хосте не появляется ни мостов, ни
маршрутов, ни правил файрвола, поэтому запускать можно и рядом с живым сеансом TUN.
TUN, nftables и маршруты живут в ядре виртуалки.

Запуск: `make test-vm`. Код возврата — как у pytest внутри виртуалки.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUEST_DIR = Path(__file__).resolve().parent / "guest"

IMAGE_URL = "https://cloud-images.ubuntu.com/noble/current/"
IMAGE_NAME = "noble-server-cloudimg-amd64.img"
# В /var/tmp, а не в домашнем каталоге: на машинах разработчиков /home часто забит.
DEFAULT_WORKDIR = Path("/var/tmp/veblock-vm")
MIN_FREE_BYTES = 12 * 1024**3

HOST_TOOLS = {
    "qemu-system-x86_64": "qemu-system-x86",
    "qemu-img": "qemu-utils",
    "cloud-localds": "cloud-image-utils",
}
GUEST_PACKAGES = (
    "busybox-static",
    "curl",
    "dbus",
    "docker.io",
    "network-manager",
    "network-manager-openvpn",
    "nftables",
    "openvpn",
    "polkitd",
    "python3-pytest",
    "systemd-resolved",
    "xvfb",
)
USER_DATA = """\
#cloud-config
hostname: veblock-vm
users:
  # Проверки и установка пакета. У tester, от которого идёт приложение, общего
  # NOPASSWD нет: иначе не будет видно, работает ли правило sudoers из пакета.
  - name: harness
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys: ["{public_key}"]
  - name: tester
    shell: /bin/bash
    groups: [sudo]
package_update: true
packages: [{packages}]
write_files:
  - path: /etc/veblock-vm-guest
    content: "Проверки guest/checks.py разрешены только здесь\\n"
  # Без NetworkManager приложение не смогло бы поднять VPN через nmcli.
  - path: /etc/netplan/99-veblock-nm.yaml
    permissions: "0600"
    content: |
      network: {{version: 2, renderer: NetworkManager}}
  # В настольном сеансе это право даёт активная сессия; здесь её нет.
  - path: /etc/polkit-1/rules.d/50-veblock-lab.rules
    content: |
      polkit.addRule(function(action, subject) {{
        if (subject.user == "tester" &&
            action.id.indexOf("org.freedesktop.NetworkManager.") == 0) {{
          return polkit.Result.YES;
        }}
      }});
runcmd:
  - [netplan, apply]
"""


def log(message: str) -> None:
    print(f"\n=== {message}", flush=True)


def run(*command, **kwargs) -> subprocess.CompletedProcess:
    kwargs.setdefault("check", True)
    return subprocess.run([str(part) for part in command], **kwargs)


def ensure_host_tools() -> None:
    missing = sorted({pkg for tool, pkg in HOST_TOOLS.items() if not shutil.which(tool)})
    if missing:
        log(f"Ставлю на хост: {' '.join(missing)}")
        # Без recommends: libvirt и его мост на хосте не нужны.
        run("sudo", "apt-get", "install", "-y", "--no-install-recommends", *missing)
    if not os.access("/dev/kvm", os.R_OK | os.W_OK):
        sys.exit("Нет доступа к /dev/kvm: включите виртуализацию или добавьте себя в группу kvm")


def build_deb() -> Path:
    log("Собираю пакет")
    run("uv", "run", "python", "cli.py", "build", cwd=ROOT)
    return newest_deb()


def newest_deb() -> Path:
    debs = sorted((ROOT / "dist").glob("tenga-proxy_*_amd64.deb"), key=lambda p: p.stat().st_mtime)
    if not debs:
        sys.exit("В dist/ нет пакета: уберите --no-build")
    return debs[-1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_base_image(cache: Path) -> Path:
    """Образ качается один раз и проверяется по контрольной сумме; это не сама виртуалка."""
    cache.mkdir(parents=True, exist_ok=True)
    image = cache / IMAGE_NAME
    if image.exists():
        return image
    log(f"Скачиваю {IMAGE_NAME}")
    sums = run("curl", "-fsSL", IMAGE_URL + "SHA256SUMS", capture_output=True, text=True).stdout
    match = re.search(rf"^([0-9a-f]{{64}}) [* ]{re.escape(IMAGE_NAME)}$", sums, re.MULTILINE)
    if not match:
        sys.exit(f"В SHA256SUMS нет {IMAGE_NAME}")
    partial = image.with_suffix(".part")
    run("curl", "-fL", "--retry", "3", "-o", partial, IMAGE_URL + IMAGE_NAME)
    if sha256(partial) != match.group(1):
        partial.unlink()
        sys.exit("Контрольная сумма образа не совпала")
    partial.rename(image)
    return image


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class VirtualMachine:
    """Одна виртуалка в собственном каталоге: удаление каталога удаляет её целиком."""

    def __init__(self, directory: Path, base_image: Path, *, cpus: int, memory: int) -> None:
        self.directory = directory
        self.base_image = base_image
        self.cpus = cpus
        self.memory = memory
        self.key = directory / "id_ed25519"
        self.port = free_port()
        self.process: subprocess.Popen | None = None

    def create(self) -> None:
        self.directory.mkdir(parents=True)
        run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", self.key)
        public_key = self.key.with_suffix(".pub").read_text().strip()
        user_data = self.directory / "user-data"
        user_data.write_text(
            USER_DATA.format(public_key=public_key, packages=", ".join(GUEST_PACKAGES)),
            encoding="utf-8",
        )
        run("cloud-localds", self.directory / "seed.iso", user_data)
        run(
            "qemu-img", "create", "-q", "-f", "qcow2", "-F", "qcow2",
            "-b", self.base_image, self.directory / "disk.qcow2", "25G",
        )  # fmt: skip

    def start(self) -> None:
        log(f"Запускаю виртуалку, ssh на 127.0.0.1:{self.port}")
        self.process = subprocess.Popen(
            [
                "qemu-system-x86_64",
                "-enable-kvm",
                "-cpu",
                "host",
                "-smp",
                str(self.cpus),
                "-m",
                str(self.memory),
                "-display",
                "none",
                "-serial",
                f"file:{self.directory / 'console.log'}",
                "-drive",
                f"file={self.directory / 'disk.qcow2'},if=virtio,format=qcow2",
                "-drive",
                f"file={self.directory / 'seed.iso'},if=virtio,format=raw",
                "-nic",
                f"user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:{self.port}-:22",
            ]
        )

    def _ssh_options(self) -> list[str]:
        return [
            "-i", str(self.key),
            "-o", "IdentitiesOnly=yes",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR",
            "-o", "ConnectTimeout=10",
            "-o", "ServerAliveInterval=15",
        ]  # fmt: skip

    def ssh(self, command: str, *, check: bool = True, **kwargs) -> subprocess.CompletedProcess:
        return run(
            "ssh", *self._ssh_options(), "-p", self.port, "harness@127.0.0.1", command,
            check=check, **kwargs,
        )  # fmt: skip

    def copy_in(self, *sources: Path, target: str) -> None:
        run("scp", *self._ssh_options(), "-P", self.port, "-q", "-r", *sources,
            f"harness@127.0.0.1:{target}")  # fmt: skip

    def copy_out(self, source: str, target: Path) -> None:
        run("scp", *self._ssh_options(), "-P", self.port, "-q", "-r",
            f"harness@127.0.0.1:{source}", target, check=False)  # fmt: skip

    def _check_alive(self) -> None:
        if self.process is not None and self.process.poll() is not None:
            sys.exit(f"QEMU завершился с кодом {self.process.returncode}")

    def wait_ready(self, timeout: float = 1200) -> None:
        """Дождаться конца cloud-init; netplan apply может разорвать соединение."""
        log("Жду настройку системы: пакеты ставятся несколько минут")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._check_alive()
            result = self.ssh(
                "cloud-init status --wait >/dev/null 2>&1; echo status=$?",
                check=False, capture_output=True, text=True,
            )  # fmt: skip
            # 2 — degraded: предупреждение, а пакеты проверяет следующая команда.
            if re.search(r"status=[02]\b", result.stdout):
                probe = self.ssh(
                    f"dpkg -s {' '.join(GUEST_PACKAGES)} >/dev/null && nmcli -t general status",
                    check=False, capture_output=True, text=True,
                )  # fmt: skip
                if probe.returncode == 0:
                    return
                sys.exit(f"Система настроена не полностью:\n{probe.stderr}\n{self.console_tail()}")
            time.sleep(5)
        sys.exit(f"Виртуалка не поднялась за {timeout:.0f} с\n{self.console_tail()}")

    def console_tail(self, lines: int = 40) -> str:
        console = self.directory / "console.log"
        if not console.exists():
            return ""
        return "\n".join(console.read_text(errors="replace").splitlines()[-lines:])

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        log("Выключаю виртуалку")
        try:
            self.ssh("sudo poweroff", check=False, capture_output=True, timeout=30)
            self.process.wait(60)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()


def run_checks(vm: VirtualMachine, deb: Path, pytest_args: list[str], results: Path) -> int:
    log(f"Ставлю {deb.name}")
    vm.copy_in(deb, target="package.deb")
    vm.ssh("sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y ./package.deb </dev/null")
    vm.ssh("mkdir -p lab")
    vm.copy_in(*sorted(GUEST_DIR.glob("*.py")), target="lab/")

    log("Проверки")
    arguments = shlex.join(pytest_args)
    code = vm.ssh(
        "cd lab && sudo env PYTHONDONTWRITEBYTECODE=1 VEBLOCK_PACKAGE=$HOME/package.deb "
        "python3 -m pytest checks.py -c /dev/null --rootdir=. -p no:cacheprovider "
        "-o python_files=checks.py -v -rfEs --tb=short "
        f"--junitxml=/var/log/veblock-lab/junit.xml {arguments}",
        check=False,
    ).returncode

    results.mkdir(parents=True, exist_ok=True)
    vm.ssh("sudo chmod -R a+rX /var/log/veblock-lab", check=False)
    vm.copy_out("/var/log/veblock-lab/.", results)
    return code


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--deb", type=Path, help="Готовый пакет вместо сборки")
    parser.add_argument("--no-build", action="store_true", help="Взять самый свежий пакет из dist/")
    parser.add_argument("--workdir", type=Path, default=DEFAULT_WORKDIR)
    parser.add_argument("--cpus", type=int, default=4)
    parser.add_argument("--memory", type=int, default=4096, help="Память в МБ")
    parser.add_argument("--keep", action="store_true", help="Не удалять виртуалку после проверок")
    parser.add_argument(
        "--purge-image", action="store_true", help="Удалить и скачанный образ Ubuntu"
    )
    parser.add_argument("pytest_args", nargs="*", help="Аргументы pytest: например -- -k docker")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    # SIGTERM должен пройти через finally: иначе виртуалка останется работать.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    ensure_host_tools()
    deb = args.deb or (newest_deb() if args.no_build else build_deb())

    args.workdir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(args.workdir).free
    if free < MIN_FREE_BYTES:
        sys.exit(f"В {args.workdir} свободно {free // 1024**3} ГБ, нужно 12")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    results = args.workdir / f"results-{stamp}"
    base_image = fetch_base_image(args.workdir / "image-cache")
    vm = VirtualMachine(
        args.workdir / f"vm-{stamp}", base_image, cpus=args.cpus, memory=args.memory
    )

    code = 1
    try:
        vm.create()
        vm.start()
        vm.wait_ready()
        code = run_checks(vm, deb, args.pytest_args, results)
    finally:
        vm.stop()
        if args.keep:
            print(f"Виртуалка оставлена: {vm.directory}, ключ {vm.key}")
        else:
            shutil.rmtree(vm.directory, ignore_errors=True)
            print("Виртуалка удалена")
        if args.purge_image:
            shutil.rmtree(args.workdir / "image-cache", ignore_errors=True)
            print("Образ Ubuntu удалён")

    print(
        textwrap.dedent(
            f"""
            Журналы: {results}
            Итог: {"проверки пройдены" if code == 0 else f"есть провалы, код pytest {code}"}
            """
        )
    )
    return code


if __name__ == "__main__":
    sys.exit(main())
