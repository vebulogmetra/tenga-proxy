"""Building xray-core configurations for a profile.

Extracted from the GTK application so the logic can be reused by the new UI and
tested without a display. Behaviour is unchanged: the functions take the
AppContext explicitly instead of reading it from `self`.
"""

from __future__ import annotations

import json
import logging
import random
import socket

from src.core.context import AppContext
from src.core.proxy_mode import build_inbounds_for_mode
from src.db.config import DEFAULT_ROUTING_ORDER, LOCAL_NETWORKS, ProxyMode, RoutingMode
from src.db.profiles import ProfileEntry
from src.sys.vpn import (
    get_default_interface,
    get_vpn_dns_servers,
    get_vpn_interface,
    is_vpn_active,
)

logger = logging.getLogger("tenga.core.config_builder")


def build_session_config(context: AppContext, profile: ProfileEntry | None) -> dict | None:
    """Create xray-core configuration for profile."""
    try:
        result = profile.bean.build_core_obj_xray()

        if result.get("error"):
            logger.error(
                "Error creating profile configuration %s: %s",
                profile.id,
                result["error"],
            )
            return None

        outbound = result["outbound"]
        if "tag" not in outbound:
            outbound["tag"] = "proxy"

        proxy_tag = outbound["tag"]
        port = context.config.inbound_socks_port

        routing = profile.routing_settings
        if routing is None:
            routing = context.config.routing
            if routing.mode == RoutingMode.CUSTOM:
                routing.load_lists_from_files(context.config_dir)

        route_rules: list[dict] = []
        vpn_settings = profile.vpn_settings
        vpn_tag = None
        vpn_interface = None
        over_vpn_domains_for_dns = []
        direct_domains: list[str] = []
        direct_ips: list[str] = []
        vpn_domains: list[str] = []
        vpn_ips: list[str] = []
        proxy_domains: list[str] = []
        proxy_ips: list[str] = []

        # Process VPN routing rules (only if VPN is enabled and active)
        if vpn_settings and vpn_settings.enabled:
            if is_vpn_active(vpn_settings.connection_name):
                if vpn_settings.interface_name:
                    vpn_interface = vpn_settings.interface_name
                else:
                    vpn_interface = get_vpn_interface(vpn_settings.connection_name)

                if vpn_interface:
                    vpn_tag = "vpn"
                    logger.info("VPN integration enabled, interface: %s", vpn_interface)
                else:
                    logger.warning("VPN is enabled but interface not found")
            else:
                logger.warning(
                    "VPN integration enabled but connection '%s' is not active",
                    vpn_settings.connection_name,
                )

        if routing.mode == RoutingMode.PROXY_ALL:
            if routing.bypass_local_networks:
                local_networks = list(LOCAL_NETWORKS)
                route_rules.append(
                    {
                        "type": "field",
                        "ip": local_networks,
                        "outboundTag": "direct",
                    }
                )
                logger.debug("Added local networks bypass rule for PROXY_ALL mode")
        elif routing.mode == RoutingMode.CUSTOM:
            direct_list = list(routing.direct_list) if routing.direct_list else []

            if routing.bypass_local_networks:
                local_networks = list(LOCAL_NETWORKS)
                for network in local_networks:
                    if network not in direct_list:
                        direct_list.append(network)

            if direct_list:
                direct_domains, direct_ips = routing.parse_entries(direct_list)

            if routing.vpn_list and vpn_tag and vpn_interface:
                vpn_domains, vpn_ips = routing.parse_entries(routing.vpn_list)
                if vpn_domains:
                    over_vpn_domains_for_dns = vpn_domains

            if routing.proxy_list:
                proxy_domains, proxy_ips = routing.parse_entries(routing.proxy_list)

            try:
                rule_order = routing.get_rule_order()
            except AttributeError:
                rule_order = DEFAULT_ROUTING_ORDER

            for group in rule_order:
                if group == "direct":
                    if direct_ips:
                        route_rules.append(
                            {
                                "type": "field",
                                "ip": direct_ips,
                                "outboundTag": "direct",
                            }
                        )
                        logger.debug(
                            "Added DIRECT routing from list for IPs (order %s): %s",
                            rule_order,
                            direct_ips,
                        )
                    if direct_domains:
                        route_rules.append(
                            {
                                "type": "field",
                                "domain": direct_domains,
                                "outboundTag": "direct",
                            }
                        )
                        logger.debug(
                            "Added DIRECT routing from list for domains (order %s): %s",
                            rule_order,
                            direct_domains,
                        )
                elif group == "vpn" and vpn_tag and vpn_interface:
                    if vpn_ips:
                        route_rules.append(
                            {
                                "type": "field",
                                "ip": vpn_ips,
                                "outboundTag": vpn_tag,
                            }
                        )
                        logger.debug(
                            "Added VPN routing from list for IPs (order %s): %s",
                            rule_order,
                            vpn_ips,
                        )
                    if vpn_domains:
                        route_rules.append(
                            {
                                "type": "field",
                                "domain": vpn_domains,
                                "outboundTag": vpn_tag,
                            }
                        )
                        logger.debug(
                            "Added VPN routing from list for domains (order %s): %s",
                            rule_order,
                            vpn_domains,
                        )
                elif group == "proxy":
                    if proxy_ips:
                        route_rules.append(
                            {
                                "type": "field",
                                "ip": proxy_ips,
                                "outboundTag": proxy_tag,
                            }
                        )
                        logger.debug(
                            "Added PROXY routing from list for IPs (order %s): %s",
                            rule_order,
                            proxy_ips,
                        )
                    if proxy_domains:
                        route_rules.append(
                            {
                                "type": "field",
                                "domain": proxy_domains,
                                "outboundTag": proxy_tag,
                            }
                        )
                        logger.debug(
                            "Added PROXY routing from list for domains (order %s): %s",
                            rule_order,
                            proxy_domains,
                        )

        # Outbounds
        direct_outbound = {"protocol": "freedom", "tag": "direct"}
        if vpn_tag and vpn_interface and vpn_settings:
            direct_interface = getattr(vpn_settings, "direct_interface", "") or ""
            if not direct_interface:
                direct_interface = get_default_interface(vpn_interface)

            if direct_interface:
                direct_outbound["streamSettings"] = {
                    "sockopt": {
                        "interface": direct_interface,
                    },
                }
                logger.info(
                    "Direct outbound bound to interface: %s (bypassing VPN %s)",
                    direct_interface,
                    vpn_interface,
                )

                # CRITICAL: Proxy outbound must also use direct interface to reach proxy server
                # Otherwise it goes through VPN tunnel which may not route to proxy correctly
                if "streamSettings" not in outbound:
                    outbound["streamSettings"] = {}
                if "sockopt" not in outbound["streamSettings"]:
                    outbound["streamSettings"]["sockopt"] = {}
                outbound["streamSettings"]["sockopt"]["interface"] = direct_interface
                logger.info(
                    "Proxy outbound bound to interface: %s (bypassing VPN to reach proxy server)",
                    direct_interface,
                )

        outbounds = [
            outbound,
            direct_outbound,
        ]

        if vpn_tag and vpn_interface:
            vpn_outbound = {
                "protocol": "freedom",
                "tag": vpn_tag,
                "settings": {
                    "domainStrategy": "UseIPv4",
                },
                "streamSettings": {
                    "sockopt": {
                        "interface": vpn_interface,
                    },
                },
            }

            logger.info(
                "Added VPN outbound with interface: %s",
                vpn_interface,
            )
            outbounds.append(vpn_outbound)

        if vpn_settings:
            if vpn_settings.enabled:
                if vpn_tag:
                    logger.info(
                        "Profile configuration: VPN enabled and active, proxy + VPN routing"
                    )
                else:
                    logger.info("Profile configuration: VPN enabled but not active, proxy only")
            else:
                logger.info("Profile configuration: VPN disabled, proxy + direct rules (if any)")
        else:
            logger.info("Profile configuration: No VPN settings, proxy only")
        # DNS (xray-core format)
        dns_settings = context.config.dns
        dns_url = dns_settings.get_dns_url()
        dns_detour = proxy_tag if dns_settings.use_proxy else "direct"

        # Extract proxy server address from profile bean (not from outbound config)
        # For VLESS/VMess/etc the server is in settings.vnext[0].address, not in outbound.server
        vps_server = profile.bean.server_address if profile.bean else ""

        # IMPORTANT: When VPN is enabled, disable DoH/DoT to avoid circular DNS dependencies
        # VPN already provides DNS privacy through its tunnel
        if vpn_tag and vpn_interface and dns_url.startswith(("https://", "tls://")):
            logger.info(
                "VPN enabled: switching from DoH/DoT to localhost DNS "
                "to avoid circular dependencies"
            )
            dns_url = "local"

        # Build DNS servers list (new format: type + server instead of address)
        dns_servers = []

        # Main DNS server
        if dns_url == "local":
            dns_servers.append(
                {
                    "tag": "main-dns",
                    "type": "local",
                    "detour": dns_detour,
                }
            )
        elif dns_url.startswith("https://"):
            # DoH server
            from urllib.parse import urlparse

            parsed = urlparse(dns_url)
            server_host = parsed.netloc.split(":")[0] if ":" in parsed.netloc else parsed.netloc
            server_port = parsed.port if parsed.port else 443
            path = parsed.path if parsed.path else "/dns-query"

            dns_servers.append(
                {
                    "tag": "main-dns",
                    "type": "https",
                    "server": server_host,
                    "server_port": server_port,
                    "path": path,
                    "detour": dns_detour,
                }
            )
        elif dns_url.startswith("tls://"):
            # DoT server
            server = dns_url.replace("tls://", "").split(":")[0]
            port = 853
            if ":" in dns_url.replace("tls://", ""):
                port = int(dns_url.split(":")[-1])

            dns_servers.append(
                {
                    "tag": "main-dns",
                    "type": "tls",
                    "server": server,
                    "server_port": port,
                    "detour": dns_detour,
                }
            )
        else:
            # Plain IP or domain - use UDP
            server = dns_url.replace("udp://", "").replace("tcp://", "")
            dns_servers.append(
                {
                    "tag": "main-dns",
                    "type": "udp",
                    "server": server,
                    "detour": dns_detour,
                }
            )

        # Local DNS server (no detour needed for local type)
        dns_servers.append(
            {
                "tag": "local-dns",
                "type": "local",
            }
        )

        if vpn_tag and vpn_interface and over_vpn_domains_for_dns:
            # Get DNS servers from VPN connection settings
            vpn_dns_servers = get_vpn_dns_servers(vpn_settings.connection_name)

            if vpn_dns_servers:
                # Use first DNS server from VPN settings
                vpn_dns_ip = vpn_dns_servers[0]
                logger.debug("Raw VPN DNS server from NetworkManager: %s", vpn_dns_ip)

                # Clean up the address: remove protocol prefixes, brackets, etc.
                clean_ip = vpn_dns_ip.strip()

                # Remove protocol prefixes
                for prefix in ["udp://", "tcp://", "tls://", "https://"]:
                    if clean_ip.startswith(prefix):
                        clean_ip = clean_ip[len(prefix) :]

                # Remove brackets if present
                clean_ip = clean_ip.strip("[]")

                # Handle NetworkManager format like "IP4.DNS[1]:10.222.0.7:53" or "IP4.DNS[1]:10.222.0.7"
                # Extract IP address and port using regex-like approach
                import re

                # Pattern to match IP address (IPv4 or IPv6) with optional port
                ip_pattern = r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?::(\d+))?"
                ipv6_pattern = r"([0-9a-fA-F:]+)(?::(\d+))?"

                # Try to find IP address in the string
                match = re.search(ip_pattern, clean_ip)
                if not match:
                    match = re.search(ipv6_pattern, clean_ip)

                if match:
                    server_ip = match.group(1)
                    server_port = int(match.group(2)) if match.group(2) else 53
                    logger.debug(
                        "Extracted IP: %s, port: %d from: %s",
                        server_ip,
                        server_port,
                        vpn_dns_ip,
                    )
                else:
                    # Fallback: try to extract by splitting on colons
                    # Remove any non-IP prefix (like "IP4.DNS[1]:")
                    parts = clean_ip.split(":")
                    # Find the part that looks like an IP address
                    for part in parts:
                        # Check if part looks like an IP (contains dots or is IPv6)
                        if "." in part or ":" in part:
                            # This might be the IP
                            ip_candidate = part
                            port_candidate = 53
                            # Check if next part is a number (port)
                            part_idx = parts.index(part)
                            if part_idx + 1 < len(parts):
                                try:
                                    port_candidate = int(parts[part_idx + 1])
                                except (ValueError, IndexError):
                                    pass

                            # Validate IP format
                            if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip_candidate):
                                server_ip = ip_candidate
                                server_port = port_candidate
                                logger.debug(
                                    "Extracted IP (fallback): %s, port: %d from: %s",
                                    server_ip,
                                    server_port,
                                    vpn_dns_ip,
                                )
                                break
                    else:
                        # No valid IP found, use fallback
                        logger.error("Could not extract IP address from: %s", vpn_dns_ip)
                        server_ip = "8.8.8.8"
                        server_port = 53

                # Final validation: server_ip should be a valid IP format
                if not re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", server_ip):
                    logger.error(
                        "Invalid VPN DNS server IP format: %s (from: %s)", server_ip, vpn_dns_ip
                    )
                    server_ip = "8.8.8.8"  # Fallback
                    server_port = 53

                logger.info(
                    "Using VPN DNS server %s:%d for over_vpn domains (from connection %s, original: %s, available: %s)",
                    server_ip,
                    server_port,
                    vpn_settings.connection_name,
                    vpn_dns_ip,
                    vpn_dns_servers,
                )
                # Use detour to VPN outbound for UDP DNS
                # This routes DNS queries through VPN interface via VPN outbound
                dns_servers.append(
                    {
                        "tag": "vpn-dns",
                        "type": "udp",
                        "server": server_ip,
                        "server_port": server_port,
                        "detour": vpn_tag,
                    }
                )
            else:
                # Fallback to local DNS through VPN interface
                logger.warning(
                    "No DNS servers found in VPN connection %s settings, using local DNS through VPN interface",
                    vpn_settings.connection_name,
                )
                dns_servers.append(
                    {
                        "tag": "vpn-dns",
                        "type": "local",
                        "detour": vpn_tag,
                    }
                )
            logger.info("Added VPN DNS server for over_vpn domains")

        dns_rules = []

        # IMPORTANT: DNS rules are evaluated in order, so more specific rules should come first
        # 1. over_vpn domains should use VPN DNS (highest priority)
        if vpn_tag and over_vpn_domains_for_dns:
            # Use domain_suffix for matching subdomains
            dns_rules.append(
                {
                    "domain_suffix": over_vpn_domains_for_dns,
                    "server": "vpn-dns",
                }
            )
            logger.info(
                "Added DNS rule for over_vpn domains (VPN DNS): %s", over_vpn_domains_for_dns
            )

        # 2. VPS server domain should use local DNS (critical for proxy+vpn to avoid bootstrap issues)
        if vps_server and not vps_server[0].isdigit():
            dns_rules.append(
                {
                    "domain": [vps_server],
                    "server": "local-dns",
                }
            )
            logger.info("Added DNS rule for proxy server domain (local DNS): %s", vps_server)

        # Note: xray-core DNS configuration uses servers with optional domains, not separate rules

        dns_config = {
            "servers": dns_servers,
            "rules": dns_rules,
            "final": "main-dns",
        }

        # Log DNS configuration for debugging (before conversion)
        logger.info("DNS configuration (before xray-core conversion):")
        logger.info("  Servers: %s", [s.get("tag", "unknown") for s in dns_servers])
        logger.info("  Rules: %s", len(dns_rules))

        # Convert DNS config from sing-box format to xray-core format
        xray_dns_servers = []

        # Convert DNS servers
        for server in dns_servers:
            server_type = server.get("type", "local")
            server_tag = server.get("tag", "")

            if server_type == "local":
                # Check if this local DNS server has specific domains from rules
                domains_for_server = []
                for rule in dns_rules:
                    if rule.get("server") == server_tag:
                        if "domain" in rule:
                            domains_for_server.extend(rule["domain"])
                        elif "domain_suffix" in rule:
                            domains_for_server.extend(rule["domain_suffix"])

                if domains_for_server:
                    # xray-core format: localhost DNS with specific domains
                    xray_dns_servers.append(
                        {
                            "address": "localhost",
                            "domains": domains_for_server,
                        }
                    )
                else:
                    # No specific domains, just use simple localhost string
                    xray_dns_servers.append("localhost")
            elif server_type == "udp":
                addr = server.get("server", "8.8.8.8")
                port_num = server.get("server_port", 53)
                # xray-core expects UDP DNS servers as object with address and port
                # or just IP string if port is 53 (default)
                server_config = {
                    "address": addr,
                    "port": port_num,
                }
                # Add domains from DNS rules if this server is referenced
                domains_for_server = []
                for rule in dns_rules:
                    if rule.get("server") == server_tag:
                        if "domain" in rule:
                            domains_for_server.extend(rule["domain"])
                        elif "domain_suffix" in rule:
                            domains_for_server.extend(rule["domain_suffix"])
                if domains_for_server:
                    server_config["domains"] = domains_for_server
                # Note: xray-core doesn't support detour in DNS config directly
                # DNS queries routing through VPN is handled via routing rules
                xray_dns_servers.append(server_config)
            elif server_type == "tls":
                addr = server.get("server", "1.1.1.1")
                port_num = server.get("server_port", 853)
                server_config = {
                    "address": f"{addr}:{port_num}",
                }
                # Add domains from DNS rules if this server is referenced
                domains_for_server = []
                for rule in dns_rules:
                    if rule.get("server") == server_tag:
                        if "domain" in rule:
                            domains_for_server.extend(rule["domain"])
                        elif "domain_suffix" in rule:
                            domains_for_server.extend(rule["domain_suffix"])
                if domains_for_server:
                    server_config["domains"] = domains_for_server
                xray_dns_servers.append(server_config)
            elif server_type == "https":
                addr = server.get("server", "1.1.1.1")
                port_num = server.get("server_port", 443)
                path = server.get("path", "/dns-query")
                server_config = {
                    "address": f"{addr}:{port_num}",
                    "path": path,
                }
                # Add domains from DNS rules if this server is referenced
                domains_for_server = []
                for rule in dns_rules:
                    if rule.get("server") == server_tag:
                        if "domain" in rule:
                            domains_for_server.extend(rule["domain"])
                        elif "domain_suffix" in rule:
                            domains_for_server.extend(rule["domain_suffix"])
                if domains_for_server:
                    server_config["domains"] = domains_for_server
                xray_dns_servers.append(server_config)

        inbounds = build_inbounds_for_mode(
            mode=getattr(context.config, "proxy_mode", None),
            address=context.config.inbound_address,
            socks_port=port,
            tun_name=getattr(context.config, "tun_name", "xray0"),
            tun_mtu=getattr(context.config, "tun_mtu", 1500),
        )

        config = {
            "log": {"loglevel": context.config.log_level},
            "dns": {
                "servers": xray_dns_servers if xray_dns_servers else ["localhost"],
            },
            "inbounds": inbounds,
            "outbounds": outbounds,
            "routing": {
                "domainStrategy": "IPOnDemand",
                "rules": route_rules,
            },
        }

        # Note: xray-core automatically uses the first outbound as default
        # if no routing rules match. No need to add a catch-all rule.

        return config

    except Exception as e:
        logger.exception(
            "Error creating profile configuration %s: %s",
            getattr(profile, "id", "?"),
            e,
        )
        return None


