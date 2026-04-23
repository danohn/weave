#!/bin/bash
# Install the Weave agent on a Debian/Ubuntu host.
# Designed to be run directly via curl — no local repo checkout required:
#
#   REF=v0.2.0
#   curl -fsSL "https://raw.githubusercontent.com/danohn/weave/${REF}/agent/install.sh" \
#     | bash -s -- --controller-url URL [OPTIONS]
#
set -euo pipefail

# ── Logging ─────────────────────────────────────────────────────────────────
LOG_FILE="/tmp/weave-install.log"
: > "$LOG_FILE"

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
  --claim-token TOKEN     Claim token for automatic activation
  --preauth-token TOKEN   Deprecated alias for --claim-token
  --endpoint-port PORT    WireGuard listen port (default: 51820)
  --interface IFACE       Overlay interface name for legacy single transport
  --heartbeat-interval N  Heartbeat interval in seconds (default: 30)
  --peer-poll-interval N  Peer poll interval in seconds (default: 60)
  --transport SPEC        Transport mapping: kind:underlay_if[:port]
  --repo-ref REF          Git ref for the agent package and service file (default: main)
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
CLAIM_TOKEN=""
ENDPOINT_PORT="51820"
INTERFACE="weave-internet"
HEARTBEAT_INTERVAL="30"
PEER_POLL_INTERVAL="60"
REPO_REF="${WEAVE_REPO_REF:-main}"
declare -a TRANSPORT_SPECS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --controller-url)     CONTROLLER_URL="$2";     shift 2 ;;
    --node-name)          NODE_NAME="$2";           shift 2 ;;
    --claim-token)        CLAIM_TOKEN="$2";         shift 2 ;;
    --preauth-token)      CLAIM_TOKEN="$2";         shift 2 ;;
    --endpoint-port)      ENDPOINT_PORT="$2";       shift 2 ;;
    --interface)          INTERFACE="$2";           shift 2 ;;
    --heartbeat-interval) HEARTBEAT_INTERVAL="$2"; shift 2 ;;
    --peer-poll-interval) PEER_POLL_INTERVAL="$2"; shift 2 ;;
    --transport)          TRANSPORT_SPECS+=("$2");  shift 2 ;;
    --repo-ref)           REPO_REF="$2";            shift 2 ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

if [[ -z "$CONTROLLER_URL" ]]; then
  echo "Error: --controller-url is required"
  usage
fi

detect_nics() {
  ip -o link show \
    | awk -F': ' '{print $2}' \
    | grep -Ev '^(lo|docker[0-9]*|veth.*|br-.*|wg.*|weave-.*)$' || true
}

first_ipv4_for_iface() {
  ip -4 -o addr show dev "$1" scope global | awk '{print $4}' | cut -d/ -f1 | head -n1
}

gateway_for_iface() {
  ip route show default dev "$1" | awk '/default/ {print $3}' | head -n1
}

build_transport_json() {
  python3 - "$@" <<'PY'
import json, sys
items = []
for spec in sys.argv[1:]:
    kind, iface, port, source_ip, gateway = (spec.split("|") + ["", "", ""])[:5]
    items.append({
        "name": "wan1" if kind == "internet" else f"{kind}1",
        "kind": kind,
        "interface": f"weave-{kind}",
        "endpoint_port": int(port),
        "private_key_file": f"/etc/weave/privatekey-{kind}",
        "bind_interface": iface or None,
        "source_ip": source_ip or None,
        "gateway": gateway or None,
    })
print(json.dumps(items, separators=(",", ":")))
PY
}

prompt_transport_for_kind() {
  local kind="$1"
  local default_port="$2"
  local iface=""
  local port=""

  read -r -p "    Interface for ${kind} transport (blank to skip): " iface
  if [[ -z "${iface}" ]]; then
    return 1
  fi
  read -r -p "    UDP listen port for ${kind} transport [${default_port}]: " port
  port="${port:-$default_port}"
  TRANSPORT_SPECS+=("${kind}|${iface}|${port}|$(first_ipv4_for_iface "$iface")|$(gateway_for_iface "$iface")")
  return 0
}

