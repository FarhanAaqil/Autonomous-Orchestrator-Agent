#!/bin/sh
set -eu
# Fail startup if the kernel cannot enforce these rules. No permissive fallback.
iptables -P OUTPUT DROP
iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
if [ "$SANDBOX_ROLE" = "browser" ]; then
    iptables -A OUTPUT -d 127.0.0.1 -p tcp --dport 8888 -j ACCEPT
    iptables -A OUTPUT -d 172.30.90.2 -p tcp --dport 8889 -j ACCEPT
else
    # Docker's embedded resolver is the only permitted DNS destination.
    iptables -A OUTPUT -d 127.0.0.11 -p udp -j ACCEPT
    iptables -A OUTPUT -d 127.0.0.11 -p tcp -j ACCEPT
    for range in 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 192.0.0.0/24 198.18.0.0/15 224.0.0.0/4 240.0.0.0/4; do
        iptables -A OUTPUT -d "$range" -j REJECT
    done
    iptables -A OUTPUT -p tcp -m multiport --dports 80,443 -j ACCEPT
fi
ip6tables -P OUTPUT DROP
# Neither the Python service nor Chromium retains firewall or root capabilities.
exec setpriv --reuid=1001 --regid=1001 --clear-groups --bounding-set=-all --inh-caps=-all --ambient-caps=-all "$@"
