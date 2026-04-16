#!/bin/bash
# Install the sdwan-agent on a Debian/Ubuntu host.
# Must be run as root from the repo directory.
set -euo pipefail

usage() {
  cat <<EOF
Usage: $0 --controller-url URL --endpoint-ip IP [OPTIONS]

Required:
  --controller-url URL    Controller base URL (e.g. http://10.18.20.5:8005)
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

# wireguard-tools provides wg and wg-quick
apt-get install -y wireguard-tools

# Install uv if not present
if ! command -v uv &>/dev/null; then
  curl -Ls https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# Install the agent — downloads Python 3.12, creates isolated venv,
# places binary at /usr/local/bin/sdwan-agent
UV_TOOL_BIN_DIR=/usr/local/bin uv tool install --python 3.12 .

# Create config directory
mkdir -p /etc/sdwan-agent
chmod 700 /etc/sdwan-agent

# Write env file
cat > /etc/sdwan-agent/agent.env <<EOF
CONTROLLER_URL=${CONTROLLER_URL}
ENDPOINT_IP=${ENDPOINT_IP}
NODE_NAME=${NODE_NAME}
ENDPOINT_PORT=${ENDPOINT_PORT}
INTERFACE=${INTERFACE}
HEARTBEAT_INTERVAL=${HEARTBEAT_INTERVAL}
PEER_POLL_INTERVAL=${PEER_POLL_INTERVAL}
EOF
if [[ -n "$PREAUTH_TOKEN" ]]; then
  echo "PREAUTH_TOKEN=${PREAUTH_TOKEN}" >> /etc/sdwan-agent/agent.env
fi
chmod 600 /etc/sdwan-agent/agent.env

# Install and enable systemd service
cp sdwan-agent.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now sdwan-agent

echo ""
echo "Installed and started. Follow logs with:"
echo "  journalctl -fu sdwan-agent"
