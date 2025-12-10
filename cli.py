#!/usr/bin/env python3
import argparse
import json
import logging
import re
import signal
import subprocess
import sys
from pathlib import Path

from src import __version__
from src.core import init_context
from src.core.config import CLI_LOG_FILE, CORE_BIN_DIR, SINGBOX_BINARY_NAME, find_singbox_binary
from src.core.logging_utils import setup_logging as setup_core_logging
from src.fmt import parse_link, parse_subscription_content
from src.sys.proxy import clear_system_proxy, set_system_proxy

logger = logging.getLogger("tenga.cli")


def cmd_parse(args: argparse.Namespace) -> int:
    """Parse a share link and print information."""
    link = args.link

    print(f"Parsing link: {link[:60]}...")
    print()

    bean = parse_link(link)

    if not bean:
        print("[ERROR] Не удалось распарсить ссылку")
        return 1

    if args.format == "json":
        result = bean.build_core_obj_singbox()
        print(json.dumps(result["outbound"], indent=2, ensure_ascii=False))
    else:
        print(f"Тип: {bean.proxy_type.upper()}")
        print(f"Имя: {bean.name or '(без имени)'}")
        print(f"Сервер: {bean.display_address}")

        if hasattr(bean, 'uuid'):
            print(f"UUID: {bean.uuid}")
        if hasattr(bean, 'password') and bean.password:
            print(f"Password: {bean.password[:20]}...")
        if hasattr(bean, 'method'):
            print(f"Method: {bean.method}")
        if hasattr(bean, 'flow') and bean.flow:
            print(f"Flow: {bean.flow}")

        stream = bean.get_stream()
        if stream:
            print(f"Network: {stream.network}")
            print(f"Security: {stream.security or 'none'}")
            if stream.sni:
                print(f"SNI: {stream.sni}")
            if stream.alpn:
                print(f"ALPN: {stream.alpn}")

    return 0


def cmd_subscription(args: argparse.Namespace) -> int:
    """Download and parse a subscription."""
    url = args.url

    print(f"Загрузка подписки: {url}")
    print()

    try:
        try:
            import requests
        except ImportError:
            print("[ERROR] Модуль 'requests' не установлен")
            print("Установите: pip install requests")
            return 1

        response = requests.get(url, timeout=30)
        response.raise_for_status()
        content = response.text

        print(f"[OK] Подписка загружена ({len(content)} байт)")
        print()

        profiles = parse_subscription_content(content)

        print(f"Найдено профилей: {len(profiles)}")
        print()

        if args.format == "json":
            outbounds = []
            for profile in profiles:
                result = profile.build_core_obj_singbox()
                outbounds.append(result["outbound"])
            print(json.dumps(outbounds, indent=2, ensure_ascii=False))
        else:
            for i, profile in enumerate(profiles, 1):
                print(f"{i}. [{profile.proxy_type.upper()}] {profile.display_name}")
                print(f"   {profile.display_address}")
                print()

        return 0

    except Exception as e:
        print(f"[ERROR] Ошибка: {e}")
        return 1


