// ── State ──────────────────────────────────────────────────────────────────
const state = {
  nodes: [],
  claims: [],
  bgp: {},        // keyed by vpn_ip → { state, uptime, prefixes_received }
  connected: false,
  lastUpdated: null,
};

// ── DOM ────────────────────────────────────────────────────────────────────
const get = id => document.getElementById(id);

const loginView    = get('login-view');
const mainView     = get('main-view');
const ssoBtn       = get('sso-btn');
const logoutBtn    = get('logout-btn');
const currentUser  = get('current-user');
const hdot         = get('hdot');
const hlabel       = get('hlabel');
const tbody        = get('tbody');
const claimsBody   = get('claims-tbody');
const updatedAt    = get('updated-at');
const newClaimBtn  = get('new-claim-btn');

// Confirm modal
const overlay  = get('overlay');
const mTitle   = get('m-title');
const mDesc    = get('m-desc');
const mOk      = get('m-ok');
const mCancel  = get('m-cancel');

// New-claim modal
const claimOverlay         = get('claim-overlay');
const claimDeviceIdInp     = get('claim-device-id-inp');
const claimExpectedNameInp = get('claim-expected-name-inp');
const claimSiteNameInp     = get('claim-site-name-inp');
const claimSiteSubnetInp   = get('claim-site-subnet-inp');
const claimCancelBtn       = get('claim-cancel');
const claimCreateBtn       = get('claim-create');

// Reveal-token modal
const revealOverlay  = get('reveal-overlay');
const revealTokenInp = get('reveal-token-inp');
const revealCopyBtn  = get('reveal-copy-btn');
const revealCommandInp = get('reveal-command-inp');
const revealCommandCopyBtn = get('reveal-command-copy-btn');
const revealDoneBtn  = get('reveal-done-btn');

// ── View helpers ───────────────────────────────────────────────────────────
function showLogin() {
  loginView.classList.remove('hidden');
  mainView.classList.add('hidden');
  logoutBtn.classList.add('hidden');
  currentUser.textContent = '';
  setHealth(false, 'Signed out');
  closeWebSocket();
}

function showApp(username) {
  loginView.classList.add('hidden');
  mainView.classList.remove('hidden');
  logoutBtn.classList.remove('hidden');
  currentUser.textContent = username;
}

// ── API helpers ────────────────────────────────────────────────────────────
async function api(path, opts = {}) {
  const res = await fetch(path, {
    credentials: 'same-origin',
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      ...(opts.headers || {}),
    },
  });
  if (res.status === 401) {
    showLogin();
    return null;
  }
  if (!res.ok) {
    const txt = await res.text().catch(() => '');
    let msg = `${res.status} ${res.statusText}`;
    try { msg += ': ' + JSON.parse(txt).detail; } catch { if (txt) msg += ': ' + txt; }
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

const fetchHealth    = ()    => api('/health');
const fetchNodes     = ()    => api('/api/v1/nodes/');
const fetchClaims    = ()    => api('/api/v1/auth/claims');
const fetchBgpStatus = ()    => api('/api/v1/bgp/status');
const activateNode  = id             => api(`/api/v1/nodes/${id}/activate`, { method: 'PATCH' });
const revokeNode    = id             => api(`/api/v1/nodes/${id}/revoke`,   { method: 'DELETE' });
const deleteNode    = id             => api(`/api/v1/nodes/${id}`,          { method: 'DELETE' });
const updateSubnet  = (id, subnet)   => api(`/api/v1/nodes/${id}`,          { method: 'PATCH', body: JSON.stringify({ site_subnet: subnet || null }) });
const createClaim   = payload         => api('/api/v1/auth/claims', { method: 'POST', body: JSON.stringify(payload) });
const revokeClaim   = id              => api(`/api/v1/auth/claims/${id}/revoke`, { method: 'POST' });
const deleteClaim   = id              => api(`/api/v1/auth/claims/${id}`, { method: 'DELETE' });

function buildInstallCommand(claim) {
  const controllerUrl = location.origin;
  const lines = [
    'REF=main',
    `curl -fsSL "https://raw.githubusercontent.com/danohn/weave/\${REF}/agent/install.sh" \\`,
    '  | bash -s -- \\',
    `      --controller-url ${shellEscape(controllerUrl)} \\`,
    `      --claim-token ${shellEscape(claim.token)} \\`,
  ];
  if (claim.expected_name) {
    lines.push(`      --node-name ${shellEscape(claim.expected_name)} \\`);
  }
  lines.push('      --repo-ref "${REF}"');
  return lines.join('\n');
}

// ── WebSocket ──────────────────────────────────────────────────────────────
let ws = null;
let wsReconnectTimer = null;

function openWebSocket() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;

  const wsUrl = location.origin.replace(/^http/, 'ws') + '/ws';
  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    clearTimeout(wsReconnectTimer);
    clearInterval(state.timer);
    state.timer = null;
  };

  ws.onmessage = ev => {
    const data = JSON.parse(ev.data);
    applyState(data.nodes, data.claims || []);
  };

  ws.onclose = ev => {
    ws = null;
    if (ev.code === 4001) {
      showLogin();
      return;
    }
    setHealth(false, 'Reconnecting…');
    wsReconnectTimer = setTimeout(openWebSocket, 5_000);
  };
}

