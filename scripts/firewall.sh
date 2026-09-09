#!/bin/bash
set -e
# Block classic abuse vectors at host level. Re-apply on boot.
# 1. jobs must use squid proxy; block direct SMTP + rate-limit SYN floods
iptables -C OUTPUT -p tcp --dport 25 -j DROP 2>/dev/null || iptables -A OUTPUT -p tcp --dport 25 -j DROP
iptables -C OUTPUT -p tcp --dport 465 -j DROP 2>/dev/null || iptables -A OUTPUT -p tcp --dport 465 -j DROP
iptables -C OUTPUT -p tcp --dport 587 -j DROP 2>/dev/null || iptables -A OUTPUT -p tcp --dport 587 -j DROP
# 2. job bridge -> LAN drop (adjust 192.168.1.0/24 to your LAN, tailscale 100.64.0.0/10 stays allowed)
iptables -C FORWARD -s 172.16.0.0/12 -d 192.168.0.0/16 -j DROP 2>/dev/null || iptables -A FORWARD -s 172.16.0.0/12 -d 192.168.0.0/16 -j DROP
iptables -C FORWARD -s 172.16.0.0/12 -d 10.0.0.0/8 -j DROP 2>/dev/null || iptables -A FORWARD -s 172.16.0.0/12 -d 10.0.0.0/8 -j DROP
echo "firewall applied. SMTP blocked, docker->LAN dropped."
