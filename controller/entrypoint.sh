#!/bin/bash
# Weave controller entrypoint.
# Brings up the WireGuard route reflector interface, starts FRR BGP/BFD daemons,
# runs database migrations, then hands off to uvicorn.
set -euo pipefail

WG_INTERFACE="${WG_INTERFACE:-wg0}"
CONTROLLER_VPN_IP="${CONTROLLER_VPN_IP:-10.0.0.254}"
CONTROLLER_ENDPOINT_PORT="${CONTROLLER_ENDPOINT_PORT:-51820}"
WG_KEY_FILE="/app/data/rr-privatekey"

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

wg set "$WG_INTERFACE" \
  private-key "$WG_KEY_FILE" \
  listen-port "$CONTROLLER_ENDPOINT_PORT"
ip link set "$WG_INTERFACE" up
echo "[wg] Interface $WG_INTERFACE up — ${CONTROLLER_VPN_IP}/24 port ${CONTROLLER_ENDPOINT_PORT}"

# ── FRR ──────────────────────────────────────────────────────────────────────
# Enable required daemons
if [[ -f /etc/frr/daemons ]]; then
  sed -i 's/^bgpd=no/bgpd=yes/' /etc/frr/daemons
  sed -i 's/^bfdd=no/bfdd=yes/'  /etc/frr/daemons
fi

# Integrated config — one frr.conf for all daemons
echo "service integrated-vtysh-config" > /etc/frr/vtysh.conf

mkdir -p /run/frr
chown frr:frr /run/frr

# Write base route reflector config.
# Neighbors are added/removed dynamically via vtysh as nodes activate/revoke —
# so the base config only contains the peer-group definition, no neighbor lines.
cat > /etc/frr/frr.conf <<FRREOF
frr version 9.1
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

# Start daemons in the background without daemonizing (--daemon forks and can
# misbehave in Docker without a proper init). Run in background subshells so
# errors are visible in docker logs. Sockets go to /run/frr/ per FRR build config.
if /usr/lib/frr/bgpd \
  --config_file /etc/frr/frr.conf \
  --pid_file /run/frr/bgpd.pid \
  >> /proc/1/fd/1 2>> /proc/1/fd/2 &
then
  echo "[frr] bgpd started (pid $!)"
else
  echo "[frr] bgpd failed to start (non-fatal)"
fi

if /usr/lib/frr/bfdd \
  --config_file /etc/frr/frr.conf \
  --pid_file /run/frr/bfdd.pid \
  >> /proc/1/fd/1 2>> /proc/1/fd/2 &
then
  echo "[frr] bfdd started (pid $!)"
else
  echo "[frr] bfdd failed to start (non-fatal)"
fi

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