def reserve_latency_port_pair(host: str) -> int:
    """
    Reserve a free consecutive TCP port pair (socks, http=socks+1).

    Args:
        host: Listen host for xray inbounds

    Returns:
        Base SOCKS port
    """
    start_port = random.randint(20000, 50000)

    for offset in range(15000):
        port = start_port + offset
        if port >= 65000:
            break

        sock_one = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock_two = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock_one.bind((host, port))
            sock_two.bind((host, port + 1))
            return port
        except OSError:
            continue
        finally:
            sock_one.close()
            sock_two.close()

    raise RuntimeError("No free consecutive port pair found for latency test")


def build_latency_probe_config(
    context: AppContext, profile: ProfileEntry | None
) -> tuple[dict, int] | None:
    """
    Create temporary xray config for latency test.

    Uses profile outbound/routing/dns from normal config but forces
    SYSTEM_PROXY inbounds to avoid TUN conflicts with active session.
    """
    config = build_session_config(context, profile)
    if not config:
        return None

    listen_host = context.config.inbound_address
    socks_port = reserve_latency_port_pair(listen_host)
    inbounds = build_inbounds_for_mode(
        mode=ProxyMode.SYSTEM_PROXY,
        address=listen_host,
        socks_port=socks_port,
        tun_name=getattr(context.config, "tun_name", "xray0"),
        tun_mtu=getattr(context.config, "tun_mtu", 1500),
    )
    config["inbounds"] = inbounds
    return config, socks_port


