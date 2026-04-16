# Weave

A WireGuard-based SD-WAN control plane. The controller handles orchestration, NAT traversal, and peer distribution. Edge nodes run a lightweight agent that manages WireGuard automatically.

## Repository structure

```
sdn/
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

### Production (Docker)

```bash
ADMIN_TOKEN=secret docker compose up -d --build
```

nginx listens on port `8005` and serves the dashboard at `http://<host>:8005`.
API docs are available at `http://<host>:8005/docs`.

## Configuration

All variables are set via environment or a `.env` file in `controller/`.

| Variable | Default | Description |
|---|---|---|
| `ADMIN_TOKEN` | `changeme-admin-token` | Bearer token for all admin endpoints |
| `DATABASE_URL` | `sqlite+aiosqlite:///./sdwan.db` | SQLAlchemy async DB URL |
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

```bash
cd agent
sudo ./install.sh \
  --controller-url http://<controller-host>:8005 \
  --endpoint-ip <this-node-public-ip> \
  --node-name <name> \
  --preauth-token <token>
```

Generate a pre-auth token first via the dashboard or the API (see below). The agent registers, auto-activates using the token, brings up WireGuard, and runs as a systemd service.

Useful commands on an edge node:

```bash
journalctl -fu sdwan-agent    # follow logs
systemctl restart sdwan-agent
cat /etc/sdwan-agent/state.json
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
    "endpoint_ip": "10.18.20.167",
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
