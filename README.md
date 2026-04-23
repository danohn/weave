# Weave

WireGuard-based SD-WAN. The controller manages node registration, VPN IP allocation, and peer distribution. Edge nodes run a small agent that keeps WireGuard in sync. BGP (via FRR) handles site-to-site routing, with the controller acting as a route reflector over the overlay.

## Components

- **Controller** — FastAPI service. Stores node state, allocates VPN IPs, handles device claims, and runs FRR as a BGP route reflector.
- **Agent** — lightweight daemon on each edge node. Registers with the controller, manages WireGuard, and applies FRR config when routing is enabled.
- **Frontend** — React dashboard, built with Vite and served by nginx.
- **Reverse proxy** — Traefik routes browser and API traffic to the right service. WireGuard UDP goes directly to the controller on port 51820.

## Repository layout

```
weave/
├── controller/         # FastAPI control plane
├── agent/              # Edge node daemon (Python, systemd)
├── frontend/           # React dashboard (Vite + nginx)
├── docker-compose.yml
└── docker-compose.with-traefik.yml
```

## Getting started

### Local development

Run the controller:

```bash
cd controller
uv sync --group dev
SESSION_SECRET=dev OIDC_ISSUER=... uv run uvicorn app.main:app --reload
# API at http://localhost:8000, docs at http://localhost:8000/docs
```

`SESSION_COOKIE_SECURE` defaults to `false` in local HTTP dev and `true` when `WEAVE_DOMAIN` is set. Override it explicitly if your setup needs different cookie behavior.

Install the repo hooks:

```bash
cd controller
uv sync --group dev
cd ..
./controller/.venv/bin/pre-commit install
```

Run the frontend dev server:

```bash
cd frontend
npm install
npm run dev
# Dashboard at http://localhost:5173
```

### Production (Docker + Traefik)

Two deployment options:

- **Existing Traefik** (`docker-compose.yml`) — attach Weave to your existing Traefik Docker network.
- **Bundled Traefik** (`docker-compose.with-traefik.yml`) — self-contained stack, good for evaluation or a dedicated host.

Both production compose files pull prebuilt images from GitHub Container Registry:

- `ghcr.io/danohn/weave-frontend:${WEAVE_VERSION}`
- `ghcr.io/danohn/weave-controller:${WEAVE_VERSION}`

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

#### Option A: Existing Traefik

```bash
docker compose pull
docker compose up -d
```

Set `TRAEFIK_NETWORK` to the Docker network your Traefik container is on.

#### Option B: Bundled Traefik

```bash
docker compose -f docker-compose.with-traefik.yml pull
docker compose -f docker-compose.with-traefik.yml up -d
```

Traefik starts as part of the stack and listens on port 80. Point DNS at the Docker host. Add a TLS certificate resolver to the Traefik service if you need HTTPS.

### Local Docker builds

If you want to run the stack from local source instead of GHCR images, add the development override:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

For the bundled Traefik stack:

```bash
docker compose -f docker-compose.with-traefik.yml -f docker-compose.dev.yml up -d --build
```

## Configuration

### `.env` (Docker)

| Variable | Required | Description |
|---|---|---|
| `WEAVE_DOMAIN` | Yes | Domain Traefik routes to the dashboard and API |
| `WEAVE_VERSION` | No | GHCR image tag to deploy (default: current release tag, e.g. `v0.2.1`) |
| `SESSION_SECRET` | Yes | Secret key for signing sessions |
| `SESSION_COOKIE_SECURE` | No | Force Secure session cookies on/off (auto-enables when `WEAVE_DOMAIN` is set) |
| `OIDC_ISSUER` | Yes | OIDC provider issuer URL |
| `OIDC_CLIENT_ID` | Yes | OIDC client ID |
| `OIDC_CLIENT_SECRET` | Yes | OIDC client secret |
| `ADMIN_TOKEN` | No | Bearer token for agent-facing admin endpoints |
| `TRAEFIK_NETWORK` | Existing Traefik only | Docker network shared with your Traefik container |
| `TRAEFIK_MIDDLEWARE` | No | Traefik middleware chain for API routes |
| `TRAEFIK_MIDDLEWARE_UI` | No | Traefik middleware chain for the dashboard (falls back to `TRAEFIK_MIDDLEWARE`) |
| `VPN_SUBNET` | No | Overlay subnet (default: `10.0.0.0/24`) |
| `OIDC_REDIRECT_URI` | No | Override the OIDC callback URL (auto-derived from `WEAVE_DOMAIN` if unset) |
| `OIDC_ADMIN_GROUP` | No | OIDC group required for admin access |

