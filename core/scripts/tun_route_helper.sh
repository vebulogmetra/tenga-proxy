#!/bin/sh
set -eu

# Root helper for TUN route switching.
# Usage:
#   tun-route-helper apply <tun_name> <proxy_ip> <gateway|- > <dev> <metric|->
#   tun-route-helper restore <proxy_ip> <gateway|- > <dev> <metric|->
#   tun-route-helper dns <tun_name>
#   tun-route-helper firewall-apply <full|ipv6_only> <tun_name> <vpn_if|-> <vpn_addrs|-> <open|closed>
#   tun-route-helper firewall-remove
#   tun-route-helper features

die() {
  echo "tun-route-helper: $*" >&2
  exit 1
}

NL='
'

# grep проверяет каждую строку отдельно, поэтому перевод строки отсекается
# заранее: со второй строкой аргумента в команды попал бы чужой текст.
matches() {
  case "$2" in *"$NL"*) return 1 ;; esac
  printf '%s\n' "$2" | grep -Eq "$1"
}

is_ipv4() {
  matches '^((25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\.){3}(25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])$' "$1"
}

is_ifname() {
  matches '^[a-zA-Z0-9_.:-]{1,32}$' "$1"
}

is_metric() {
  matches '^[0-9]{1,10}$' "$1"
}

# Только шестнадцатеричные цифры и двоеточия: строка не вырвется из множества nft.
is_ipv6() {
  case "$1" in *:*) ;; *) return 1 ;; esac
  matches '^[0-9a-fA-F:]{2,39}$' "$1"
}

