#!/usr/bin/env python3
import sys
import json
import argparse
import subprocess
import signal
from pathlib import Path
import logging

from src.fmt import parse_link, parse_subscription_content
from src.core import init_context
from src.core.config import CORE_BIN_DIR, SINGBOX_BINARY_NAME, CLI_LOG_FILE, find_singbox_binary
from src.core.logging_utils import setup_logging as setup_core_logging
from src.sys.proxy import set_system_proxy, clear_system_proxy


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
    else:
        print(f"[ERROR] Не удалось удалить профиль")
        return 1


def cmd_version(args: argparse.Namespace) -> int:
    """Show version information."""
    from src import __version__, __app_name__
    
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
               '  %(prog)s ver',
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
    }
    
    handler = commands.get(args.command)
    if handler:
        return handler(args)
    
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
