#!/bin/bash
# Install the Weave agent on a Debian/Ubuntu host.
# Designed to be run directly via curl — no local repo checkout required:
#
#   curl -fsSL https://raw.githubusercontent.com/danohn/weave/refs/heads/main/agent/install.sh \
#     | bash -s -- --controller-url URL [OPTIONS]
#
set -euo pipefail

# ── Logging ─────────────────────────────────────────────────────────────────
LOG_FILE="/tmp/weave-install.log"
: > "$LOG_FILE"   # truncate

CURRENT_STEP="init"

log()  { echo "$*" | tee -a "$LOG_FILE"; }
step() { CURRENT_STEP="$*"; log ""; log "  → $*"; }
info() { log "    $*"; }
err()  {
  echo ""
  echo "  ✗ Installation failed. Details:"
  echo "      $LOG_FILE"
  echo ""
  tail -20 "$LOG_FILE" | sed 's/^/    /'
  echo ""
  echo "WEAVE_INSTALL=failed step=\"${CURRENT_STEP}\" log=${LOG_FILE}"
  exit 1
}
trap err ERR

# ── Usage ────────────────────────────────────────────────────────────────────
usage() {
  cat <<EOF
Usage: $0 --controller-url URL [OPTIONS]

Required:
  --controller-url URL    Controller base URL (e.g. https://weave.example.com)

Optional:
  --node-name NAME        Node name (default: hostname)
  --preauth-token TOKEN   Pre-auth token for automatic activation
  --endpoint-port PORT    WireGuard listen port (default: 51820)
  --interface IFACE       WireGuard interface name (default: wg0)
  --heartbeat-interval N  Heartbeat interval in seconds (default: 30)
  --peer-poll-interval N  Peer poll interval in seconds (default: 60)
EOF
  exit 1
}

if [ "$(id -u)" -ne 0 ]; then
  echo "Error: run as root" >&2
  exit 1
fi

# ── Argument parsing ──────────────────────────────────────────────────────────
CONTROLLER_URL=""
NODE_NAME="$(hostname)"
PREAUTH_TOKEN=""
ENDPOINT_PORT="51820"
INTERFACE="wg0"
HEARTBEAT_INTERVAL="30"
PEER_POLL_INTERVAL="60"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --controller-url)     CONTROLLER_URL="$2";     shift 2 ;;
    --node-name)          NODE_NAME="$2";           shift 2 ;;
    --preauth-token)      PREAUTH_TOKEN="$2";       shift 2 ;;
    --endpoint-port)      ENDPOINT_PORT="$2";       shift 2 ;;
    --interface)          INTERFACE="$2";           shift 2 ;;
    --heartbeat-interval) HEARTBEAT_INTERVAL="$2"; shift 2 ;;
    --peer-poll-interval) PEER_POLL_INTERVAL="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

if [[ -z "$CONTROLLER_URL" ]]; then
  echo "Error: --controller-url is required"
  usage
fi

# ── Idempotency check ────────────────────────────────────────────────────────
if [[ -f "/etc/weave/state.json" ]]; then
  echo ""
  echo "  ⚠ Warning: /etc/weave/state.json already exists."
  echo "    This node has previously registered with a controller."
  echo "    Re-running will overwrite agent.env and restart the service,"
  echo "    but state.json (node ID and VPN IP) will be preserved."
  echo ""
  echo "    To force a clean re-registration, remove it first:"
  echo "      rm /etc/weave/state.json"
  echo ""
  read -r -p "    Continue anyway? [y/N] " confirm
  if [[ "$confirm" != [yY] ]]; then
    echo "Aborted."
    exit 0
  fi
fi

# ── Install ───────────────────────────────────────────────────────────────────
log ""
log "Weave Agent Installer"
log "────────────────────────────────────────"
info "Node:       $NODE_NAME"
info "Controller: $CONTROLLER_URL"
info "Interface:  $INTERFACE  (port $ENDPOINT_PORT)"
log ""

