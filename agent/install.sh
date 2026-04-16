#!/bin/bash
# Install the Weave agent on a Debian/Ubuntu host.
# Designed to be run directly via curl — no local repo checkout required:
#
#   curl -fsSL https://raw.githubusercontent.com/danohn/weave/refs/heads/main/agent/install.sh \
#     | bash -s -- --controller-url URL --endpoint-ip IP [OPTIONS]
#
set -euo pipefail

usage() {
  cat <<EOF
Usage: $0 --controller-url URL --endpoint-ip IP [OPTIONS]

Required:
  --controller-url URL    Controller base URL (e.g. http://192.168.1.1:8005)
  --endpoint-ip IP        This node's public IP reported to the controller

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
  echo "Run as root" >&2
  exit 1
fi

# Defaults
CONTROLLER_URL=""
ENDPOINT_IP=""
NODE_NAME="$(hostname)"
PREAUTH_TOKEN=""
ENDPOINT_PORT="51820"
INTERFACE="wg0"
HEARTBEAT_INTERVAL="30"
PEER_POLL_INTERVAL="60"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --controller-url)   CONTROLLER_URL="$2";   shift 2 ;;
    --endpoint-ip)      ENDPOINT_IP="$2";      shift 2 ;;
    --node-name)        NODE_NAME="$2";        shift 2 ;;
    --preauth-token)    PREAUTH_TOKEN="$2";    shift 2 ;;
    --endpoint-port)    ENDPOINT_PORT="$2";    shift 2 ;;
    --interface)        INTERFACE="$2";        shift 2 ;;
    --heartbeat-interval) HEARTBEAT_INTERVAL="$2"; shift 2 ;;
    --peer-poll-interval) PEER_POLL_INTERVAL="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

if [[ -z "$CONTROLLER_URL" || -z "$ENDPOINT_IP" ]]; then
  echo "Error: --controller-url and --endpoint-ip are required"
  usage
fi

# wireguard-tools provides the wg binary (used for key generation)
# git is required by uv to install the agent directly from GitHub
apt-get update -y
apt-get install -y wireguard-tools git

# Install uv if not present
if ! command -v uv &>/dev/null; then
  curl -fsSL https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# Install the agent directly from GitHub — no local checkout required.
# uv downloads Python 3.12, builds an isolated venv, and places the
# binary at /usr/local/bin/weave.
UV_TOOL_BIN_DIR=/usr/local/bin uv tool install --python 3.12 \
  "git+https://github.com/danohn/weave#subdirectory=agent"

# Create config directory
mkdir -p /etc/weave
chmod 700 /etc/weave

# Write env file
cat > /etc/weave/agent.env <<EOF
CONTROLLER_URL=${CONTROLLER_URL}
ENDPOINT_IP=${ENDPOINT_IP}
NODE_NAME=${NODE_NAME}
ENDPOINT_PORT=${ENDPOINT_PORT}
INTERFACE=${INTERFACE}
HEARTBEAT_INTERVAL=${HEARTBEAT_INTERVAL}
PEER_POLL_INTERVAL=${PEER_POLL_INTERVAL}
EOF
if [[ -n "$PREAUTH_TOKEN" ]]; then
  echo "PREAUTH_TOKEN=${PREAUTH_TOKEN}" >> /etc/weave/agent.env
fi
chmod 600 /etc/weave/agent.env

# Write the systemd service unit inline — no local file needed
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
ExecStartPre=/bin/sleep 2

StandardOutput=journal
StandardError=journal
SyslogIdentifier=weave

User=root

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now weave

echo ""
echo "Installed and started. Follow logs with:"
echo "  journalctl -fu weave"
