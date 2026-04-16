// ── State ──────────────────────────────────────────────────────────────────
const state = {
  url: '',
  token: '',
  nodes: [],
  tokens: [],
  connected: false,
  autoRefresh: true,
  timer: null,
  lastUpdated: null,
};

// ── DOM ────────────────────────────────────────────────────────────────────
const get = id => document.getElementById(id);

const inpUrl       = get('inp-url');
const inpToken     = get('inp-token');
const connectBtn   = get('connect-btn');
const refreshBtn   = get('refresh-btn');
const arPill       = get('ar-pill');
const arToggle     = get('ar-toggle');
const hdot         = get('hdot');
const hlabel       = get('hlabel');
const tbody        = get('tbody');
const tokensBody   = get('tokens-tbody');
const updatedAt    = get('updated-at');
const newTokenBtn  = get('new-token-btn');

// Confirm modal
const overlay  = get('overlay');
const mTitle   = get('m-title');
const mDesc    = get('m-desc');
const mOk      = get('m-ok');
const mCancel  = get('m-cancel');

// New-token modal
const tokenOverlay   = get('token-overlay');
const tokenLabelInp  = get('token-label-inp');
const tokenCancelBtn = get('token-cancel');
const tokenCreateBtn = get('token-create');

// ── Persistence ────────────────────────────────────────────────────────────
(function loadConfig() {
  const savedUrl   = localStorage.getItem('sdwan_url')   || '';
  const savedToken = localStorage.getItem('sdwan_token') || '';
  inpUrl.value   = savedUrl   || (location.hostname !== '' ? location.origin : '');
  inpToken.value = savedToken || '';
  if (savedUrl && savedToken) {
    state.url   = savedUrl.replace(/\/$/, '');
    state.token = savedToken;
  }
})();

function saveConfig() {
  localStorage.setItem('sdwan_url',   state.url);
  localStorage.setItem('sdwan_token', state.token);
}