### Controller settings

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./weave.db` | SQLAlchemy async DB URL |
| `STALE_THRESHOLD_SECONDS` | `75` | Seconds without a heartbeat before a node goes OFFLINE |
| `STALE_CHECK_INTERVAL` | `15` | How often the expiry sweep runs |
| `REQUIRE_PREAUTH` | `true` | Reject registrations without a valid claim token |

To use PostgreSQL: set `DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db` and run `uv add asyncpg` in `controller/`.

## Running tests

```bash
cd controller
uv sync --group dev
./.venv/bin/pytest -v
```

Run lint and formatting checks:

```bash
./.venv/bin/pre-commit run --all-files
```

## Agent package releases

The edge agent is published to PyPI as `weave-agent`, while the installed CLI remains `weave`.

Install the latest published agent:

```bash
uv tool install weave-agent
```

Upgrade an installed agent:

```bash
uv tool upgrade weave-agent
```

Install the repo release tooling once from the repository root:

```bash
uv sync --group dev
```

Version bumps and release tags are then managed from the repository root:

```bash
uv run bump-my-version bump patch
```

That updates the shared repo release version, creates a release commit, and tags it as `vX.Y.Z`. Pushing the tag triggers the GitHub Actions workflows that publish `weave-agent`, publish the Docker images, and create the GitHub release automatically.

## Installing an edge node

Generate a bootstrap claim from the controller:

```bash
curl -s -X POST https://<WEAVE_DOMAIN>/api/v1/auth/claims \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"device_id": "sdn-3", "expected_name": "sdn-3"}'
# {"id": "...", "token": "abc123...", ...}
```

Then on the new node (as root):

```bash
REF=v0.2.1
curl -fsSL "https://raw.githubusercontent.com/danohn/weave/${REF}/agent/install.sh" \
  | bash -s -- \
      --controller-url https://<WEAVE_DOMAIN> \
      --node-name <name> \
      --claim-token <token> \
      --repo-ref "${REF}"
```

Pin both the script URL and `--repo-ref` to the same tag so everything installs from the same revision.

Useful commands on an edge node:

```bash
journalctl -fu weave
systemctl restart weave
cat /etc/weave/state.json
wg show wg0
```

### Verifying the VPN

After the node goes `ACTIVE`, check WireGuard:

```bash
wg show wg0
# Should show one [Peer] block per active node
ping 10.0.0.1   # replace with another node's VPN IP
```

### Firewall

Every node needs inbound UDP 51820 open:

```bash
# ufw
ufw allow 51820/udp

# iptables
iptables -A INPUT -p udp --dport 51820 -j ACCEPT
```

Cloud providers also need an inbound rule in their security group for UDP 51820.

---

## Troubleshooting

**API returns HTML instead of JSON** — the request hit nginx instead of the controller. Check that the controller is up and Traefik is routing `/api`, `/ws`, `/health`, `/auth`, `/docs`, and `/openapi.json` to the API service.

**Dashboard loads but stops updating** — check the browser console and confirm `GET /ws` is reaching the controller. A failed WebSocket upgrade usually means the controller is down or the proxy isn't forwarding WebSocket traffic.

**Nodes ACTIVE but traffic fails** — `wg show` lists peers but pings fail? Check that UDP 51820 is open on every node and in your cloud firewall.

**Controller fails to start after upgrade** — check `docker compose logs controller` for Alembic errors. A partial migration may have left the schema ahead of `alembic_version`.

---

## API reference

Base URL: `http://localhost:8000` (local dev) or `https://<WEAVE_DOMAIN>` (production).

