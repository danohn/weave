# Weave

A WireGuard-based SD-WAN control plane with FRR-powered BGP route reflection and BFD-assisted failure detection. The controller handles orchestration, NAT traversal, peer distribution, and dynamic routing across the overlay. Edge nodes run a lightweight agent that manages WireGuard automatically and applies FRR configuration when routing is enabled.

## Architecture

Weave has four moving parts:

- **Controller**: FastAPI service that stores node state, allocates VPN IPs, manages bootstrap device claims, and serves peer lists to agents. It also runs FRR as a BGP route reflector on the overlay.
- **Agent**: lightweight daemon installed on each edge node. It registers with the controller, maintains WireGuard state, heartbeats periodically, and applies FRR configuration when present.
- **Frontend**: static admin dashboard served by nginx. It talks to the controller over the same origin using the REST API and admin WebSocket.
- **Reverse proxy**: Traefik routes browser/API traffic to nginx or the controller based on path, while WireGuard UDP traffic goes directly to the controller host on port `51820`.

At runtime, the controller acts as the source of truth. Agents register once, receive a node auth token plus VPN IP, then keep their local WireGuard and FRR state in sync from controller-provided peer updates. Overlay transport happens over WireGuard; routed site reachability is exchanged over BGP sessions running across that overlay.

## Why FRR, BGP, and BFD?

Weave is more than a WireGuard peer distributor. WireGuard gives each node secure encrypted transport, but FRR is what turns that transport into a routed SD-WAN:

- **BGP advertises site subnets**: each node can optionally publish a `site_subnet` behind it, so remote nodes learn LAN reachability dynamically instead of relying on hand-written static routes.
- **Route reflection avoids full-mesh BGP**: the controller runs FRR as a route reflector, so every node peers only with the controller over the overlay. Nodes do not need to maintain BGP sessions to every other node.
- **BFD accelerates failure detection**: BFD is enabled alongside BGP so routing liveliness is detected faster than waiting on default BGP convergence timers alone.
- **WireGuard and routing stay separate**: WireGuard handles encryption and transport, while FRR handles prefix exchange and routing decisions.

In the current implementation, the controller brings up `wg0`, starts `bgpd` and `bfdd`, defines a `NODES` peer-group, and dynamically adds or removes neighbors as nodes become active or revoked. Each agent fetches a generated FRR config from the controller, peers its local FRR instance with the controller over the WireGuard overlay, and advertises its `site_subnet` when one is configured.

## Repository structure

```
weave/
├── controller/         # FastAPI control plane
├── agent/              # Edge node daemon (Python, systemd)
├── frontend/           # Dashboard (HTML/CSS/JS, served by nginx)
├── docker-compose.yml
└── nginx.conf
```

## Getting started

The shortest path to a working deployment is:

1. Start the controller stack with Docker and Traefik.
2. Generate a device claim from the controller.
3. Bootstrap an edge node with the install script.
4. Confirm the node appears in the dashboard and `wg show` lists peers.

If you just want to develop locally, use the local development flow below. If you want a real deployment, start with the production section and then continue to **Installing an edge node**.

## Quick start

### Local development

```bash
cd controller
uv sync
ADMIN_TOKEN=secret uv run uvicorn app.main:app --reload
# API at http://localhost:8000, docs at http://localhost:8000/docs
# Point the dashboard at http://localhost:8000 by opening frontend/index.html
```

### Production (Docker + Traefik)

There are two supported deployment modes:

- **Existing Traefik**: use [`docker-compose.yml`](/Users/daniel/Code/weave/docker-compose.yml) when you already run a shared Traefik instance and can attach Weave to its Docker network.
- **Bundled Traefik**: use [`docker-compose.with-traefik.yml`](/Users/daniel/Code/weave/docker-compose.with-traefik.yml) when you want a self-contained stack for evaluation or a simple standalone deployment.

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```ini
ADMIN_TOKEN=your-secret-token
WEAVE_DOMAIN=weave.example.com
TRAEFIK_NETWORK=backend               # existing-Traefik mode only
TRAEFIK_MIDDLEWARE=chain-internal@file   # optional
```

#### Option A: Existing Traefik

Start the default stack:

```bash
docker compose up -d --build
```

The dashboard and API will be available at `https://<WEAVE_DOMAIN>`. This mode expects an external Docker network shared with your existing Traefik instance.
Set `TRAEFIK_NETWORK` to the Docker network name your Traefik container uses.

#### Option B: Bundled Traefik

Start the self-contained stack:

```bash
docker compose -f docker-compose.with-traefik.yml up -d --build
```

In this mode Traefik is started as part of the stack and listens on port `80`. Point DNS or your local hosts file at the Docker host so `http://<WEAVE_DOMAIN>` resolves there. Add TLS and certificate resolver settings to the Traefik service if you want HTTPS in this mode.

