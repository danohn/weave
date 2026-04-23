#!/bin/bash
# Install the Weave agent on a Debian/Ubuntu host.
# Designed to be run directly via curl — no local repo checkout required:
#
#   REF=v0.2.2
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
warn() { log "    WARN: $*"; }
fail() { echo "Error: $*" >&2; exit 1; }
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
  --controller-url URL      Controller base URL (e.g. https://weave.example.com)

Optional:
  --node-name NAME          Node name (default: hostname)
  --claim-token TOKEN       Claim token for automatic activation
  --preauth-token TOKEN     Deprecated alias for --claim-token
  --endpoint-port PORT      WireGuard listen port for default internet transport (default: 51820)
  --interface IFACE         Overlay interface name for legacy single transport (default: weave-internet)
  --heartbeat-interval N    Heartbeat interval in seconds (default: 30)
  --peer-poll-interval N    Peer poll interval in seconds (default: 60)
  --transport SPEC          Transport mapping: kind:underlay_if[:port]
  --install-source SOURCE   Agent install source: pypi or github (default: pypi)
  --repo-ref REF            Git ref for GitHub installs only (default: main)
  --reuse-state             Reuse existing /etc/weave/state.json without prompting
  --fresh-register          Back up and remove existing state.json before install
  --non-interactive         Do not prompt; implies reuse-state when state exists
  --yes                     Alias for --non-interactive --reuse-state
  -h, --help                Show this help
EOF
  exit 1
}

if [ "$(id -u)" -ne 0 ]; then
  fail "run as root"
fi

# ── Defaults and argument parsing ───────────────────────────────────────────
CONTROLLER_URL=""
NODE_NAME="$(hostname)"
CLAIM_TOKEN=""
ENDPOINT_PORT="51820"
INTERFACE="weave-internet"
HEARTBEAT_INTERVAL="30"
PEER_POLL_INTERVAL="60"
INSTALL_SOURCE="${WEAVE_INSTALL_SOURCE:-pypi}"
REPO_REF="${WEAVE_REPO_REF:-main}"
NON_INTERACTIVE="false"
STATE_MODE="prompt"  # prompt | reuse | fresh
declare -a TRANSPORT_SPECS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --controller-url)     CONTROLLER_URL="$2";     shift 2 ;;
    --node-name)          NODE_NAME="$2";          shift 2 ;;
    --claim-token)        CLAIM_TOKEN="$2";        shift 2 ;;
    --preauth-token)      CLAIM_TOKEN="$2";        shift 2 ;;
    --endpoint-port)      ENDPOINT_PORT="$2";      shift 2 ;;
    --interface)          INTERFACE="$2";          shift 2 ;;
    --heartbeat-interval) HEARTBEAT_INTERVAL="$2"; shift 2 ;;
    --peer-poll-interval) PEER_POLL_INTERVAL="$2"; shift 2 ;;
    --transport)          TRANSPORT_SPECS+=("$2"); shift 2 ;;
    --install-source)     INSTALL_SOURCE="$2";     shift 2 ;;
    --repo-ref)           REPO_REF="$2";           shift 2 ;;
    --reuse-state)        STATE_MODE="reuse";      shift 1 ;;
    --fresh-register)     STATE_MODE="fresh";      shift 1 ;;
    --non-interactive)    NON_INTERACTIVE="true";  shift 1 ;;
    --yes)                NON_INTERACTIVE="true"; STATE_MODE="reuse"; shift 1 ;;
    -h|--help)            usage ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

if [[ -z "$CONTROLLER_URL" ]]; then
  echo "Error: --controller-url is required"
  usage
fi

CONTROLLER_URL="${CONTROLLER_URL%/}"
STATE_FILE="/etc/weave/state.json"
FRR_DAEMONS="/etc/frr/daemons"
SERVICE_PATH="/etc/systemd/system/weave.service"
INSTALL_MODE_LABEL=""

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

have_tty() {
  [[ -t 0 && -t 1 ]]
}

ensure_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || fail "required command '$cmd' is not available"
}

is_supported_transport_kind() {
  case "$1" in
    internet|mpls|lte|other) return 0 ;;
    *) return 1 ;;
  esac
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

