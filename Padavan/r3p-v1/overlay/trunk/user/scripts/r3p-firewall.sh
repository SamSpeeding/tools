#!/bin/sh

chain=R3P_MIHOMO
mark=0x400000/0x400000
table=166
priority=10266
run=/tmp/r3p

remove_family()
{
	"$1" -t mangle -D PREROUTING -i br0 -j "$chain" 2>/dev/null
	"$1" -t mangle -F "$chain" 2>/dev/null
	"$1" -t mangle -X "$chain" 2>/dev/null
	ip "$2" rule del pref "$priority" fwmark "$mark" lookup "$table" 2>/dev/null
	ip "$2" route flush table "$table" 2>/dev/null
}

add_family()
{
	ipt=$1
	family=$2
	range=$3
	loopback=$4
	port=$5
	shift 5

	"$ipt" -t mangle -N "$chain" || return 1
	"$ipt" -t mangle -A "$chain" -m addrtype --dst-type LOCAL -j RETURN || return 1

	for dst in "$@" $(ip "$family" route show dev br0 | awk '$1 ~ /^[0-9a-fA-F:.]+(\/[0-9]+)?$/ {print $1}'); do
		"$ipt" -t mangle -A "$chain" -d "$dst" -j RETURN || return 1
	done

	if [ -f "$run/proxy.bypass" ]; then
		while read -r rule_family direction address; do
			[ "$rule_family" = "$family" ] || continue
			"$ipt" -t mangle -A "$chain" "$direction" "$address" -j RETURN || return 1
		done < "$run/proxy.bypass"
	fi

	ip "$family" route replace local "$range" dev lo table "$table" || return 1
	ip "$family" rule add pref "$priority" fwmark "$mark" lookup "$table" || return 1
	for proto in tcp udp; do
		"$ipt" -t mangle -A "$chain" -p "$proto" -j TPROXY --on-ip "$loopback" --on-port "$port" --tproxy-mark "$mark" || return 1
	done
	"$ipt" -t mangle -A PREROUTING -i br0 -j "$chain"
}

remove_family iptables -4
remove_family ip6tables -6
rm -f "$run/proxy.ready"

[ -f "$run/proxy.active" ] || exit 0
[ "$(nvram get wan_route_x)" != IP_Bridged ] || exit 1
[ -d /sys/module/hw_nat ] && exit 1
[ -d /sys/module/fast_classifier ] && exit 1

if add_family iptables -4 0.0.0.0/0 127.0.0.1 17891 \
		0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 240.0.0.0/4 &&
	add_family ip6tables -6 ::/0 ::1 17892 ::/128 ::1/128 fc00::/7 fe80::/10 ff00::/8; then
	touch "$run/proxy.ready"
	exit $?
fi

remove_family iptables -4
remove_family ip6tables -6
exit 1