## Configuration

### Docker environment (`.env`)

| Variable | Required | Description |
|---|---|---|
| `ADMIN_TOKEN` | Yes | Bearer token for all admin endpoints |
| `WEAVE_DOMAIN` | Yes | Domain Traefik routes to the dashboard and API |
| `TRAEFIK_NETWORK` | Existing Traefik only | Docker network shared with your existing Traefik container |
| `TRAEFIK_MIDDLEWARE` | No | Traefik middleware chain to apply (e.g. `chain-internal@file`) |
| `VPN_SUBNET` | No | Overlay subnet to allocate VPN IPs from (default: `10.0.0.0/24`) |

### Controller settings

These can be set in `controller/.env` for local development or passed as environment variables in Docker.

| Variable | Default | Description |
|---|---|---|
| `ADMIN_TOKEN` | `changeme-admin-token` | Bearer token for all admin endpoints |
| `DATABASE_URL` | `sqlite+aiosqlite:///./weave.db` | SQLAlchemy async DB URL |
| `VPN_SUBNET` | `10.0.0.0/24` | Overlay subnet to allocate VPN IPs from |
| `REQUIRE_PREAUTH` | `true` | Reject registrations that don't supply a valid claim token |
| `STALE_THRESHOLD_SECONDS` | `75` | Seconds without a heartbeat before a node is marked OFFLINE |
| `STALE_CHECK_INTERVAL` | `15` | How often the expiry sweep runs |

To use PostgreSQL: set `DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db` and run `uv add asyncpg` in `controller/`.

## Running tests

```bash
cd controller
uv run pytest -v
```

## Installing an edge node

From the controller host (or anywhere with admin access), generate a bootstrap claim for the new node:

```bash
curl -s -X POST https://<controller-host>/api/v1/auth/claims \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"device_id": "sdn-3", "expected_name": "sdn-3"}'
# {"id": "...", "token": "abc123...", "status": "UNCLAIMED", ...}
```

Then on the new node (as root), run:

```bash
REF=v0.1.0
curl -fsSL "https://raw.githubusercontent.com/danohn/weave/${REF}/agent/install.sh" \
  | bash -s -- \
      --controller-url https://<controller-host> \
      --node-name <name> \
      --claim-token <token> \
      --repo-ref "${REF}"
```

The script installs the agent directly from GitHub — no local repo checkout required. Pinning both the script URL and `--repo-ref` to the same release tag keeps the bootstrap script, installed package, and systemd unit on the same revision. The node registers, auto-activates using the claim, brings up WireGuard, and starts running as a systemd service.

Useful commands on an edge node:

```bash
journalctl -fu weave     # follow logs
systemctl restart weave
cat /etc/weave/state.json
wg show wg0
```

### Verifying the VPN works

After the node is `ACTIVE`, confirm WireGuard is up and peers are wired in:

```bash
wg show wg0
# Should list one [Peer] block per other active node, each with an endpoint and allowed IP
```

Then ping another node's VPN IP (shown in the dashboard or `state.json`):

```bash
ping 10.0.0.1    # replace with the VPN IP of any other active node
```

If `wg show` lists peers but pings fail, check the firewall section below.

### Firewall requirements

WireGuard communicates directly between nodes over UDP. **Every node must allow inbound UDP on port 51820** (or whichever port you configured with `--endpoint-port`). Without this, nodes will appear `ACTIVE` in the dashboard but pass no traffic.

On nodes using `ufw`:

```bash
ufw allow 51820/udp
```

On nodes using `iptables` directly:

```bash
iptables -A INPUT -p udp --dport 51820 -j ACCEPT
```

Cloud providers (AWS, GCP, Hetzner, etc.) also require an inbound rule in their security group / firewall console for UDP 51820.

---

## Troubleshooting

### API returns HTML instead of JSON

If `/health` or `/api/...` returns the dashboard HTML instead of JSON, the request is reaching the frontend nginx container rather than the controller. Check that the controller is up and that your reverse proxy is routing `/api`, `/ws`, and `/health` to the API service.

### Dashboard loads but live updates fail

If the dashboard renders but stops updating, check the browser console and confirm `GET /ws` is reaching the controller. A failed WebSocket upgrade usually means the controller is down or the reverse proxy is not forwarding WebSocket traffic correctly.

### Nodes are ACTIVE but traffic does not pass

If `wg show` lists peers but pings fail, verify inbound UDP 51820 is allowed on every node and in any cloud firewall or security group.

### Controller fails during startup after an upgrade

Check `docker compose logs controller` for Alembic errors. If a migration partially applied, the schema may be ahead of `alembic_version`; fix the database state before retrying the container.

---

## API reference

The base URL in examples below is `http://localhost:8000` (local dev). In production replace with `https://<WEAVE_DOMAIN>`.