render_transport_summary() {
  python3 - "$@" <<'PY'
import sys

for spec in sys.argv[1:]:
    kind, iface, port, source_ip, gateway = (spec.split("|") + ["", "", ""])[:5]
    parts = [
        f"{kind}",
        f"bind={iface or 'auto'}",
        f"src={source_ip or 'auto'}",
        f"gw={gateway or 'auto'}",
        f"port={port}",
        f"overlay=weave-{kind}",
    ]
    print(" | ".join(parts))
PY
}

prompt_transport_for_kind() {
  local kind="$1"
  local default_port="$2"
  local iface=""
  local port=""

  if [[ "$NON_INTERACTIVE" == "true" ]] || ! have_tty; then
    return 1
  fi

  read -r -p "    Interface for ${kind} transport (blank to skip): " iface
  if [[ -z "${iface}" ]]; then
    return 1
  fi
  read -r -p "    UDP listen port for ${kind} transport [${default_port}]: " port
  port="${port:-$default_port}"
  TRANSPORT_SPECS+=("${kind}|${iface}|${port}|$(first_ipv4_for_iface "$iface")|$(gateway_for_iface "$iface")")
  return 0
}

write_service_file() {
  cat > "$SERVICE_PATH" <<'EOF'
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
StartLimitIntervalSec=0
TimeoutStopSec=15
StandardOutput=journal
StandardError=journal
SyslogIdentifier=weave
User=root
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF
}

parse_state_field() {
  local field="$1"
  python3 - "$STATE_FILE" "$field" <<'PY'
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
field = sys.argv[2]
data = json.loads(path.read_text())
print(data.get(field, ""))
PY
}

handle_existing_state() {
  if [[ ! -f "$STATE_FILE" ]]; then
    return
  fi

  case "$STATE_MODE" in
    fresh)
      local backup="${STATE_FILE}.bak.$(date +%Y%m%d%H%M%S)"
      cp "$STATE_FILE" "$backup"
      rm -f "$STATE_FILE"
      info "Backed up existing state to $backup and forced a fresh registration"
      ;;
    reuse)
      info "Reusing existing state from $STATE_FILE"
      ;;
    prompt)
      if [[ "$NON_INTERACTIVE" == "true" || ! -t 0 ]]; then
        info "Existing state found; non-interactive mode defaults to reuse"
        return
      fi
      echo ""
      echo "  ⚠ Warning: $STATE_FILE already exists."
      echo "    This node has previously registered with a controller."
      echo "    Re-running will overwrite agent.env and restart the service,"
      echo "    but state.json (node ID and VPN IP) will be preserved."
      echo ""
      echo "    To force a clean re-registration, rerun with:"
      echo "      --fresh-register"
      echo ""
      read -r -p "    Reuse existing state and continue? [Y/n] " confirm
      confirm="${confirm:-Y}"
      if [[ "$confirm" != [yY] ]]; then
        echo "Aborted."
        exit 0
      fi
      ;;
    *)
      fail "unsupported state mode '$STATE_MODE'"
      ;;
  esac
}