Admin endpoints require `Authorization: Bearer <ADMIN_TOKEN>`.
Node endpoints require `Authorization: Bearer <auth_token>` (returned at registration).

### Claims

#### `POST /api/v1/auth/claims` (admin)

Create a single-use bootstrap claim.

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/claims \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"device_id": "sdn-4", "expected_name": "sdn-4"}'
```

#### `GET /api/v1/auth/claims` (admin)

List all claims.

#### `POST /api/v1/auth/claims/{id}/revoke` (admin)

Revoke a claim so it can no longer be used for enrollment.

#### `DELETE /api/v1/auth/claims/{id}` (admin)

Delete an unused claim. Returns `400` if already used.

### Nodes

#### `POST /api/v1/nodes/register`

Register a new edge node. Returns the node's bearer token and VPN IP.

With `REQUIRE_PREAUTH=true` (default), a valid `claim_token` is required and the node is immediately `ACTIVE`.

```bash
curl -s -X POST http://localhost:8000/api/v1/nodes/register \
  -H "Content-Type: application/json" \
  -d '{
    "name": "sdn-4",
    "wireguard_public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "endpoint_port": 51820,
    "claim_token": "abc123..."
  }'
```

> The endpoint IP isn't sent by the agent — the controller infers it from the source address of the request.

#### `POST /api/v1/nodes/{id}/heartbeat`

Keep-alive. Updates `last_seen` and refreshes the reflected endpoint IP. A node that was `OFFLINE` recovers automatically on the next heartbeat.

#### `GET /api/v1/nodes/{id}/peers`

Returns all visible peers (excludes self, `PENDING`, `OFFLINE`, `REVOKED`). The `preferred_endpoint` is always the IP the controller saw the peer connect from.

#### `POST /api/v1/nodes/{id}/rotate-token`

Rotate the node's bearer token. The old token stops working immediately.

#### `PATCH /api/v1/nodes/{id}/activate` (admin)

Manually activate a `PENDING` node. Only needed when `REQUIRE_PREAUTH=false`.

#### `DELETE /api/v1/nodes/{id}/revoke` (admin)

Set status to `REVOKED`. Excluded from peer lists immediately; record is kept.

#### `DELETE /api/v1/nodes/{id}` (admin)

Hard delete. Removes the record and frees the VPN IP.

#### `GET /api/v1/nodes/` (admin)

List all nodes.

### Health

#### `GET /health`

```bash
curl http://localhost:8000/health
# {"status": "ok", "node_count": 3}
```

### WebSocket

#### `GET /ws`

Real-time dashboard feed. Requires an authenticated browser session (OIDC login). On connect the server pushes current state; subsequent messages are broadcast on any mutation.

```json
{
  "nodes":  [ ...NodeAdminResponse... ],
  "claims": [ ...DeviceClaimResponse... ]
}
```

---

## Node lifecycle

```
POST /register (with claim)   →  ACTIVE
POST /register (no claim)     →  PENDING  (REQUIRE_PREAUTH=false only)
                                    │
                          PATCH /activate
                                    │
                                 ACTIVE
                                /      \
              clean shutdown  /        \ no heartbeat for 75s
                             /          \
                          OFFLINE     (excluded from peer lists)
                             \
                      heartbeat received
                             \
                           ACTIVE
                              │
                       DELETE /revoke
                              │
                           REVOKED  (excluded from peer lists, record kept)
                              │
                        DELETE /{id}
                              │
                          (deleted, VPN IP freed)
```
