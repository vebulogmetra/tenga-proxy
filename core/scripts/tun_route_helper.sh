#!/bin/sh
set -eu

# Root helper for TUN route switching.
# Usage:
#   tun-route-helper apply <tun_name> <proxy_ip> <gateway|- > <dev> <metric|->
#   tun-route-helper restore <proxy_ip> <gateway|- > <dev> <metric|->

die() {
  echo "tun-route-helper: $*" >&2
  exit 1
}

is_ipv4() {
  echo "$1" | awk -F. '
    NF != 4 { exit 1 }
    {
      for (i = 1; i <= 4; i++) {
        if ($i !~ /^[0-9]+$/) exit 1
        if ($i < 0 || $i > 255) exit 1
      }
    }
    END { exit 0 }
  '
}

is_ifname() {
  echo "$1" | grep -Eq '^[a-zA-Z0-9_.:-]{1,32}$'
}

is_metric() {
  echo "$1" | grep -Eq '^[0-9]{1,10}$'
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

  *)
    die "unknown action: $action"
    ;;
esac