normalize_transport_specs() {
  local -a detected_nics=("$@")
  local -a normalized=()
  declare -A seen_kinds=()
  declare -A seen_ifaces=()

  if [[ ${#TRANSPORT_SPECS[@]} -eq 0 ]]; then
    if [[ ${#detected_nics[@]} -eq 1 ]]; then
      local auto_iface="${detected_nics[0]}"
      local auto_source_ip
      local auto_gateway
      auto_source_ip="$(first_ipv4_for_iface "$auto_iface")"
      auto_gateway="$(gateway_for_iface "$auto_iface")"
      [[ -n "$auto_source_ip" ]] || fail "detected interface '$auto_iface' has no global IPv4 address"
      TRANSPORT_SPECS+=("internet|${auto_iface}|${ENDPOINT_PORT}|${auto_source_ip}|${auto_gateway}")
      info "Detected single underlay interface ${auto_iface}; binding internet transport automatically"
    elif [[ ${#detected_nics[@]} -gt 1 ]]; then
      log ""
      log "Detected multiple underlay interfaces:"
      for nic in "${detected_nics[@]}"; do
        info "${nic}  ip=$(first_ipv4_for_iface "$nic")  gw=$(gateway_for_iface "$nic")"
      done
      log ""
      log "Multiple NICs require explicit transport mappings."
      log "Use repeated --transport kind:iface[:port] flags for automation."
      if [[ "$NON_INTERACTIVE" == "true" ]]; then
        fail "multiple interfaces detected; pass explicit --transport mappings"
      fi
      log "Interactive prompts will collect them now."
      log ""
      if ! prompt_transport_for_kind "internet" "$ENDPOINT_PORT"; then
        fail "internet transport is required when multiple NICs are present"
      fi
      prompt_transport_for_kind "mpls" "51821" || true
      prompt_transport_for_kind "lte" "51822" || true
    else
      fail "no non-loopback underlay interfaces detected"
    fi
  fi

  for spec in "${TRANSPORT_SPECS[@]}"; do
    local kind=""
    local iface=""
    local port=""
    local source_ip=""
    local gateway=""

    if [[ "$spec" == *"|"* ]]; then
      IFS='|' read -r kind iface port source_ip gateway <<< "$spec"
    else
      IFS=':' read -r kind iface port <<< "$spec"
      source_ip="$(first_ipv4_for_iface "$iface")"
      gateway="$(gateway_for_iface "$iface")"
    fi

    is_supported_transport_kind "$kind" || fail "unsupported transport kind '$kind'"
    [[ -n "$iface" ]] || fail "transport '$kind' must specify an underlay interface"
    printf '%s\n' "${detected_nics[@]}" | grep -qx "$iface" || fail "interface '$iface' not detected on this host"
    [[ -n "${seen_kinds[$kind]:-}" ]] && fail "transport kind '$kind' was specified more than once"
    if [[ -n "${seen_ifaces[$iface]:-}" ]]; then
      warn "interface '$iface' is reused by transports '${seen_ifaces[$iface]}' and '$kind'"
    fi

    [[ -n "$source_ip" ]] || fail "interface '$iface' has no global IPv4 address"
    if [[ -z "${port:-}" ]]; then
      case "$kind" in
        internet) port="$ENDPOINT_PORT" ;;
        mpls) port="51821" ;;
        lte) port="51822" ;;
        other) port="51823" ;;
      esac
    fi
    [[ "$port" =~ ^[0-9]+$ ]] || fail "invalid port '$port' for transport '$kind'"

    seen_kinds["$kind"]=1
    seen_ifaces["$iface"]="$kind"
    normalized+=("${kind}|${iface}|${port}|${source_ip}|${gateway}")
  done

  TRANSPORT_SPECS=("${normalized[@]}")
}

run_preflight() {
  step "Running preflight checks..."
  ensure_cmd apt-get
  ensure_cmd curl
  ensure_cmd ip
  ensure_cmd python3
  ensure_cmd systemctl

  if [[ ! -f /etc/os-release ]]; then
    fail "/etc/os-release not found; unsupported host"
  fi

  # shellcheck disable=SC1091
  . /etc/os-release
  case "${ID:-}" in
    debian|ubuntu) info "Detected supported OS: ${PRETTY_NAME:-$ID}" ;;
    *) fail "unsupported OS '${PRETTY_NAME:-$ID}' (expected Debian/Ubuntu)" ;;
  esac

  local health_url="${CONTROLLER_URL}/health"
  curl -fsS -o /dev/null --max-time 10 "$health_url"
  info "Controller health check succeeded: $health_url"
}

install_system_dependencies() {
  step "Installing system dependencies (wireguard-tools, frr, git, curl)..."
  apt-get update -y >> "$LOG_FILE" 2>&1
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    ca-certificates curl frr git python3 wireguard-tools >> "$LOG_FILE" 2>&1
}

enable_frr_daemons() {
  step "Enabling FRR daemons (bgpd, bfdd)..."
  if [[ -f "$FRR_DAEMONS" ]]; then
    sed -i 's/^bgpd=no/bgpd=yes/' "$FRR_DAEMONS"
    sed -i 's/^bfdd=no/bfdd=yes/' "$FRR_DAEMONS"
    echo "service integrated-vtysh-config" > /etc/frr/vtysh.conf
    info "bgpd and bfdd enabled"
  else
    warn "FRR daemons file not found; the agent will configure FRR on first run"
  fi
}

install_uv() {
  step "Installing uv..."
  export PATH="$HOME/.local/bin:$PATH"
  if command -v uv >/dev/null 2>&1; then
    info "uv already installed"
    return
  fi
  curl -fsSL https://astral.sh/uv/install.sh 2>>"$LOG_FILE" | sh >> "$LOG_FILE" 2>&1
  export PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null 2>&1 || fail "uv installation completed but uv is still not on PATH"
}

install_agent() {
  case "$INSTALL_SOURCE" in
    pypi)
      INSTALL_MODE_LABEL="PyPI"
      step "Installing weave agent from PyPI..."
      UV_TOOL_BIN_DIR=/usr/local/bin uv tool install --python 3.12 --upgrade weave-agent >> "$LOG_FILE" 2>&1
      ;;
    github)
      INSTALL_MODE_LABEL="GitHub (${REPO_REF})"
      step "Installing weave agent from GitHub..."
      UV_TOOL_BIN_DIR=/usr/local/bin uv tool install --python 3.12 --upgrade \
        "git+https://github.com/danohn/weave@${REPO_REF}#subdirectory=agent" >> "$LOG_FILE" 2>&1
      ;;
    *)
      fail "unsupported install source '$INSTALL_SOURCE' (expected pypi or github)"
      ;;
  esac
}