step "Installing system dependencies (wireguard-tools, git)..."
apt-get update -y        >> "$LOG_FILE" 2>&1
apt-get install -y wireguard-tools git >> "$LOG_FILE" 2>&1

export PATH="$HOME/.local/bin:$PATH"

step "Installing uv..."
if command -v uv &>/dev/null; then
  info "uv already installed — skipping"
else
  curl -fsSL https://astral.sh/uv/install.sh 2>>"$LOG_FILE" | sh >> "$LOG_FILE" 2>&1
fi

step "Installing weave agent from GitHub..."
UV_TOOL_BIN_DIR=/usr/local/bin uv tool install --python 3.12 \
  "git+https://github.com/danohn/weave#subdirectory=agent" >> "$LOG_FILE" 2>&1

step "Writing configuration..."
mkdir -p /etc/weave
chmod 700 /etc/weave

# Use printf to write each value — avoids shell expansion of special characters
# in URLs or tokens that would corrupt the file with an unquoted heredoc.
{
  printf 'CONTROLLER_URL=%s\n'      "$CONTROLLER_URL"
  printf 'NODE_NAME=%s\n'           "$NODE_NAME"
  printf 'ENDPOINT_PORT=%s\n'       "$ENDPOINT_PORT"
  printf 'INTERFACE=%s\n'           "$INTERFACE"
  printf 'HEARTBEAT_INTERVAL=%s\n'  "$HEARTBEAT_INTERVAL"
  printf 'PEER_POLL_INTERVAL=%s\n'  "$PEER_POLL_INTERVAL"
  [[ -n "$PREAUTH_TOKEN" ]] && printf 'PREAUTH_TOKEN=%s\n' "$PREAUTH_TOKEN"
} > /etc/weave/agent.env
chmod 600 /etc/weave/agent.env

step "Installing systemd service..."
cat > /etc/systemd/system/weave.service <<'UNIT'
[Unit]
Description=Weave Agent
Documentation=https://github.com/danohn/weave
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/weave/agent.env
ExecStart=/usr/local/bin/weave
Restart=on-failure
RestartSec=10
# Never give up restarting — network outages can be arbitrarily long
StartLimitIntervalSec=0
# Don't wait 90s for graceful shutdown; our SIGTERM handler is fast
TimeoutStopSec=15

StandardOutput=journal
StandardError=journal
SyslogIdentifier=weave

User=root
# Basic hardening (WireGuard requires root/CAP_NET_ADMIN so full sandboxing isn't possible)
# Note: ProtectHome cannot be used — uv stores the tool venv under /root/.local/
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload       >> "$LOG_FILE" 2>&1
systemctl enable --now weave  >> "$LOG_FILE" 2>&1

step "Waiting for agent to register with controller..."
STATE_FILE="/etc/weave/state.json"
NODE_ID=""
VPN_IP=""
for i in $(seq 1 30); do
  if [[ -f "$STATE_FILE" ]]; then
    NODE_ID=$(python3 -c "import json; d=json.load(open('$STATE_FILE')); print(d['node_id'])" 2>/dev/null || true)
    VPN_IP=$(python3  -c "import json; d=json.load(open('$STATE_FILE')); print(d['vpn_ip'])"  2>/dev/null || true)
    break
  fi
  sleep 1
done

log ""
log "────────────────────────────────────────"
if [[ -n "$NODE_ID" ]]; then
  log "  Weave agent installed and registered."
  log ""
  log "  Node ID:  $NODE_ID"
  log "  VPN IP:   $VPN_IP"
else
  log "  Weave agent installed and started."
  log "  (Node not yet registered — may need controller activation)"
fi
log ""
log "  Follow logs:  journalctl -fu weave"
log "  Full install log: $LOG_FILE"
log ""

# Machine-readable status line — easy to grep across cloud-init logs
if [[ -n "$NODE_ID" ]]; then
  echo "WEAVE_INSTALL=success node=${NODE_NAME} node_id=${NODE_ID} vpn_ip=${VPN_IP}"
else
  echo "WEAVE_INSTALL=success node=${NODE_NAME} node_id=pending vpn_ip=pending"
fi