function closeWebSocket() {
  clearTimeout(wsReconnectTimer);
  if (ws) {
    ws.onclose = null;
    ws.close();
    ws = null;
  }
}

// ── BGP status polling (independent of node list) ─────────────────────────
let bgpPollTimer = null;

async function pollBgp() {
  if (!state.connected) return;
  try {
    state.bgp = await fetchBgpStatus();
    if (state.bgp) renderNodes();
  } catch { /* non-fatal — BGP column shows unknown */ }
}

function startBgpPoll() {
  stopBgpPoll();
  pollBgp();
  bgpPollTimer = setInterval(pollBgp, 5_000);
}

function stopBgpPoll() {
  clearInterval(bgpPollTimer);
  bgpPollTimer = null;
}

// ── Apply state from WS message or HTTP fetch ──────────────────────────────
function applyState(nodes, claims) {
  const wasConnected = state.connected;
  state.nodes       = nodes;
  state.claims      = claims;
  state.connected   = true;
  state.lastUpdated = new Date();
  setHealth(true, `${nodes.length} node${nodes.length !== 1 ? 's' : ''}`);
  newClaimBtn.disabled = false;
  renderStats();
  renderNodes();
  renderClaims();
  renderTimestamp();
  if (!wasConnected) startBgpPoll();
}

// ── HTTP refresh (used on connect and as WS fallback) ──────────────────────
async function refresh() {
  try {
    const [health, nodes, claims] = await Promise.all([fetchHealth(), fetchNodes(), fetchClaims()]);
    if (!nodes || !claims) return; // 401 already handled in api()
    applyState(nodes, claims);
    setHealth(true, `${health.node_count} node${health.node_count !== 1 ? 's' : ''}`);
  } catch (err) {
    state.connected = false;
    newClaimBtn.disabled = true;
    setHealth(false, 'Error');
    toast(err.message, 'err');
  }
}

// ── Rendering ──────────────────────────────────────────────────────────────
function setHealth(ok, text) {
  hdot.className = `health-dot ${ok ? 'ok' : 'error'}`;
  hlabel.textContent = text;
}

function renderStats() {
  const n = state.nodes;
  get('s-total').textContent   = n.length;
  get('s-active').textContent  = n.filter(x => x.status === 'ACTIVE').length;
  get('s-pending').textContent = n.filter(x => x.status === 'PENDING').length;
  get('s-offline').textContent = n.filter(x => x.status === 'OFFLINE').length;
  get('s-revoked').textContent = n.filter(x => x.status === 'REVOKED').length;
}

function renderTimestamp() {
  if (!state.lastUpdated) return;
  updatedAt.textContent = `Updated ${state.lastUpdated.toLocaleTimeString()}`;
}

const STATUS_ORDER = { ACTIVE: 0, PENDING: 1, OFFLINE: 2, REVOKED: 3 };

