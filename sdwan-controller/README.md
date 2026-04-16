# SD-WAN Controller

A FastAPI-based SD-WAN control plane analogous to Cisco Viptela's **vBond** (orchestration/NAT traversal) and **vSmart** (policy/peer distribution) components, built on **WireGuard** and **FRRouting**.

## Architecture

```
sdwan-controller/
├── app/
│   ├── main.py                 # FastAPI app, lifespan, /health
│   ├── core/
│   │   ├── config.py           # pydantic-settings (env vars)
│   │   └── security.py         # Token auth dependencies
│   ├── db/
│   │   ├── base.py             # SQLAlchemy async engine + session
│   │   └── models.py           # Node ORM model
│   ├── schemas/
│   │   └── node.py             # Pydantic v2 request/response schemas
│   ├── routers/
│   │   ├── nodes.py            # Registration, heartbeat, admin ops
│   │   └── peers.py            # Peer list distribution
│   └── services/
│       ├── node_service.py     # Node business logic
│       └── peer_service.py     # Peer selection + NAT detection
├── alembic/                    # Database migrations
├── tests/
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## Quick Start

### Local development

```bash
# Install dependencies
uv sync

# Run database migrations (or let the app auto-create tables on startup)
uv run alembic upgrade head

# Start the server
ADMIN_TOKEN=mysecret uv run uvicorn app.main:app --reload
```

### Docker

```bash
ADMIN_TOKEN=mysecret docker compose up --build
```

The API is available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./sdwan.db` | SQLAlchemy async DB URL |
| `ADMIN_TOKEN` | `changeme-admin-token` | Static bearer token for admin endpoints |
| `VPN_SUBNET` | `10.0.0.0/24` | Reference overlay subnet |

For PostgreSQL: `DATABASE_URL=postgresql+asyncpg://user:pass@host/db`

## Running Tests

```bash
uv run pytest -v
```

---

## API Reference

All node endpoints that require a bearer token use the `auth_token` returned at registration.

### `GET /health`

No authentication required.

```bash
curl http://localhost:8000/health
# {"status":"ok","node_count":2}
```

---

### `POST /api/v1/nodes/register`

Register a new edge node. Returns its bearer token for subsequent calls.

```bash
curl -s -X POST http://localhost:8000/api/v1/nodes/register \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "branch-sydney",
    "wireguard_public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "endpoint_ip": "203.0.113.10",
    "endpoint_port": 51820,
    "vpn_ip": "10.0.0.1"
  }'
# {
#   "id": "550e8400-e29b-41d4-a716-446655440000",
#   "auth_token": "Ry3...long_token...xQ",
#   "vpn_ip": "10.0.0.1"
# }
```

---

### `POST /api/v1/nodes/{node_id}/heartbeat`

Keep-alive. Updates `last_seen` and refreshes the reflected (NAT) endpoint IP.

```bash
curl -s -X POST http://localhost:8000/api/v1/nodes/550e8400-e29b-41d4-a716-446655440000/heartbeat \
  -H 'Authorization: Bearer Ry3...long_token...xQ'
# {"status":"ACTIVE","last_seen":"2025-01-15T12:00:00Z"}
```

---

### `GET /api/v1/nodes/{node_id}/peers`

Returns all **ACTIVE** peers (excludes self, PENDING, and REVOKED nodes). Includes NAT traversal hints.

```bash
curl -s http://localhost:8000/api/v1/nodes/550e8400-e29b-41d4-a716-446655440000/peers \
  -H 'Authorization: Bearer Ry3...long_token...xQ'
# [
#   {
#     "name": "branch-london",
#     "wireguard_public_key": "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=",
#     "vpn_ip": "10.0.0.2",
#     "preferred_endpoint": "198.51.100.20",
#     "endpoint_port": 51820,
#     "nat_detected": false
#   }
# ]
```

**NAT detection:** if the peer's `reflected_endpoint_ip` (as seen by the controller) differs from the peer's self-reported `endpoint_ip`, `nat_detected` is `true` and `preferred_endpoint` uses the reflected IP for hole-punching.

---

### `PATCH /api/v1/nodes/{node_id}/activate` *(admin)*

Transitions a node from `PENDING` → `ACTIVE`.

```bash
curl -s -X PATCH http://localhost:8000/api/v1/nodes/550e8400-e29b-41d4-a716-446655440000/activate \
  -H 'Authorization: Bearer mysecret'
```

---

### `DELETE /api/v1/nodes/{node_id}/revoke` *(admin)*

Sets node status to `REVOKED`. The node is immediately excluded from all peer lists.

```bash
curl -s -X DELETE http://localhost:8000/api/v1/nodes/550e8400-e29b-41d4-a716-446655440000/revoke \
  -H 'Authorization: Bearer mysecret'
```

---

### `GET /api/v1/nodes/` *(admin)*

List all nodes with full details.

```bash
curl -s http://localhost:8000/api/v1/nodes/ \
  -H 'Authorization: Bearer mysecret'
```

---

## Node Lifecycle

```
POST /register  →  PENDING
                       │
         PATCH /activate (admin)
                       │
                    ACTIVE  ──── appears in peer lists
                       │
          DELETE /revoke (admin)
                       │
                    REVOKED ──── excluded from peer lists
```

## WireGuard Integration (agent-side sketch)

On each edge node, a daemon would:

1. **Register** once on first boot, store `auth_token` securely.
2. **Heartbeat** every 30 s to keep `last_seen` fresh and update NAT state.
3. **Poll peers** every 60 s, diff against current WireGuard config, then call `wg set` / `wg addconf` for additions and removals.

```bash
# Example peer sync loop (pseudocode)
while true; do
  PEERS=$(curl -s .../peers -H "Authorization: Bearer $TOKEN")
  echo "$PEERS" | jq -r '.[] | "peer \(.wireguard_public_key)\n  endpoint \(.preferred_endpoint):\(.endpoint_port)\n  allowed-ips \(.vpn_ip)/32"' \
    | wg addconf wg0 /dev/stdin
  sleep 60
done
```

## Swapping to PostgreSQL

1. Install the async driver: `uv add asyncpg`
2. Set `DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/sdwan`
3. Run `uv run alembic upgrade head`

No application code changes required.