write_config() {
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
}

install_service() {
  step "Installing systemd service..."
  write_service_file
  systemctl daemon-reload >> "$LOG_FILE" 2>&1
  systemctl enable --now weave >> "$LOG_FILE" 2>&1
}

verify_install() {
  step "Verifying installation..."
  [[ -x /usr/local/bin/weave ]] || fail "weave executable not found at /usr/local/bin/weave"
  [[ -f /etc/weave/agent.env ]] || fail "agent configuration file was not written"
  systemctl is-active --quiet weave || fail "weave systemd service is not active"
  info "systemd service is active"

  local node_id=""
  local vpn_ip=""
  for _ in $(seq 1 30); do
    if [[ -f "$STATE_FILE" ]]; then
      node_id="$(parse_state_field node_id || true)"
      vpn_ip="$(parse_state_field vpn_ip || true)"
      break
    fi
    sleep 1
  done

  log ""
  log "────────────────────────────────────────"
  log "  Install summary"
  log ""
  info "Install source: $INSTALL_MODE_LABEL"
  info "Node:           $NODE_NAME"
  info "Controller:     $CONTROLLER_URL"
  info "Heartbeat:      ${HEARTBEAT_INTERVAL}s"
  info "Peer poll:      ${PEER_POLL_INTERVAL}s"
  log "  Transport bindings:"
  while IFS= read -r line; do
    info "$line"
  done < <(render_transport_summary "${TRANSPORT_SPECS[@]}")

  if [[ -n "$node_id" ]]; then
    info "Registration:   complete"
    info "Node ID:        $node_id"
    info "VPN IP:         $vpn_ip"
  else
    warn "Registration not yet visible in $STATE_FILE"
    warn "The agent is installed and running; activation or controller reachability may still be pending"
  fi

  if command -v wg >/dev/null 2>&1; then
    info "WireGuard:      $(wg show interfaces 2>/dev/null || echo "no interfaces yet")"
  fi

  log ""
  log "  Follow logs:      journalctl -fu weave"
  log "  Full install log: $LOG_FILE"
  log ""

  if [[ -n "$node_id" ]]; then
    echo "WEAVE_INSTALL=success node=${NODE_NAME} node_id=${node_id} vpn_ip=${vpn_ip}"
  else
    echo "WEAVE_INSTALL=success node=${NODE_NAME} node_id=pending vpn_ip=pending"
  fi
}

# ── Main flow ────────────────────────────────────────────────────────────────
run_preflight

step "Detecting underlay interfaces..."
mapfile -t DETECTED_NICS < <(detect_nics)
normalize_transport_specs "${DETECTED_NICS[@]}"
TRANSPORTS_JSON="$(build_transport_json "${TRANSPORT_SPECS[@]}")"

log ""
log "Weave Agent Installer"
log "────────────────────────────────────────"
info "Node:           $NODE_NAME"
info "Controller:     $CONTROLLER_URL"
info "Install source: $INSTALL_SOURCE"
if [[ "$INSTALL_SOURCE" == "github" ]]; then
  info "Repo ref:       $REPO_REF"
fi
log "  Planned transports:"
while IFS= read -r line; do
  info "$line"
done < <(render_transport_summary "${TRANSPORT_SPECS[@]}")
log ""

handle_existing_state
install_system_dependencies
enable_frr_daemons
install_uv
install_agent
write_config
install_service
verify_install