function renderNodes() {
  if (!state.nodes.length) {
    tbody.innerHTML = `<tr><td colspan="9"><div class="placeholder">No nodes registered yet</div></td></tr>`;
    return;
  }

  const sorted = [...state.nodes].sort(
    (a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9)
  );

  tbody.innerHTML = sorted.map(n => {
    const tsClass = tsAgeClass(n.last_seen);

    const activateBtn = n.status === 'PENDING'
      ? `<button class="row-btn activate-btn" onclick="doActivate('${e(n.id)}','${e(n.name)}')">Activate</button>`
      : '';
    const revokeBtn = n.status !== 'REVOKED'
      ? `<button class="row-btn" onclick="doRevoke('${e(n.id)}','${e(n.name)}')">Revoke</button>`
      : '';
    const deleteBtn = n.status === 'REVOKED'
      ? `<button class="row-btn" onclick="doDelete('${e(n.id)}','${e(n.name)}')">Delete</button>`
      : '';

    const bgpInfo  = state.bgp[n.vpn_ip];
    const bgpCell  = bgpBadge(bgpInfo);

    const advertised = bgpInfo && bgpInfo.prefixes_received > 0;
    const reachDot = n.site_subnet
      ? `<span class="reach-dot ${advertised ? 'reach-ok' : 'reach-no'}" title="${advertised ? 'Route advertised' : 'Not advertising'}"></span>`
      : '';

    const subnetCell = n.site_subnet
      ? `${reachDot}<span class="subnet-pill">${e(n.site_subnet)}</span> <button class="edit-btn" onclick="doEditSubnet('${e(n.id)}','${e(n.name)}','${e(n.site_subnet || '')}')">Edit</button>`
      : `<span class="td-empty">—</span> <button class="edit-btn" onclick="doEditSubnet('${e(n.id)}','${e(n.name)}','')">Set</button>`;

    return `<tr>
      <td class="td-name">${e(n.name)}</td>
      <td>${badge(n.status)}</td>
      <td>${bgpCell}</td>
      <td class="td-mono">${e(n.vpn_ip)}</td>
      <td class="td-mono">${e(n.endpoint_ip)}:${e(String(n.endpoint_port))}</td>
      <td class="td-subnet">${subnetCell}</td>
      <td class="${tsClass}">${relTime(n.last_seen)}</td>
      <td class="td-actions">${activateBtn}${revokeBtn}${deleteBtn}</td>
    </tr>`;
  }).join('');
}

function renderClaims() {
  if (!state.claims.length) {
    claimsBody.innerHTML = `<tr><td colspan="7"><div class="placeholder">No claims yet — create one to enroll a node with a one-time bootstrap token</div></td></tr>`;
    return;
  }

  claimsBody.innerHTML = state.claims.map(c => {
    const claimedNode = c.claimed_by_node_id
      ? (state.nodes.find(n => n.id === c.claimed_by_node_id)?.name ?? c.claimed_by_node_id.slice(0, 8) + '…')
      : null;

    let statusBadge = badge(c.status);
    if (claimedNode && (c.status === 'CLAIMED' || c.status === 'ACTIVE')) {
      statusBadge += ` <span class="claim-meta">by ${e(claimedNode)}</span>`;
    }

    const actions = [];
    if (c.status !== 'REVOKED' && c.status !== 'ACTIVE') {
      actions.push(`<button class="row-btn" onclick="doRevokeClaim('${e(c.id)}','${e(c.device_id)}')">Revoke</button>`);
    }
    if (c.status === 'UNCLAIMED') {
      actions.push(`<button class="row-btn" onclick="doDeleteClaim('${e(c.id)}','${e(c.device_id)}')">Delete</button>`);
    }

    return `<tr>
      <td class="td-name">${e(c.device_id)}</td>
      <td>${c.expected_name ? e(c.expected_name) : '<span class="td-empty">Any</span>'}</td>
      <td>${c.site_name ? e(c.site_name) : '<span class="td-empty">—</span>'}</td>
      <td>
        <span class="token-str">${e(c.token_prefix)}••••••••••••••••</span>
      </td>
      <td class="ts-warm">${relTime(c.created_at)}</td>
      <td>${statusBadge}</td>
      <td class="td-actions">${actions.join('')}</td>
    </tr>`;
  }).join('');
}

function badge(status) {
  const cls = 'badge-' + status.toLowerCase();
  return `<span class="badge ${cls}"><span class="badge-pip"></span>${e(status)}</span>`;
}