// ── API helpers ────────────────────────────────────────────────────────────
async function api(path, opts = {}) {
  const res = await fetch(state.url + path, {
    ...opts,
    headers: {
      Authorization: `Bearer ${state.token}`,
      'Content-Type': 'application/json',
      ...(opts.headers || {}),
    },
  });
  if (!res.ok) {
    const txt = await res.text().catch(() => '');
    let msg = `${res.status} ${res.statusText}`;
    try { msg += ': ' + JSON.parse(txt).detail; } catch { if (txt) msg += ': ' + txt; }
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

const fetchHealth  = ()      => api('/health');
const fetchNodes   = ()      => api('/api/v1/nodes/');
const fetchTokens  = ()      => api('/api/v1/auth/tokens');
const activateNode = id      => api(`/api/v1/nodes/${id}/activate`, { method: 'PATCH' });
const revokeNode   = id      => api(`/api/v1/nodes/${id}/revoke`,   { method: 'DELETE' });
const deleteNode   = id      => api(`/api/v1/nodes/${id}`,          { method: 'DELETE' });
const createToken  = label   => api('/api/v1/auth/tokens', { method: 'POST', body: JSON.stringify({ label }) });
const deleteToken  = id      => api(`/api/v1/auth/tokens/${id}`,    { method: 'DELETE' });

// ── Refresh ────────────────────────────────────────────────────────────────
async function refresh() {
  if (!state.url || !state.token) return;
  refreshBtn.classList.add('spinning');
  try {
    const [health, nodes, tokens] = await Promise.all([fetchHealth(), fetchNodes(), fetchTokens()]);
    state.connected   = true;
    state.nodes       = nodes;
    state.tokens      = tokens;
    state.lastUpdated = new Date();
    setHealth(true, `${health.node_count} node${health.node_count !== 1 ? 's' : ''}`);
    newTokenBtn.disabled = false;
    renderStats();
    renderNodes();
    renderTokens();
    renderTimestamp();
  } catch (err) {
    state.connected = false;
    newTokenBtn.disabled = true;
    setHealth(false, 'Error');
    toast(err.message, 'err');
  } finally {
    refreshBtn.classList.remove('spinning');
  }
}

function setAutoRefresh(on) {
  state.autoRefresh = on;
  clearInterval(state.timer);
  state.timer = null;
  arPill.classList.toggle('on', on);
  if (on) state.timer = setInterval(refresh, 30_000);
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
}

function renderTimestamp() {
  if (!state.lastUpdated) return;
  updatedAt.textContent = `Updated ${state.lastUpdated.toLocaleTimeString()}`;
}

const STATUS_ORDER = { ACTIVE: 0, PENDING: 1, OFFLINE: 2, REVOKED: 3 };

function renderNodes() {
  if (!state.nodes.length) {
    tbody.innerHTML = `<tr><td colspan="8"><div class="placeholder">No nodes registered yet</div></td></tr>`;
    return;
  }

  const sorted = [...state.nodes].sort(
    (a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9)
  );

  tbody.innerHTML = sorted.map(n => {
    const natDetected = n.reflected_endpoint_ip && n.reflected_endpoint_ip !== n.endpoint_ip;
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

    return `<tr>
      <td class="td-name">${e(n.name)}</td>
      <td>${badge(n.status)}</td>
      <td class="td-mono">${e(n.vpn_ip)}</td>
      <td class="td-mono">${e(n.endpoint_ip)}:${e(String(n.endpoint_port))}</td>
      <td class="td-mono">${n.reflected_endpoint_ip
        ? e(n.reflected_endpoint_ip)
        : `<span style="color:var(--gray-300)">—</span>`}</td>
      <td>${natDetected
        ? `<span class="nat-pill">NAT</span>`
        : `<span style="color:var(--gray-300);font-size:12px">—</span>`}</td>
      <td class="${tsClass}">${relTime(n.last_seen)}</td>
      <td class="td-actions">${activateBtn}${revokeBtn}${deleteBtn}</td>
    </tr>`;
  }).join('');
}

function renderTokens() {
  if (!state.tokens.length) {
    tokensBody.innerHTML = `<tr><td colspan="5"><div class="placeholder">No tokens yet — create one to enable zero-touch provisioning</div></td></tr>`;
    return;
  }

  tokensBody.innerHTML = state.tokens.map(t => {
    const usedNode = t.used_by_node_id
      ? (state.nodes.find(n => n.id === t.used_by_node_id)?.name ?? t.used_by_node_id.slice(0, 8) + '…')
      : null;

    const statusBadge = usedNode
      ? `<span class="badge badge-used"><span class="badge-pip"></span>${e(usedNode)}</span>`
      : `<span class="badge badge-unused"><span class="badge-pip"></span>Unused</span>`;

    const deleteBtn = !t.used_at
      ? `<button class="row-btn" onclick="doDeleteToken('${e(t.id)}','${e(t.label)}')">Delete</button>`
      : '';

    return `<tr>
      <td class="td-name">${e(t.label)}</td>
      <td>
        <div class="token-cell">
          <span class="token-str" title="${e(t.token)}">${e(t.token)}</span>
          <button class="copy-btn" onclick="copyToken('${e(t.token)}')">Copy</button>
        </div>
      </td>
      <td class="ts-warm">${relTime(t.created_at)}</td>
      <td>${statusBadge}</td>
      <td class="td-actions">${deleteBtn}</td>
    </tr>`;
  }).join('');
}

function badge(status) {
  const cls = 'badge-' + status.toLowerCase();
  return `<span class="badge ${cls}"><span class="badge-pip"></span>${e(status)}</span>`;
}

// ── Helpers ────────────────────────────────────────────────────────────────
function e(str) {
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
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

async function copyToken(val) {
  try {
    await navigator.clipboard.writeText(val);
    toast('Token copied');
  } catch {
    toast('Copy failed — select manually', 'err');
  }
}

// ── Node actions ───────────────────────────────────────────────────────────
function doActivate(id, name) {
  confirm(
    'Activate node',
    `Activate <strong>${e(name)}</strong>? It will join the mesh and become visible to all peers.`,
    async () => {
      try { await activateNode(id); toast(`${name} activated`); await refresh(); }
      catch (err) { toast(err.message, 'err'); }
    }
  );
}

function doRevoke(id, name) {
  confirm(
    'Revoke node',
    `Revoke <strong>${e(name)}</strong>? It will be excluded from all peer lists. This cannot be undone.`,
    async () => {
      try { await revokeNode(id); toast(`${name} revoked`); await refresh(); }
      catch (err) { toast(err.message, 'err'); }
    }
  );
}

function doDelete(id, name) {
  confirm(
    'Delete node',
    `Permanently delete <strong>${e(name)}</strong>? The record will be removed and its VPN IP freed for reuse.`,
    async () => {
      try { await deleteNode(id); toast(`${name} deleted`); await refresh(); }
      catch (err) { toast(err.message, 'err'); }
    }
  );
}

// ── Token actions ──────────────────────────────────────────────────────────
function doDeleteToken(id, label) {
  confirm(
    'Delete token',
    `Delete token <strong>${e(label)}</strong>? It will no longer be valid for registration.`,
    async () => {
      try { await deleteToken(id); toast(`Token "${label}" deleted`); await refresh(); }
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

// ── New-token modal ────────────────────────────────────────────────────────
newTokenBtn.addEventListener('click', () => {
  tokenLabelInp.value = '';
  tokenOverlay.classList.add('open');
  setTimeout(() => tokenLabelInp.focus(), 50);
});

tokenCancelBtn.addEventListener('click', () => tokenOverlay.classList.remove('open'));
tokenOverlay.addEventListener('click', ev => { if (ev.target === tokenOverlay) tokenOverlay.classList.remove('open'); });
tokenLabelInp.addEventListener('keydown', ev => { if (ev.key === 'Enter') tokenCreateBtn.click(); });

tokenCreateBtn.addEventListener('click', async () => {
  const label = tokenLabelInp.value.trim();
  if (!label) { tokenLabelInp.focus(); return; }
  tokenCreateBtn.disabled = true;
  try {
    await createToken(label);
    tokenOverlay.classList.remove('open');
    toast(`Token "${label}" created`);
    await refresh();
  } catch (err) {
    toast(err.message, 'err');
  } finally {
    tokenCreateBtn.disabled = false;
  }
});

// ── Toast ──────────────────────────────────────────────────────────────────
function toast(msg, type = 'ok') {
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  get('toasts').appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ── Events ─────────────────────────────────────────────────────────────────
connectBtn.addEventListener('click', () => {
  const url   = inpUrl.value.trim().replace(/\/$/, '');
  const token = inpToken.value.trim();
  if (!url)   { toast('Enter a server URL', 'err'); return; }
  if (!token) { toast('Enter an admin token', 'err'); return; }
  state.url   = url;
  state.token = token;
  saveConfig();
  refresh();
});

inpUrl.addEventListener('keydown',   ev => ev.key === 'Enter' && connectBtn.click());
inpToken.addEventListener('keydown', ev => ev.key === 'Enter' && connectBtn.click());

refreshBtn.addEventListener('click', refresh);
arToggle.addEventListener('click', () => setAutoRefresh(!state.autoRefresh));

// ── Boot ───────────────────────────────────────────────────────────────────
setAutoRefresh(true);
if (state.url && state.token) refresh();

// Tick relative timestamps every 10s without a full API call
setInterval(() => {
  if (state.nodes.length)  { renderNodes(); renderTimestamp(); }
  if (state.tokens.length) { renderTokens(); }
}, 10_000);