Admin endpoints require `Authorization: Bearer <ADMIN_TOKEN>`.
Node endpoints require `Authorization: Bearer <auth_token>` (returned at registration).

---

### Device claims

#### `POST /api/v1/auth/claims` (admin)

Create a single-use bootstrap claim. When a node registers with this claim token it is auto-activated and linked back to the claim record.

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/claims \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"device_id": "sdn-4", "expected_name": "sdn-4"}'
# {"id": "...", "token": "abc123...", "device_id": "sdn-4", "claimed_at": null, ...}
```

#### `GET /api/v1/auth/claims` (admin)

List all claims with their status and claim metadata.

#### `POST /api/v1/auth/claims/{id}/revoke` (admin)

Revoke a claim so it can no longer be used for enrollment.

#### `DELETE /api/v1/auth/claims/{id}` (admin)

Delete an unused claim. Returns `400` if the claim has already been used.

---

### Nodes

#### `POST /api/v1/nodes/register`

Register a new edge node. Returns the node's bearer token and allocated VPN IP.

If `REQUIRE_PREAUTH=true` (the default), a valid `claim_token` must be supplied and the node is immediately `ACTIVE`. Without a claim token the request is rejected.

```bash
curl -s -X POST http://localhost:8000/api/v1/nodes/register \
  -H "Content-Type: application/json" \
  -d '{
    "name": "sdn-4",
    "wireguard_public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "endpoint_port": 51820,
    "claim_token": "abc123..."
  }'
# {"id": "...", "auth_token": "...", "vpn_ip": "10.0.0.4", "device_claim_id": "..."}
```

> The endpoint IP is not sent by the agent — the controller infers it from the source address of the HTTP request.

#### `POST /api/v1/nodes/{id}/heartbeat`

Keep-alive. Updates `last_seen` and refreshes the reflected endpoint IP used for NAT detection. A node that was `OFFLINE` is automatically restored to `ACTIVE` on heartbeat.

```bash
curl -s -X POST http://localhost:8000/api/v1/nodes/<id>/heartbeat \
  -H "Authorization: Bearer <auth_token>"
# {"status": "ACTIVE", "last_seen": "2025-01-15T12:00:00Z"}
```

#### `GET /api/v1/nodes/{id}/peers`

Returns all visible peers for this node (excludes self, `PENDING`, `OFFLINE`, and `REVOKED` nodes). The `preferred_endpoint` is always the IP the controller observed the peer connecting from.

```bash
curl -s http://localhost:8000/api/v1/nodes/<id>/peers \
  -H "Authorization: Bearer <auth_token>"
```

#### `POST /api/v1/nodes/{id}/rotate-token`

Rotate the node's operational bearer token. The old token stops working immediately.

#### `PATCH /api/v1/nodes/{id}/activate` (admin)

Manually transition a `PENDING` node to `ACTIVE`. Only needed when `REQUIRE_PREAUTH=false`.

#### `DELETE /api/v1/nodes/{id}/revoke` (admin)

Set node status to `REVOKED`. Immediately excluded from all peer lists. The record is kept.

#### `DELETE /api/v1/nodes/{id}` (admin)

Hard delete. Removes the node record entirely and frees its VPN IP for reuse.

#### `GET /api/v1/nodes/` (admin)

List all nodes with full details.

---

### Health

#### `GET /health`

No authentication required.

```bash
curl http://localhost:8000/health
# {"status": "ok", "node_count": 3}
```

---

### WebSocket

#### `GET /ws?token=<ADMIN_TOKEN>`

Real-time feed of node and claim state. The dashboard connects here automatically. On connect the server immediately pushes current state; subsequent messages are broadcast on any mutation (registration, heartbeat, activation, expiry, etc.).

Message format:

```json
{
  "nodes":  [ ...NodeAdminResponse... ],
  "claims": [ ...DeviceClaimResponse... ]
}
```

---

## Node lifecycle

```
POST /register (with claim token)    ->  ACTIVE   (auto-activated)
POST /register (no token)            ->  PENDING  (requires REQUIRE_PREAUTH=false)
                                            |
                             PATCH /activate (admin)
                                            |
                                         ACTIVE   -- visible to peers
                                          /   \
                          clean shutdown /     \ no heartbeat for 75s
                     (agent sends SIGTERM)       (crash or network loss)
                                        /         \
                                     OFFLINE  -- excluded from peer lists until heartbeat recovery
                                            |
                              heartbeat received
                                            |
                                         ACTIVE   (auto-recovery)
                                            |
                             DELETE /revoke (admin)
                                            |
                                         REVOKED  -- excluded from peer lists
                                            |
                             DELETE /{id} (admin)
                                            |
                                         (deleted, VPN IP freed)
```
