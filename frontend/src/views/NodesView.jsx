import { useState } from 'react'
import { useData } from '../contexts/DataContext'
import { useConfirm } from '../contexts/ConfirmContext'
import { useToast } from '../contexts/ToastContext'
import { api } from '../lib/api'
import { relTime, tsAgeClass, bgpStateClass } from '../lib/utils'
import EditSubnetModal from '../components/EditSubnetModal'

const STATUS_ORDER = { ACTIVE: 0, PENDING: 1, OFFLINE: 2, REVOKED: 3 }

function Badge({ status }) {
  return (
    <span className={`badge badge-${status.toLowerCase()}`}>
      <span className="badge-pip" />
      {status}
    </span>
  )
}

function BgpBadge({ info }) {
  if (!info) {
    return <span className="badge badge-bgp-unknown"><span className="badge-pip" />—</span>
  }
  const cls   = bgpStateClass(info.state)
  const label = info.state === 'Established'
    ? `${info.state} (${info.uptime})`
    : (info.state || '—')
  return <span className={`badge ${cls}`}><span className="badge-pip" />{label}</span>
}

function TransportBadge({ transport }) {
  if (!transport) {
    return <span className="badge badge-bgp-unknown"><span className="badge-pip" />—</span>
  }
  const label = `${transport.kind} / ${transport.status}`
  const cls = transport.status === 'HEALTHY'
    ? 'badge-bgp-established'
    : transport.status === 'DEGRADED'
      ? 'badge-bgp-active'
      : 'badge-bgp-unknown'
  return <span className={`badge ${cls}`}><span className="badge-pip" />{label}</span>
}

export default function NodesView() {
  const { nodes, bgp, lastUpdated } = useData()
  const confirm = useConfirm()
  const toast   = useToast()
  const [subnetNode, setSubnetNode] = useState(null)

  const sorted = [...nodes].sort(
    (a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9)
  )

  const doActivate = (node) => confirm(
    'Activate node',
    `Activate <strong>${node.name}</strong>? It will join the mesh and become visible to all peers.`,
    async () => {
      try { await api.patch(`/api/v1/nodes/${node.id}/activate`); toast(`${node.name} activated`) }
      catch (err) { toast(err.message, 'err') }
    }
  )

  const doRevoke = (node) => confirm(
    'Revoke node',
    `Revoke <strong>${node.name}</strong>? It will be excluded from all peer lists. This cannot be undone.`,
    async () => {
      try { await api.delete(`/api/v1/nodes/${node.id}/revoke`); toast(`${node.name} revoked`) }
      catch (err) { toast(err.message, 'err') }
    }
  )

  const doDelete = (node) => confirm(
    'Delete node',
    `Permanently delete <strong>${node.name}</strong>? The record will be removed and its VPN IP freed for reuse.`,
    async () => {
      try { await api.delete(`/api/v1/nodes/${node.id}`); toast(`${node.name} deleted`) }
      catch (err) { toast(err.message, 'err') }
    }
  )

  const counts = {
    total:   nodes.length,
    active:  nodes.filter(n => n.status === 'ACTIVE').length,
    pending: nodes.filter(n => n.status === 'PENDING').length,
    offline: nodes.filter(n => n.status === 'OFFLINE').length,
    revoked: nodes.filter(n => n.status === 'REVOKED').length,
  }

  return (
    <>
      <div className="stats">
        <div className="stat-card">
          <div className="stat-label">Total</div>
          <div className="stat-num">{counts.total || '—'}</div>
        </div>
        <div className="stat-card live">
          <div className="stat-label">Active</div>
          <div className="stat-num">{counts.active || '—'}</div>
        </div>
        <div className="stat-card muted">
          <div className="stat-label">Pending</div>
          <div className="stat-num">{counts.pending || '—'}</div>
        </div>
        <div className="stat-card dim">
          <div className="stat-label">Offline</div>
          <div className="stat-num">{counts.offline || '—'}</div>
        </div>
        <div className="stat-card faded">
          <div className="stat-label">Revoked</div>
          <div className="stat-num">{counts.revoked || '—'}</div>
        </div>
      </div>

      <div className="section-head">
        <div className="section-title">Nodes</div>
        <div className="section-meta">
          {lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString()}` : ''}
        </div>
      </div>

      <div className="table-shell">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>BGP</th>
              <th>VPN IP</th>
              <th>Active Overlay</th>
              <th>Site</th>
              <th>Endpoint</th>
              <th>Prefix</th>
              <th>Transport</th>
              <th>Last seen</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr><td colSpan={11}><div className="placeholder">No nodes registered yet</div></td></tr>
            ) : sorted.map(n => {
              const bgpKey     = n.active_overlay_vpn_ip || n.vpn_ip
              const bgpInfo    = bgp[bgpKey]
              const advertised = bgpInfo && bgpInfo.prefixes_received > 0
              return (
                <tr key={n.id}>
                  <td className="td-name">{n.name}</td>
                  <td><Badge status={n.status} /></td>
                  <td><BgpBadge info={bgpInfo} /></td>
                  <td className="td-mono">{n.vpn_ip}</td>
                  <td className="td-mono">
                    {n.active_overlay_vpn_ip || <span className="td-empty">—</span>}
                    {n.active_overlay_interface && (
                      <div className="table-subtext">{n.active_overlay_interface}</div>
                    )}
                  </td>
                  <td>
                    {n.site ? (
                      <>
                        <div>{n.site.name}</div>
                        <div className="table-subtext">{n.site.prefixes?.length || 0} prefix{(n.site.prefixes?.length || 0) === 1 ? '' : 'es'}</div>
                      </>
                    ) : <span className="td-empty">—</span>}
                  </td>
                  <td className="td-mono">{n.endpoint_ip}:{n.endpoint_port}</td>
                  <td className="td-subnet">
                    {n.site_subnet ? (
                      <>
                        <span
                          className={`reach-dot ${advertised ? 'reach-ok' : 'reach-no'}`}
                          title={advertised ? 'Route advertised' : 'Not advertising'}
                        />
                        <span className="subnet-pill">{n.site_subnet}</span>{' '}
                        <button className="edit-btn" onClick={() => setSubnetNode(n)}>Edit</button>
                      </>
                    ) : (
                      <>
                        <span className="td-empty">—</span>{' '}
                        <button className="edit-btn" onClick={() => setSubnetNode(n)}>Set</button>
                      </>
                    )}
                  </td>
                  <td>
                    <TransportBadge transport={n.active_transport} />
                    {n.active_transport && (
                      <div className="table-subtext">
                        {n.active_transport.name}
                        {n.active_transport.rtt_ms != null ? ` · ${n.active_transport.rtt_ms}ms` : ''}
                        {n.active_transport.loss_pct != null ? ` · ${n.active_transport.loss_pct}% loss` : ''}
                      </div>
                    )}
                  </td>
                  <td className={tsAgeClass(n.last_seen)}>{relTime(n.last_seen)}</td>
                  <td className="td-actions">
                    {n.status === 'PENDING' && (
                      <button className="row-btn activate-btn" onClick={() => doActivate(n)}>Activate</button>
                    )}
                    {n.status !== 'REVOKED' && (
                      <button className="row-btn" onClick={() => doRevoke(n)}>Revoke</button>
                    )}
                    {n.status === 'REVOKED' && (
                      <button className="row-btn" onClick={() => doDelete(n)}>Delete</button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {subnetNode && (
        <EditSubnetModal node={subnetNode} onClose={() => setSubnetNode(null)} />
      )}
    </>
  )
}