step "Detecting underlay interfaces..."
mapfile -t DETECTED_NICS < <(detect_nics)
if [[ ${#TRANSPORT_SPECS[@]} -eq 0 ]]; then
  if [[ ${#DETECTED_NICS[@]} -eq 1 ]]; then
    AUTO_IFACE="${DETECTED_NICS[0]}"
    AUTO_SOURCE_IP="$(first_ipv4_for_iface "$AUTO_IFACE")"
    AUTO_GATEWAY="$(gateway_for_iface "$AUTO_IFACE")"
    TRANSPORT_SPECS+=("internet|${AUTO_IFACE}|${ENDPOINT_PORT}|${AUTO_SOURCE_IP}|${AUTO_GATEWAY}")
    info "Detected single underlay interface ${AUTO_IFACE}; binding internet transport automatically"
  elif [[ ${#DETECTED_NICS[@]} -gt 1 ]]; then
    log ""
    log "Detected multiple underlay interfaces:"
    for nic in "${DETECTED_NICS[@]}"; do
      info "${nic}  ip=$(first_ipv4_for_iface "$nic")  gw=$(gateway_for_iface "$nic")"
    done
    log ""
    log "Multiple NICs require explicit transport mappings."
    log "Use repeated --transport kind:iface[:port] flags for automation,"
    log "or answer the prompts below."
    log ""
    if ! prompt_transport_for_kind "internet" "$ENDPOINT_PORT"; then
      echo "Error: internet transport is required when multiple NICs are present"
      echo "Hint: pass --transport internet:<iface>[:port]"
      exit 1
    fi
    prompt_transport_for_kind "mpls" "51821" || true
    prompt_transport_for_kind "lte" "51822" || true
  else
    info "No non-loopback underlay interfaces detected; leaving transport binding unset"
    TRANSPORT_SPECS+=("internet||${ENDPOINT_PORT}||")
  fi
fi

for spec in "${TRANSPORT_SPECS[@]}"; do
  IFS=':' read -r maybe_kind maybe_iface maybe_port <<< "$spec"
  if [[ "$spec" == *"|"* ]]; then
    continue
  fi
  if [[ -z "${maybe_kind:-}" || -z "${maybe_iface:-}" ]]; then
    echo "Error: invalid --transport value '$spec'"
    echo "Expected format: kind:underlay_if[:port]"
    exit 1
  fi
done

if [[ ${#TRANSPORT_SPECS[@]} -gt 0 ]]; then
  NORMALIZED_SPECS=()
  for spec in "${TRANSPORT_SPECS[@]}"; do
    if [[ "$spec" == *"|"* ]]; then
      NORMALIZED_SPECS+=("$spec")
      continue
    fi
    IFS=':' read -r kind iface port <<< "$spec"
    case "$kind" in
      internet|mpls|lte|other) ;;
      *)
        echo "Error: unsupported transport kind '$kind'"
        exit 1
        ;;
    esac
    if ! printf '%s\n' "${DETECTED_NICS[@]}" | grep -qx "$iface"; then
      echo "Error: interface '$iface' not detected on this host"
      exit 1
    fi
    if [[ -z "${port:-}" ]]; then
      case "$kind" in
        internet) port="$ENDPOINT_PORT" ;;
        mpls) port="51821" ;;
        lte) port="51822" ;;
        other) port="51823" ;;
      esac
    fi
    NORMALIZED_SPECS+=("${kind}|${iface}|${port}|$(first_ipv4_for_iface "$iface")|$(gateway_for_iface "$iface")")
  done
  TRANSPORT_SPECS=("${NORMALIZED_SPECS[@]}")
fi

TRANSPORTS_JSON="$(build_transport_json "${TRANSPORT_SPECS[@]}")"

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
info "Transports: $TRANSPORTS_JSON"
info "Repo ref:   $REPO_REF"
log ""

step "Installing system dependencies (wireguard-tools, frr, git)..."
apt-get update -y                              >> "$LOG_FILE" 2>&1
apt-get install -y wireguard-tools frr git     >> "$LOG_FILE" 2>&1

step "Enabling FRR daemons (bgpd, bfdd)..."
FRR_DAEMONS="/etc/frr/daemons"
if [[ -f "$FRR_DAEMONS" ]]; then
  sed -i 's/^bgpd=no/bgpd=yes/' "$FRR_DAEMONS"
  sed -i 's/^bfdd=no/bfdd=yes/' "$FRR_DAEMONS"
  # Integrated config — one frr.conf for all daemons
  echo "service integrated-vtysh-config" > /etc/frr/vtysh.conf
  info "bgpd and bfdd enabled"
else
  info "FRR daemons file not found — agent will configure at first run"
fi

export PATH="$HOME/.local/bin:$PATH"

step "Installing uv..."
if command -v uv &>/dev/null; then
  info "uv already installed — skipping"
else
  curl -fsSL https://astral.sh/uv/install.sh 2>>"$LOG_FILE" | sh >> "$LOG_FILE" 2>&1
fi

step "Installing weave agent from GitHub..."
UV_TOOL_BIN_DIR=/usr/local/bin uv tool install --python 3.12 \
  "git+https://github.com/danohn/weave@${REPO_REF}#subdirectory=agent" >> "$LOG_FILE" 2>&1

step "Writing configuration..."
mkdir -p /etc/weave
chmod 700 /etc/weave

{
  printf 'CONTROLLER_URL=%s\n'      "$CONTROLLER_URL"
  printf 'NODE_NAME=%s\n'           "$NODE_NAME"
  printf 'ENDPOINT_PORT=%s\n'       "$ENDPOINT_PORT"
  printf 'INTERFACE=%s\n'           "$INTERFACE"
  printf 'TRANSPORTS_JSON=%s\n'     "$TRANSPORTS_JSON"
  printf 'HEARTBEAT_INTERVAL=%s\n'  "$HEARTBEAT_INTERVAL"
  printf 'PEER_POLL_INTERVAL=%s\n'  "$PEER_POLL_INTERVAL"
  [[ -n "$CLAIM_TOKEN" ]] && printf 'CLAIM_TOKEN=%s\n' "$CLAIM_TOKEN"
} > /etc/weave/agent.env
chmod 600 /etc/weave/agent.env

step "Installing systemd service..."
SERVICE_URL="https://raw.githubusercontent.com/danohn/weave/${REPO_REF}/agent/weave.service"
curl -fsSL "$SERVICE_URL" -o /etc/systemd/system/weave.service >> "$LOG_FILE" 2>&1

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

if [[ -n "$NODE_ID" ]]; then
  echo "WEAVE_INSTALL=success node=${NODE_NAME} node_id=${NODE_ID} vpn_ip=${VPN_IP}"
else
  echo "WEAVE_INSTALL=success node=${NODE_NAME} node_id=pending vpn_ip=pending"
fi
