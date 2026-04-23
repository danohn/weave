#!/bin/bash
# Weave controller entrypoint.
# Brings up the WireGuard route reflector interface, starts FRR BGP/BFD daemons,
# runs database migrations, then hands off to uvicorn.
set -euo pipefail

WG_INTERFACE="${WG_INTERFACE:-wg0}"
CONTROLLER_VPN_IP="${CONTROLLER_VPN_IP:-10.0.0.254}"
CONTROLLER_ENDPOINT_PORT="${CONTROLLER_ENDPOINT_PORT:-51820}"
TRANSPORT_OVERLAY_SUBNETS="${TRANSPORT_OVERLAY_SUBNETS:-internet=10.0.0.0/24,mpls=10.0.1.0/24,lte=10.0.2.0/24,other=10.0.3.0/24}"
WG_KEY_FILE="/app/data/rr-privatekey"
export WG_INTERFACE CONTROLLER_VPN_IP TRANSPORT_OVERLAY_SUBNETS

echo "=== Weave controller starting ==="

# ── WireGuard ────────────────────────────────────────────────────────────────
mkdir -p /app/data

if [[ ! -f "$WG_KEY_FILE" ]]; then
  wg genkey > "$WG_KEY_FILE"
  chmod 600 "$WG_KEY_FILE"
  echo "[wg] Generated new private key"
fi

wg pubkey < "$WG_KEY_FILE" > /app/data/rr-publickey
echo "[wg] Public key: $(cat /app/data/rr-publickey)"

if ! ip link show "$WG_INTERFACE" &>/dev/null; then
  ip link add "$WG_INTERFACE" type wireguard
  ip addr add "${CONTROLLER_VPN_IP}/24" dev "$WG_INTERFACE"
  echo "[wg] Created interface $WG_INTERFACE"
fi

python3 - <<'PY'
import ipaddress
import os
import subprocess

wg_interface = os.environ["WG_INTERFACE"]
controller_vpn_ip = os.environ["CONTROLLER_VPN_IP"]
subnets = os.environ["TRANSPORT_OVERLAY_SUBNETS"].split(",")

existing = subprocess.check_output(["ip", "-o", "-4", "addr", "show", "dev", wg_interface], text=True)
existing_addrs = {line.split()[3].split("/")[0] for line in existing.splitlines()}
primary_network = ipaddress.ip_interface(f"{controller_vpn_ip}/24").network

for item in subnets:
    if "=" not in item:
        continue
    _, subnet = item.split("=", 1)
    subnet = subnet.strip()
    network = ipaddress.ip_network(subnet, strict=False)
    controller_ip = str(list(network.hosts())[-1])
    if controller_ip == controller_vpn_ip or controller_ip in existing_addrs:
        pass
    else:
        subprocess.run(
            ["ip", "addr", "add", f"{controller_ip}/32", "dev", wg_interface],
            check=True,
        )
        print(f"[wg] Added overlay address {controller_ip}/32 to {wg_interface}")
PY

wg set "$WG_INTERFACE" \
  private-key "$WG_KEY_FILE" \
  listen-port "$CONTROLLER_ENDPOINT_PORT"
ip link set "$WG_INTERFACE" up
echo "[wg] Interface $WG_INTERFACE up — ${CONTROLLER_VPN_IP}/24 port ${CONTROLLER_ENDPOINT_PORT}"

python3 - <<'PY'
import ipaddress
import os
import subprocess

wg_interface = os.environ["WG_INTERFACE"]
controller_vpn_ip = os.environ["CONTROLLER_VPN_IP"]
subnets = os.environ["TRANSPORT_OVERLAY_SUBNETS"].split(",")
primary_network = ipaddress.ip_interface(f"{controller_vpn_ip}/24").network

for item in subnets:
    if "=" not in item:
        continue
    _, subnet = item.split("=", 1)
    subnet = subnet.strip()
    network = ipaddress.ip_network(subnet, strict=False)
    if network == primary_network:
        continue
    route_check = subprocess.run(
        ["ip", "route", "show", subnet, "dev", wg_interface],
        capture_output=True,
        text=True,
        check=True,
    )
    if not route_check.stdout.strip():
        subprocess.run(
            ["ip", "route", "add", subnet, "dev", wg_interface],
            check=True,
        )
        print(f"[wg] Added overlay route {subnet} dev {wg_interface}")
PY

# ── FRR ──────────────────────────────────────────────────────────────────────
# Enable required daemons
if [[ -f /etc/frr/daemons ]]; then
  sed -i 's/^zebra=no/zebra=yes/' /etc/frr/daemons
  sed -i 's/^bgpd=no/bgpd=yes/'  /etc/frr/daemons
  sed -i 's/^bfdd=no/bfdd=yes/'  /etc/frr/daemons
fi

# Integrated config — one frr.conf for all daemons
echo "service integrated-vtysh-config" > /etc/frr/vtysh.conf

mkdir -p /run/frr
chown frr:frr /run/frr
# Allow root (uvicorn process) to use vtysh — its socket is group-restricted to frrvty
usermod -aG frrvty root 2>/dev/null || true

# Write base route reflector config.
# Neighbors are added/removed dynamically via vtysh as nodes activate/revoke —
# so the base config only contains the peer-group definition, no neighbor lines.
cat > /etc/frr/frr.conf <<FRREOF
frr defaults traditional
hostname weave-rr
log syslog informational
!
bfd
!
router bgp 65000
 bgp router-id ${CONTROLLER_VPN_IP}
 no bgp default ipv4-unicast
 bgp cluster-id ${CONTROLLER_VPN_IP}
 !
 neighbor NODES peer-group
 neighbor NODES remote-as 65000
 neighbor NODES update-source ${WG_INTERFACE}
 neighbor NODES route-reflector-client
 neighbor NODES bfd
 neighbor NODES timers connect 10
 !
 address-family ipv4 unicast
  neighbor NODES activate
  neighbor NODES soft-reconfiguration inbound
 exit-address-family
!
FRREOF

# FRR drops to the frr user — config must be readable by it
chown frr:frr /etc/frr/frr.conf
chmod 640 /etc/frr/frr.conf

# Start bgpd and bfdd under watchfrr so they are automatically restarted
# if they crash. watchfrr itself runs in the background and survives bgpd
# restarts. Logs flow to PID 1 so they appear in docker logs.
/usr/lib/frr/watchfrr \
  --log-level informational \
  zebra bgpd bfdd \
  >> /proc/1/fd/1 2>> /proc/1/fd/2 &
echo "[frr] watchfrr started (pid $!) — supervising zebra + bgpd + bfdd"

# Give FRR time to open its vtysh socket before the API tries to add neighbors
sleep 3

# ── Database + API ───────────────────────────────────────────────────────────
alembic upgrade head

exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --proxy-headers \
  --forwarded-allow-ips='*' \
  --log-level info