function bgpBadge(info) {
  if (!info) return `<span class="badge badge-bgp-unknown"><span class="badge-pip"></span>—</span>`;
  const s = info.state;
  let cls = 'badge-bgp-unknown';
  if (s === 'Established') cls = 'badge-bgp-up';
  else if (s === 'Active' || s === 'Connect') cls = 'badge-bgp-pending';
  else if (s === 'Idle' || s === 'OpenSent' || s === 'OpenConfirm') cls = 'badge-bgp-down';
  const label = s === 'Established' ? `${s} (${info.uptime})` : s;
  return `<span class="badge ${cls}"><span class="badge-pip"></span>${e(label)}</span>`;
}

// ── Helpers ────────────────────────────────────────────────────────────────
function e(str) {
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function shellEscape(str) {
  return `'${String(str).replace(/'/g, `'\"'\"'`)}'`;
}

function relTime(iso) {
  if (!iso) return '—';
  const sec = (Date.now() - new Date(iso.endsWith('Z') ? iso : iso + 'Z')) / 1000;
  if (sec < 60)    return `${Math.round(sec)}s ago`;
  if (sec < 3600)  return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

function tsAgeClass(iso) {
  if (!iso) return '';
  const sec = (Date.now() - new Date(iso.endsWith('Z') ? iso : iso + 'Z')) / 1000;
  if (sec < 45)  return 'ts-fresh';
  if (sec < 180) return 'ts-warm';
  return 'ts-stale';
}

// ── Node actions ───────────────────────────────────────────────────────────
function doActivate(id, name) {
  confirm(
    'Activate node',
    `Activate <strong>${e(name)}</strong>? It will join the mesh and become visible to all peers.`,
    async () => {
      try { await activateNode(id); toast(`${name} activated`); }
      catch (err) { toast(err.message, 'err'); }
    }
  );
}

function doRevoke(id, name) {
  confirm(
    'Revoke node',
    `Revoke <strong>${e(name)}</strong>? It will be excluded from all peer lists. This cannot be undone.`,
    async () => {
      try { await revokeNode(id); toast(`${name} revoked`); }
      catch (err) { toast(err.message, 'err'); }
    }
  );
}

function doDelete(id, name) {
  confirm(
    'Delete node',
    `Permanently delete <strong>${e(name)}</strong>? The record will be removed and its VPN IP freed for reuse.`,
    async () => {
      try { await deleteNode(id); toast(`${name} deleted`); }
      catch (err) { toast(err.message, 'err'); }
    }
  );
}

// ── Subnet edit ────────────────────────────────────────────────────────────
const subnetOverlay   = get('subnet-overlay');
const subnetNodeName  = get('subnet-node-name');
const subnetInp       = get('subnet-inp');
const subnetCancelBtn = get('subnet-cancel');
const subnetSaveBtn   = get('subnet-save');

let _subnetNodeId = null;

function doEditSubnet(id, name, current) {
  _subnetNodeId = id;
  subnetNodeName.textContent = name;
  subnetInp.value = current || '';
  subnetOverlay.classList.add('open');
  setTimeout(() => subnetInp.focus(), 50);
}

function closeSubnetModal() {
  subnetOverlay.classList.remove('open');
  _subnetNodeId = null;
}

subnetCancelBtn.addEventListener('click', closeSubnetModal);
subnetOverlay.addEventListener('click', ev => { if (ev.target === subnetOverlay) closeSubnetModal(); });
subnetInp.addEventListener('keydown', ev => { if (ev.key === 'Enter') subnetSaveBtn.click(); });

subnetSaveBtn.addEventListener('click', async () => {
  if (!_subnetNodeId) return;
  const subnet = subnetInp.value.trim();
  subnetSaveBtn.disabled = true;
  try {
    await updateSubnet(_subnetNodeId, subnet);
    closeSubnetModal();
    toast(subnet ? `Subnet set to ${subnet}` : 'Subnet cleared');
  } catch (err) {
    toast(err.message, 'err');
  } finally {
    subnetSaveBtn.disabled = false;
  }
});

// ── Claim actions ──────────────────────────────────────────────────────────
function doRevokeClaim(id, deviceId) {
  confirm(
    'Revoke claim',
    `Revoke claim <strong>${e(deviceId)}</strong>? It will no longer be usable for node enrollment.`,
    async () => {
      try { await revokeClaim(id); toast(`Claim "${deviceId}" revoked`); }
      catch (err) { toast(err.message, 'err'); }
    }
  );
}

function doDeleteClaim(id, deviceId) {
  confirm(
    'Delete claim',
    `Delete claim <strong>${e(deviceId)}</strong>? Its bootstrap token will stop working immediately.`,
    async () => {
      try { await deleteClaim(id); toast(`Claim "${deviceId}" deleted`); }
      catch (err) { toast(err.message, 'err'); }
    }
  );
}

// ── Confirm modal ──────────────────────────────────────────────────────────
let _confirmCb = null;

function confirm(title, desc, cb) {
  mTitle.textContent = title;
  mDesc.innerHTML = desc;
  _confirmCb = cb;
  overlay.classList.add('open');
}

function closeModal() { overlay.classList.remove('open'); _confirmCb = null; }

mOk.addEventListener('click', async () => { const cb = _confirmCb; closeModal(); if (cb) await cb(); });
mCancel.addEventListener('click', closeModal);
overlay.addEventListener('click', ev => { if (ev.target === overlay) closeModal(); });

// ── New-claim modal ────────────────────────────────────────────────────────
newClaimBtn.addEventListener('click', () => {
  claimDeviceIdInp.value = '';
  claimExpectedNameInp.value = '';
  claimSiteNameInp.value = '';
  claimSiteSubnetInp.value = '';
  claimOverlay.classList.add('open');
  setTimeout(() => claimDeviceIdInp.focus(), 50);
});

function closeClaimModal() {
  claimOverlay.classList.remove('open');
}

claimCancelBtn.addEventListener('click', closeClaimModal);
claimOverlay.addEventListener('click', ev => { if (ev.target === claimOverlay) closeClaimModal(); });
[claimDeviceIdInp, claimExpectedNameInp, claimSiteNameInp, claimSiteSubnetInp].forEach(inp => {
  inp.addEventListener('keydown', ev => { if (ev.key === 'Enter') claimCreateBtn.click(); });
});

claimCreateBtn.addEventListener('click', async () => {
  const deviceId = claimDeviceIdInp.value.trim();
  if (!deviceId) { claimDeviceIdInp.focus(); return; }
  claimCreateBtn.disabled = true;
  try {
    const data = await createClaim({
      device_id: deviceId,
      expected_name: claimExpectedNameInp.value.trim() || null,
      site_name: claimSiteNameInp.value.trim() || null,
      site_subnet: claimSiteSubnetInp.value.trim() || null,
    });
    if (!data) return;
    closeClaimModal();
    revealTokenInp.value = data.token;
    revealCommandInp.value = buildInstallCommand(data);
    revealOverlay.classList.add('open');
    setTimeout(() => revealTokenInp.select(), 50);
  } catch (err) {
    toast(err.message, 'err');
  } finally {
    claimCreateBtn.disabled = false;
  }
});

// ── Reveal-token modal ─────────────────────────────────────────────────────
revealCopyBtn.addEventListener('click', () => {
  navigator.clipboard.writeText(revealTokenInp.value)
    .then(() => toast('Token copied'))
    .catch(() => { revealTokenInp.select(); toast('Select and copy manually', 'err'); });
});

revealCommandCopyBtn.addEventListener('click', () => {
  navigator.clipboard.writeText(revealCommandInp.value)
    .then(() => toast('Install command copied'))
    .catch(() => { revealCommandInp.select(); toast('Select and copy manually', 'err'); });
});

revealDoneBtn.addEventListener('click', () => {
  revealOverlay.classList.remove('open');
  revealTokenInp.value = '';
  revealCommandInp.value = '';
});

// ── Toast ──────────────────────────────────────────────────────────────────
function toast(msg, type = 'ok') {
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  get('toasts').appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ── Auth events ────────────────────────────────────────────────────────────
ssoBtn.addEventListener('click', () => { window.location.href = '/auth/login'; });

logoutBtn.addEventListener('click', async () => {
  await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin' });
  window.location.href = '/';
});

// ── Boot ───────────────────────────────────────────────────────────────────
async function boot() {
  const res = await fetch('/auth/me', { credentials: 'same-origin' });
  if (!res.ok) {
    showLogin();
    return;
  }
  const user = await res.json();
  showApp(user.username);
  await refresh();
  openWebSocket();
}

boot();

// Tick relative timestamps every 10s without any network call
setInterval(() => {
  if (state.nodes.length)  renderNodes();
  if (state.claims.length) renderClaims();
  if (state.lastUpdated)   renderTimestamp();
}, 10_000);