def cmd_generate(args: argparse.Namespace) -> int:
    """Generate sing-box configuration from a link."""
    link = args.link

    print("Генерация конфигурации...")
    print()

    bean = parse_link(link)

    if not bean:
        print("[ERROR] Не удалось распарсить ссылку")
        return 1

    result = bean.build_core_obj_singbox()

    if result.get("error"):
        print(f"[WARN] Предупреждение: {result['error']}")

    outbound = result["outbound"]
    if "tag" not in outbound:
        outbound["tag"] = "proxy"

    config = {
        "log": {
            "level": "info",
            "timestamp": True
        },
        "inbounds": [
            {
                "type": "mixed",
                "listen": "127.0.0.1",
                "listen_port": args.port,
                "sniff": True
            }
        ],
        "outbounds": [
            {"type": "direct", "tag": "direct"},
            outbound
        ],
        "route": {
            "rules": [
                {
                    "ip_cidr": [
                        "127.0.0.0/8",
                        "10.0.0.0/8",
                        "172.16.0.0/12",
                        "192.168.0.0/16",
                        "169.254.0.0/16",
                        "::1/128",
                        "fc00::/7",
                        "fe80::/10"
                    ],
                    "outbound": "direct"
                }
            ],
            "final": outbound["tag"],
            "auto_detect_interface": False
        }
    }

    config_json = json.dumps(config, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(config_json, encoding='utf-8')
        print(f"[OK] Конфигурация сохранена в: {args.output}")
    else:
        print(config_json)

    return 0


def cmd_add(args: argparse.Namespace) -> int:
    """Add a profile from a share link."""
    context = init_context()

    link = args.link

    bean = parse_link(link)
    if not bean:
        print("[ERROR] Не удалось распарсить ссылку")
        return 1

    entry = context.profiles.add_profile(bean)
    context.profiles.save()

    print(f"[OK] Профиль добавлен: {entry.name} (ID: {entry.id})")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """Show the list of profiles."""
    context = init_context()

    profiles = context.profiles.get_current_group_profiles()

    if not profiles:
        print("Нет профилей")
        return 0

    print(f"Профили (группа {context.profiles.current_group_id}):")
    print()

    for i, profile in enumerate(profiles, 1):
        latency = f"{profile.latency_ms}ms" if profile.latency_ms >= 0 else "-"
        print(f"  {i}. [ID: {profile.id}] [{profile.proxy_type.upper()}] {profile.name}")
        print(f"      {profile.bean.display_address} | Latency: {latency}")

    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    """Remove profile."""
    context = init_context()

    try:
        profile_id = int(args.profile_id)
    except ValueError:
        print(f"[ERROR] Неверный ID профиля: {args.profile_id}")
        return 1

    profile = context.profiles.get_profile(profile_id)
    if not profile:
        print(f"[ERROR] Профиль с ID {profile_id} не найден")
        return 1

    if context.profiles.remove_profile(profile_id):
        context.profiles.save()
        print(f"[OK] Профиль удалён: {profile.name} (ID: {profile_id})")
        return 0
    print("[ERROR] Не удалось удалить профиль")
    return 1


def cmd_version(args: argparse.Namespace) -> int:
    """Show version information."""
    from src import __app_name__, __version__

    print(f"{__app_name__} {__version__}")

    # Check sing-box version
    singbox_path = find_singbox_binary()
    if singbox_path:
        try:
            result = subprocess.run(
                [singbox_path, "version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                print(f"sing-box: {result.stdout.strip()}")
        except Exception:
            print("sing-box: не удалось определить версию")
    else:
        print("sing-box: не найден")

    return 0


def cmd_bump_version(args: argparse.Namespace) -> int:
    """Обновить версию в проекте."""
    project_root = Path(__file__).parent
    init_file = project_root / "src" / "__init__.py"
    build_script = project_root / "core" / "scripts" / "build_appimage.sh"
    pyproject_file = project_root / "pyproject.toml"

    if not init_file.exists():
        print(f"[ERROR] Файл {init_file} не найден")
        return 1

    if not build_script.exists():
        print(f"[ERROR] Файл {build_script} не найден")
        return 1

    current_version = __version__
    print("==========================================")
    print("      Tenga Proxy - Bump Version          ")
    print("==========================================")
    print()
    print(f"Текущая версия: {current_version}")
    print()

    if args.version:
        new_version = args.version
    else:
        new_version = input("Введите новую версию (например, 1.3.0): ").strip()

    if not new_version:
        print("[ERROR] Версия не введена")
        return 1

    # Validate version format
    if not re.match(r'^\d+\.\d+\.\d+$', new_version):
        print("[ERROR] Неверный формат версии. Используйте формат X.Y.Z (например, 1.3.0)")
        return 1

    if current_version == new_version:
        if not args.force:
            response = input("Новая версия совпадает с текущей. Продолжить? (y/N): ").strip()
            if response.lower() != 'y':
                print("[INFO] Отменено")
                return 0

    print()
    print(f"[INFO] Обновление версии с {current_version} на {new_version}...")

    # Update src/__init__.py
    content = init_file.read_text(encoding='utf-8')
    content = re.sub(
        r'__version__ = ".*"',
        f'__version__ = "{new_version}"',
        content
    )
    init_file.write_text(content, encoding='utf-8')
    print(f"[OK] Версия обновлена в {init_file}")

    # Update build_appimage.sh
    content = build_script.read_text(encoding='utf-8')
    content = re.sub(
        r'APP_VERSION=".*"',
        f'APP_VERSION="{new_version}"',
        content
    )
    build_script.write_text(content, encoding='utf-8')
    print(f"[OK] Версия обновлена в {build_script}")

    # Update pyproject.toml
    if pyproject_file.exists():
        content = pyproject_file.read_text(encoding='utf-8')
        content = re.sub(
            r'version = ".*"',
            f'version = "{new_version}"',
            content
        )
        pyproject_file.write_text(content, encoding='utf-8')
        print(f"[OK] Версия обновлена в {pyproject_file}")

    print()
    print("[OK] Версия успешно обновлена!")
    print()

    if args.build:
        print("[INFO] Запуск сборки AppImage...")
        print()
        build_args = argparse.Namespace()
        return cmd_build(build_args)

    return 0


def cmd_build(args: argparse.Namespace) -> int:
    """Собрать AppImage."""
    project_root = Path(__file__).parent
    build_script = project_root / "core" / "scripts" / "build_appimage.sh"

    if not build_script.exists():
        print(f"[ERROR] Скрипт сборки не найден: {build_script}")
        return 1

    if not (project_root / "core" / "bin" / "sing-box").exists():
        print("[ERROR] sing-box не найден в core/bin/")
        print()
        print("Для разработки запустите:")
        print("  python cli.py setup-dev")
        return 1

    print("==========================================")
    print("      Tenga Proxy - AppImage Build        ")
    print("==========================================")
    print()

    try:
        result = subprocess.run(
            ["bash", str(build_script)],
            cwd=project_root,
            check=False
        )
        return result.returncode
    except FileNotFoundError:
        print("[ERROR] bash не найден")
        return 1


def cmd_install(args: argparse.Namespace) -> int:
    """Установить AppImage в систему."""
    project_root = Path(__file__).parent
    install_script = project_root / "core" / "scripts" / "install_appimage.sh"

    if not install_script.exists():
        print(f"[ERROR] Скрипт установки не найден: {install_script}")
        return 1

    action = "uninstall" if args.uninstall else "install"

    print("==========================================")
    print("      Tenga Proxy - Install AppImage     ")
    print("==========================================")
    print()

    try:
        result = subprocess.run(
            ["bash", str(install_script), action],
            cwd=project_root,
            check=False
        )
        return result.returncode
    except FileNotFoundError:
        print("[ERROR] bash не найден")
        return 1


def cmd_setup(args: argparse.Namespace) -> int:
    """Собрать и установить AppImage (аналог setup.sh)."""
    project_root = Path(__file__).parent

    if not (project_root / "core" / "bin" / "sing-box").exists():
        print("[ERROR] sing-box не найден в core/bin/")
        print()
        print("Для разработки запустите:")
        print("  python cli.py setup-dev")
        return 1

    print("==========================================")
    print("          Tenga Proxy - Setup             ")
    print("==========================================")
    print()

    # Step 1: Build
    print("[INFO] Шаг 1/2: Сборка AppImage...")
    build_args = argparse.Namespace()
    if cmd_build(build_args) != 0:
        print("[ERROR] Ошибка при сборке AppImage")
        return 1

    print()
    # Step 2: Install
    print("[INFO] Шаг 2/2: Установка в систему...")
    install_args = argparse.Namespace(uninstall=False)
    if cmd_install(install_args) != 0:
        print("[ERROR] Ошибка при установке")
        return 1

    print()
    print("==========================================")
    print("          Установка завершена!            ")
    print("==========================================")
    print()

    return 0


def cmd_setup_dev(args: argparse.Namespace) -> int:
    """Установить окружение для разработки."""
    project_root = Path(__file__).parent
    install_dev_script = project_root / "core" / "scripts" / "install_dev.sh"

    if not install_dev_script.exists():
        print(f"[ERROR] Скрипт установки не найден: {install_dev_script}")
        return 1

    print("==========================================")
    print("   Tenga Proxy - Dev Environment Setup   ")
    print("==========================================")
    print()

    try:
        result = subprocess.run(
            ["bash", str(install_dev_script)],
            cwd=project_root,
            check=False
        )
        return result.returncode
    except FileNotFoundError:
        print("[ERROR] bash не найден")
        return 1


def cmd_lint(args: argparse.Namespace) -> int:
    """Проверить код линтером (ruff)."""
    project_root = Path(__file__).parent

    try:
        if args.fix:
            # Исправить автоматически исправимые проблемы
            print("[INFO] Запуск ruff check --fix...")
            result = subprocess.run(
                ["ruff", "check", "--fix", str(project_root)],
                cwd=project_root,
                check=False
            )
            return result.returncode
        # Только проверка
        print("[INFO] Запуск ruff check...")
        result = subprocess.run(
            ["ruff", "check", str(project_root)],
            cwd=project_root,
            check=False
        )
        return result.returncode
    except FileNotFoundError:
        print("[ERROR] ruff не найден")
        print("Установите: pip install ruff")
        print("Или: pip install -e '.[dev]'")
        return 1


def cmd_format(args: argparse.Namespace) -> int:
    """Отформатировать код (ruff format)."""
    project_root = Path(__file__).parent

    try:
        if args.check:
            # Только проверка форматирования
            print("[INFO] Проверка форматирования...")
            result = subprocess.run(
                ["ruff", "format", "--check", str(project_root)],
                cwd=project_root,
                check=False
            )
            return result.returncode
        # Форматирование
        print("[INFO] Форматирование кода...")
        result = subprocess.run(
            ["ruff", "format", str(project_root)],
            cwd=project_root,
            check=False
        )
        return result.returncode
    except FileNotFoundError:
        print("[ERROR] ruff не найден")
        print("Установите: pip install ruff")
        print("Или: pip install -e '.[dev]'")
        return 1


def cmd_lint_all(args: argparse.Namespace) -> int:
    """Запустить все проверки: линтинг и форматирование."""
    print("==========================================")
    print("      Tenga Proxy - Code Quality         ")
    print("==========================================")
    print()

    # Проверка форматирования
    print("[1/2] Проверка форматирования...")
    format_args = argparse.Namespace(check=True)
    format_result = cmd_format(format_args)

    if format_result != 0:
        print("[WARN] Код не отформатирован. Запустите: python cli.py format")
        print()

    # Проверка линтинга
    print("[2/2] Проверка линтинга...")
    lint_args = argparse.Namespace(fix=False)
    lint_result = cmd_lint(lint_args)

    print()
    if format_result == 0 and lint_result == 0:
        print("[OK] Все проверки пройдены!")
        return 0
    print("[ERROR] Обнаружены проблемы")
    if format_result != 0:
        print("  - Запустите: python cli.py format")
    if lint_result != 0:
        print("  - Запустите: python cli.py lint --fix")
    return 1


def find_core_binary() -> str | None:
    """
    Find proxy binary for CLI (sing-box).
    
    Selection priority:
    1. sing-box in core/bin/ directory
    2. system-wide sing-box
    
    CLI uses only sing-box (not nekobox_core).
    """
    # check sing-box in project
    singbox_path = CORE_BIN_DIR / SINGBOX_BINARY_NAME
    if singbox_path.exists() and singbox_path.is_file():
        try:
            result = subprocess.run(
                [str(singbox_path), "version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                print(f"[OK] sing-box найден: {result.stdout.strip()}")
                return str(singbox_path)
        except Exception:
            pass

    # check sing-box in system
    path = find_singbox_binary()
    if path == "sing-box":
        try:
            result = subprocess.run(
                ["sing-box", "version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                msg = f"sing-box найден: {result.stdout.strip()}"
                print(f"[OK] {msg}")
                logger.info(msg)
                return "sing-box"
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[WARN] Ошибка проверки sing-box: {e}")
            logger.exception("Ошибка проверки системного sing-box: %s", e)

    return None


def cmd_run(args: argparse.Namespace) -> int:
    """Run the proxy."""
    context = init_context()
    bean = None

    # Get profile or link
    if args.link:
        profile_identifier = args.link

        try:
            profile_num = int(profile_identifier)
            profiles = context.profiles.get_current_group_profiles()

            profile = context.profiles.get_profile(profile_num)
            if profile and profile.group_id == context.profiles.current_group_id:
                bean = profile.bean
                print(f"[OK] Найден профиль по ID: {profile.name}")
            else:
                if 1 <= profile_num <= len(profiles):
                    profile = profiles[profile_num - 1]
                    bean = profile.bean
                    print(f"[OK] Найден профиль по номеру {profile_num}: {profile.name}")
                else:
                    print(f"[ERROR] Профиль с номером {profile_num} не найден (всего профилей: {len(profiles)})")
                    return 1
        except ValueError:
            # Not a number - try to find by profile name
            profiles = context.profiles.get_current_group_profiles()
            found_profile = None
            for profile in profiles:
                if profile.name == profile_identifier or profile.name.lower() == profile_identifier.lower():
                    found_profile = profile
                    break

            if found_profile:
                bean = found_profile.bean
                print(f"[OK] Найден профиль по имени: {found_profile.name}")
            else:
                # Not found by name - treat as share link
                if Path(profile_identifier).exists():
                    link = Path(profile_identifier).read_text().strip()
                else:
                    link = profile_identifier

                print("[INFO] Парсинг ссылки...")
                bean = parse_link(link)

                if not bean:
                    print("[ERROR] Не удалось найти профиль или распарсить ссылку")
                    print(f"   Имя/ID: {profile_identifier}")
                    return 1

                print(f"[OK] Парсинг успешен: {bean.display_name}")
    else:
        print("[ERROR] Укажите ID профиля, порядковый номер, имя профиля или share link")
        return 1

    try:
        result = bean.build_core_obj_singbox()

        if result.get("error"):
            raise ValueError(f"Ошибка генерации: {result['error']}")

        outbound = result["outbound"]
        if "tag" not in outbound:
            outbound["tag"] = "proxy"

        config = {
            "log": {"level": "info", "timestamp": True},
            "inbounds": [
                {"type": "mixed", "listen": "127.0.0.1", "listen_port": args.port, "sniff": True}
            ],
            "outbounds": [{"type": "direct", "tag": "direct"}, outbound],
            "route": {
                "rules": [
                    {
                        "ip_cidr": [
                            "127.0.0.0/8",
                            "10.0.0.0/8",
                            "172.16.0.0/12",
                            "192.168.0.0/16",
                            "169.254.0.0/16",
                            "::1/128",
                            "fc00::/7",
                            "fe80::/10"
                        ],
                        "outbound": "direct"
                    }
                ],
                "final": outbound["tag"],
                "auto_detect_interface": False
            }
        }

        config_path = Path(__file__).parent / "core" / "proxy_config.json"
        config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"[OK] Конфигурация сохранена: {config_path}")

        core_binary = find_core_binary()

        if not core_binary:
            print("\n[ERROR] sing-box не найден!")
            print("\nВарианты решения:")
            print("1. Установите sing-box: https://github.com/SagerNet/sing-box/releases")
            print("2. Поместите sing-box в директорию core/bin/")
            print("3. Или установите системно: sudo apt install sing-box")
            return 1

        if not args.no_system_proxy:
            print(f"\n[INFO] Настройка системного прокси на порт {args.port}...")
            if set_system_proxy(http_port=args.port, socks_port=args.port):
                print("[OK] Системный прокси настроен")
            else:
                print("[WARN] Не удалось настроить системный прокси")

        print("\n[INFO] Запуск sing-box...")
        print(f"[INFO] Прокси доступен на: 127.0.0.1:{args.port}")
        print(f"   HTTP: http://127.0.0.1:{args.port}")
        print(f"   SOCKS5: socks5://127.0.0.1:{args.port}")
        print("\nНажмите Ctrl+C для остановки\n")

        # Signal handling
        def signal_handler(sig, frame):
            print("\n\n[STOP] Остановка...")
            if not args.no_system_proxy:
                clear_system_proxy()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            process = subprocess.Popen(
                [core_binary, "run", "-c", str(config_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            for line in process.stdout:
                print(line, end='')

            process.wait()

        except KeyboardInterrupt:
            print("\n\n[STOP] Остановка sing-box...")
            process.terminate()
            process.wait()
            print("[OK] sing-box остановлен")
        finally:
            if not args.no_system_proxy:
                clear_system_proxy()

        return 0

    except Exception as e:
        print(f"\n[ERROR] Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return 1


def main() -> int:
    """Main entry point."""
    setup_core_logging(CLI_LOG_FILE, level=logging.INFO)
    logger.info("Starting Tenga CLI, log file: %s", CLI_LOG_FILE)

    parser = argparse.ArgumentParser(
        description='Tenga CLI - консольный клиент прокси',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Примеры:\n'
               '  %(prog)s parse "vless://..."\n'
               '  %(prog)s add "vless://..."\n'
               '  %(prog)s ls\n'
               '  %(prog)s run 1\n'
               '  %(prog)s ver\n'
               '  %(prog)s setup\n'
               '  %(prog)s build\n'
               '  %(prog)s install\n'
               '  %(prog)s bump-version 1.6.0\n'
               '  %(prog)s lint --fix\n'
               '  %(prog)s format',
    )

    subparsers = parser.add_subparsers(dest='command', help='Команды')

    parse_parser = subparsers.add_parser('parse', help='Парсить share link')
    parse_parser.add_argument('link', help='Share link')
    parse_parser.add_argument(
        '-f', '--format',
        choices=['json', 'text'],
        default='text',
        help='Формат вывода'
    )

    sub_parser = subparsers.add_parser('sub', help='Загрузить подписку')
    sub_parser.add_argument('url', help='URL подписки')
    sub_parser.add_argument(
        '-f', '--format',
        choices=['json', 'list'],
        default='list',
        help='Формат вывода'
    )

    gen_parser = subparsers.add_parser('gen', help='Сгенерировать конфигурацию')
    gen_parser.add_argument('link', help='Share link')
    gen_parser.add_argument('-o', '--output', help='Файл для сохранения')
    gen_parser.add_argument('-p', '--port', type=int, default=2080, help='Порт прокси')

    add_parser = subparsers.add_parser('add', help='Добавить профиль')
    add_parser.add_argument('link', help='Share link')

    subparsers.add_parser('ls', help='Показать профили')

    remove_parser = subparsers.add_parser('rm', help='Удалить профиль')
    remove_parser.add_argument('profile_id', help='ID профиля для удаления')

    subparsers.add_parser('ver', help='Показать версию')

    run_parser = subparsers.add_parser('run', help='Запустить прокси')
    run_parser.add_argument('link', nargs='?', help='ID профиля, порядковый номер (из list), имя профиля или share link (или путь к файлу)')
    run_parser.add_argument('-p', '--port', type=int, default=2080, help='Порт прокси')
    run_parser.add_argument('--no-system-proxy', action='store_true', help='Не настраивать системный прокси')

    # Build and installation commands
    setup_parser = subparsers.add_parser('setup', help='Собрать и установить AppImage в систему')

    build_parser = subparsers.add_parser('build', help='Собрать AppImage')

    install_parser = subparsers.add_parser('install', help='Установить AppImage в систему')
    install_parser.add_argument('--uninstall', action='store_true', help='Удалить AppImage из системы')

    bump_version_parser = subparsers.add_parser('bump-version', help='Обновить версию проекта')
    bump_version_parser.add_argument('version', nargs='?', help='Новая версия (например, 1.3.0)')
    bump_version_parser.add_argument('--force', action='store_true', help='Принудительно обновить, даже если версия совпадает')
    bump_version_parser.add_argument('--build', action='store_true', help='Запустить сборку AppImage после обновления версии')

    setup_dev_parser = subparsers.add_parser('setup-dev', help='Установить окружение для разработки')

    # Code quality commands
    lint_parser = subparsers.add_parser('lint', help='Проверить код линтером (ruff)')
    lint_parser.add_argument('--fix', action='store_true', help='Исправить автоматически исправимые проблемы')

    format_parser = subparsers.add_parser('format', help='Отформатировать код (ruff format)')
    format_parser.add_argument('--check', action='store_true', help='Только проверить форматирование, не изменять файлы')

    lint_all_parser = subparsers.add_parser('lint-all', help='Запустить все проверки: линтинг и форматирование')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    commands = {
        'parse': cmd_parse,
        'sub': cmd_subscription,
        'gen': cmd_generate,
        'add': cmd_add,
        'ls': cmd_list,
        'rm': cmd_remove,
        'ver': cmd_version,
        'run': cmd_run,
        'setup': cmd_setup,
        'build': cmd_build,
        'install': cmd_install,
        'bump-version': cmd_bump_version,
        'setup-dev': cmd_setup_dev,
        'lint': cmd_lint,
        'format': cmd_format,
        'lint-all': cmd_lint_all,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