[ "$(id -u)" -eq 0 ] || die "must be run as root"
[ $# -ge 1 ] || die "missing action"

action="$1"
shift

case "$action" in
  apply)
    [ $# -eq 5 ] || die "apply requires 5 args"
    tun_name="$1"
    proxy_ip="$2"
    gateway="$3"
    dev="$4"
    metric="$5"

    is_ifname "$tun_name" || die "invalid tun_name"
    is_ipv4 "$proxy_ip" || die "invalid proxy_ip"
    [ "$gateway" = "-" ] || is_ipv4 "$gateway" || die "invalid gateway"
    is_ifname "$dev" || die "invalid dev"
    [ "$metric" = "-" ] || is_metric "$metric" || die "invalid metric"

    if [ "$gateway" = "-" ]; then
      ip route replace "$proxy_ip/32" dev "$dev"
    else
      ip route replace "$proxy_ip/32" via "$gateway" dev "$dev"
    fi
    ip route replace default dev "$tun_name"
    ;;

  restore)
    [ $# -eq 4 ] || die "restore requires 4 args"
    proxy_ip="$1"
    gateway="$2"
    dev="$3"
    metric="$4"

    is_ipv4 "$proxy_ip" || die "invalid proxy_ip"
    [ "$gateway" = "-" ] || is_ipv4 "$gateway" || die "invalid gateway"
    is_ifname "$dev" || die "invalid dev"
    [ "$metric" = "-" ] || is_metric "$metric" || die "invalid metric"

    if [ "$gateway" = "-" ]; then
      ip route replace default dev "$dev"
    else
      if [ "$metric" = "-" ]; then
        ip route replace default via "$gateway" dev "$dev"
      else
        ip route replace default via "$gateway" dev "$dev" metric "$metric"
      fi
    fi

    ip route del "$proxy_ip/32" >/dev/null 2>&1 || true
    ;;

  dns)
    # Фиксированный сервер: помощник выполняется от root без пароля.
    [ $# -eq 1 ] || die "dns requires 1 arg"
    tun_name="$1"
    is_ifname "$tun_name" || die "invalid tun_name"
    case "$tun_name" in -*) die "invalid tun_name" ;; esac
    command -v resolvectl >/dev/null 2>&1 || die "resolvectl not found"
    resolvectl dns "$tun_name" 1.1.1.1
    resolvectl domain "$tun_name" "~."
    ;;

  features)
    # Что умеет этот помощник: приложение из исходников может работать с
    # помощником установленного пакета, который новых действий не знает.
    [ $# -eq 0 ] || die "features takes no args"
    echo "apply restore dns firewall"
    ;;

  firewall-apply)
    # Правила собирает сам помощник: от root без пароля нельзя принимать готовый
    # текст. Скрипт для `nft -f` один: создать-если-нет, очистить, наполнить —
    # переустановка атомарна, и щели с policy accept нет.
    [ $# -eq 5 ] || die "firewall-apply requires 5 args"
    level="$1"
    tun_name="$2"
    vpn_if="$3"
    vpn_addrs="$4"
    dns="$5"

    case "$level" in full | ipv6_only) ;; *) die "invalid level" ;; esac
    is_ifname "$tun_name" || die "invalid tun_name"
    [ "$vpn_if" = "-" ] || is_ifname "$vpn_if" || die "invalid vpn_if"
    case "$dns" in open | closed) ;; *) die "invalid dns state" ;; esac

    v4=""
    v6=""
    if [ "$vpn_addrs" != "-" ]; then
      # Адрес с пробелом или переводом строки разбиваться не должен: список
      # делится только по запятым, а каждая часть проверяется целиком.
      rest="$vpn_addrs,"
      while [ -n "$rest" ]; do
        addr="${rest%%,*}"
        rest="${rest#*,}"
        if is_ipv4 "$addr"; then
          v4="$v4${v4:+, }$addr"
        elif is_ipv6 "$addr"; then
          v6="$v6${v6:+, }$addr"
        else
          die "invalid vpn address"
        fi
      done
    fi

    command -v nft >/dev/null 2>&1 || die "nft not found"
    {
      # Комментарий ставится при создании: у существующей таблицы nft его не меняет.
      echo 'table inet veblock { comment "Veblock: traffic block on connection loss. Remove: nft delete table inet veblock"; }'
      echo 'flush table inet veblock'
      echo 'table inet veblock {'
      for chain in output forward; do
        echo "  chain $chain {"
        echo "    type filter hook $chain priority 0; policy accept;"
        if [ "$chain" = output ]; then
          echo '    oif "lo" accept'
          # Сокеты xray. В forward метки нет: при переходе через veth она стирается.
          echo '    meta mark 0x7e6a accept'
        fi
        echo "    oifname \"$tun_name\" accept"
        [ "$vpn_if" = "-" ] || echo "    oifname \"$vpn_if\" accept"
        [ -z "$v4" ] || echo "    ip daddr { $v4 } accept"
        [ -z "$v6" ] || echo "    ip6 daddr { $v6 } accept"
        # До локальных сетей: иначе запрос на роутер пройдёт по их разрешению.
        if [ "$level" = full ] && [ "$dns" = closed ]; then
          echo '    tcp dport 53 reject with tcp reset'
          echo '    udp dport 53 reject with icmpx type admin-prohibited'
        fi
        # DHCP: DISCOVER идёт мимо netfilter, а продление — unicast'ом через output.
        [ "$chain" != output ] || echo '    udp sport 68 udp dport 67 accept'
        echo '    icmpv6 type { nd-router-solicit, nd-neighbor-solicit, nd-neighbor-advert } accept'
        echo '    ip daddr { 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16, 224.0.0.0/4, 255.255.255.255 } accept'
        echo '    ip6 daddr { ::1/128, fc00::/7, fe80::/10, ff00::/8 } accept'
        # TCP отказывается сбросом: ICMP-ошибку на первый SYN по IPv6 ядро считает
        # мягкой, и connect() ждал бы повтора SYN, около секунды на каждый адрес.
        if [ "$level" = full ]; then
          echo '    meta l4proto tcp reject with tcp reset'
          echo '    reject with icmpx type admin-prohibited'
        else
          echo '    meta nfproto ipv6 meta l4proto tcp reject with tcp reset'
          echo '    meta nfproto ipv6 reject with icmpx type admin-prohibited'
        fi
        echo '  }'
      done
      echo '}'
    } | nft -f -
    ;;

  firewall-remove)
    [ $# -eq 0 ] || die "firewall-remove takes no args"
    command -v nft >/dev/null 2>&1 || exit 0
    nft delete table inet veblock 2>/dev/null || true
    ;;

  *)
    die "unknown action: $action"
    ;;
esac