def probe_profile_latency(
    context: AppContext, profile_id: int, timeout_ms: int = 3000, probes: int = 3
) -> int:
    """
    Run realistic latency test for profile through temporary xray instance.

    Args:
        profile_id: Profile id to test
        timeout_ms: Probe timeout in milliseconds
        probes: Number of probes

    Returns:
        Median latency in milliseconds or -1 on failure.
    """
    profile = context.profiles.get_profile(profile_id)
    if not profile:
        logger.error("Latency test: profile %s not found", profile_id)
        return -1

    config_with_port = build_latency_probe_config(context, profile)
    if not config_with_port:
        logger.error("Latency test: failed to build config for profile %s", profile_id)
        return -1

    config, socks_port = config_with_port
    probe_manager = None
    try:
        from src.core.xray_manager import XrayManager

        probe_manager = XrayManager(binary_path=context.xray_manager.binary_path)
        success, error = probe_manager.start(config)
        if not success:
            logger.error(
                "Latency test: temp xray start failed for profile %s: %s", profile_id, error
            )
            return -1

        return probe_manager.test_delay_realistic(
            proxy_address=context.config.inbound_address,
            proxy_port=socks_port,
            timeout=timeout_ms,
            probes=probes,
        )
    except Exception as e:
        logger.exception("Latency test failed for profile %s: %s", profile_id, e)
        return -1
    finally:
        if probe_manager is not None:
            try:
                probe_manager.stop()
            except Exception:
                pass
