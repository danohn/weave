# Weave

A WireGuard-based SD-WAN control plane. The controller handles orchestration, NAT traversal, and peer distribution. Edge nodes run a lightweight agent that manages WireGuard automatically.

## Repository structure

```
weave/
├── controller/         # FastAPI control plane
├── agent/              # Edge node daemon (Python, systemd)
├── frontend/           # Dashboard (HTML/CSS/JS, served by nginx)
├── docker-compose.yml
└── nginx.conf
```

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

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```ini
ADMIN_TOKEN=your-secret-token
WEAVE_DOMAIN=weave.example.com
TRAEFIK_MIDDLEWARE=chain-internal@file   # optional
```

Then start the stack:

```bash
docker compose up -d --build
```

The dashboard and API will be available at `https://<WEAVE_DOMAIN>`. The stack expects an external Docker network named `backend` and a running Traefik instance attached to it.

## Configuration

### Docker environment (`.env`)

| Variable | Required | Description |
|---|---|---|
| `ADMIN_TOKEN` | Yes | Bearer token for all admin endpoints |
| `WEAVE_DOMAIN` | Yes | Domain Traefik routes to the dashboard and API |
| `TRAEFIK_MIDDLEWARE` | No | Traefik middleware chain to apply (e.g. `chain-internal@file`) |
| `VPN_SUBNET` | No | Overlay subnet to allocate VPN IPs from (default: `10.0.0.0/24`) |

### Controller settings

These can be set in `controller/.env` for local development or passed as environment variables in Docker.

| Variable | Default | Description |
|---|---|---|
| `ADMIN_TOKEN` | `changeme-admin-token` | Bearer token for all admin endpoints |
| `DATABASE_URL` | `sqlite+aiosqlite:///./weave.db` | SQLAlchemy async DB URL |
| `VPN_SUBNET` | `10.0.0.0/24` | Overlay subnet to allocate VPN IPs from |
| `REQUIRE_PREAUTH` | `true` | Reject registrations that don't supply a valid pre-auth token |
| `STALE_THRESHOLD_SECONDS` | `120` | Seconds without a heartbeat before a node is marked OFFLINE |
| `STALE_CHECK_INTERVAL` | `30` | How often the expiry sweep runs |

To use PostgreSQL: set `DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db` and run `uv add asyncpg` in `controller/`.

## Running tests

```bash
cd controller
uv run pytest -v
```

## Installing an edge node

From the controller host (or anywhere with admin access), generate a pre-auth token for the new node:

```bash
curl -s -X POST http://<controller-host>:8005/api/v1/auth/tokens \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"label": "sdn-3"}'
# {"id": "...", "token": "abc123...", ...}
```

Then on the new node (as root), run:

```bash
curl -fsSL https://raw.githubusercontent.com/danohn/weave/refs/heads/main/agent/install.sh \
  | bash -s -- \
      --controller-url https://<controller-host> \
      --node-name <name> \
      --preauth-token <token>
```

The script installs the agent directly from GitHub — no local repo checkout required. The node registers, auto-activates using the token, brings up WireGuard, and starts running as a systemd service.

Useful commands on an edge node:

```bash
journalctl -fu weave     # follow logs
systemctl restart weave
cat /etc/weave/state.json
wg show wg0
```

---

## API reference

The base URL in examples below is `http://localhost:8000` (local dev). In production replace with `http://<host>:8005`.

Admin endpoints require `Authorization: Bearer <ADMIN_TOKEN>`.
Node endpoints require `Authorization: Bearer <auth_token>` (returned at registration).

---

### Pre-auth tokens

#### `POST /api/v1/auth/tokens` (admin)

Create a single-use token. When a node registers with this token it is auto-activated without manual intervention.

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/tokens \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"label": "sdn-4 cloud-init"}'
# {"id": "...", "token": "abc123...", "label": "sdn-4 cloud-init", "used_at": null, ...}
```

#### `GET /api/v1/auth/tokens` (admin)

List all tokens with their used/unused status.

#### `DELETE /api/v1/auth/tokens/{id}` (admin)

Delete an unused token. Returns `400` if the token has already been used.

---

### Nodes

#### `POST /api/v1/nodes/register`

Register a new edge node. Returns the node's bearer token and allocated VPN IP.

If `REQUIRE_PREAUTH=true` (the default), a valid `preauth_token` must be supplied and the node is immediately `ACTIVE`. Without a pre-auth token the request is rejected.

```bash
curl -s -X POST http://localhost:8000/api/v1/nodes/register \
  -H "Content-Type: application/json" \
  -d '{
    "name": "sdn-4",
    "wireguard_public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "endpoint_ip": "192.168.1.100",
    "endpoint_port": 51820,
    "preauth_token": "abc123..."
  }'
# {"id": "...", "auth_token": "...", "vpn_ip": "10.0.0.4"}
```

#### `POST /api/v1/nodes/{id}/heartbeat`

Keep-alive. Updates `last_seen` and refreshes the reflected endpoint IP used for NAT detection. A node that was `OFFLINE` is automatically restored to `ACTIVE` on heartbeat.

```bash
curl -s -X POST http://localhost:8000/api/v1/nodes/<id>/heartbeat \
  -H "Authorization: Bearer <auth_token>"
# {"status": "ACTIVE", "last_seen": "2025-01-15T12:00:00Z"}
```

#### `GET /api/v1/nodes/{id}/peers`

Returns all `ACTIVE` peers visible to this node (excludes self, `PENDING`, `OFFLINE`, and `REVOKED` nodes). Includes NAT traversal hints.

If the peer's `reflected_endpoint_ip` (as observed by the controller) differs from their self-reported `endpoint_ip`, `nat_detected` is `true` and `preferred_endpoint` is set to the reflected IP for hole-punching.

```bash
curl -s http://localhost:8000/api/v1/nodes/<id>/peers \
  -H "Authorization: Bearer <auth_token>"
```

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

Real-time feed of node and token state. The dashboard connects here automatically. On connect the server immediately pushes current state; subsequent messages are broadcast on any mutation (registration, heartbeat, activation, expiry, etc.).

Message format:

```json
{
  "nodes":  [ ...NodeAdminResponse... ],
  "tokens": [ ...PreAuthTokenResponse... ]
}
```

---

## Node lifecycle

```
POST /register (with preauth token)  ->  ACTIVE   (auto-activated)
POST /register (no token)            ->  PENDING  (requires REQUIRE_PREAUTH=false)
                                            |
                             PATCH /activate (admin)
                                            |
                                         ACTIVE   -- visible to peers
                                            |
                              no heartbeat for 120s
                                            |
                                         OFFLINE  -- excluded from peer lists
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
