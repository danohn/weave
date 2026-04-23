import { useState } from 'react'
import { useData } from '../contexts/DataContext'
import { useConfirm } from '../contexts/ConfirmContext'
import { useToast } from '../contexts/ToastContext'
import { api } from '../lib/api'
import { relTime } from '../lib/utils'
import CreateClaimModal from '../components/CreateClaimModal'
import RevealClaimModal from '../components/RevealClaimModal'

function Badge({ status }) {
  return (
    <span className={`badge badge-${status.toLowerCase()}`}>
      <span className="badge-pip" />
      {status}
    </span>
  )
}

export default function ClaimsView() {
  const { claims, nodes } = useData()
  const confirm = useConfirm()
  const toast   = useToast()
  const [showCreate, setShowCreate] = useState(false)
  const [revealClaim, setRevealClaim] = useState(null)

  // Split into actionable pending and historical records
  const pending = claims.filter(c => c.status === 'UNCLAIMED')
  const history = claims.filter(c => c.status !== 'UNCLAIMED')

  const claimedNodeName = (nodeId) => {
    if (!nodeId) return null
    const node = nodes.find(n => n.id === nodeId)
    return node?.name ?? nodeId.slice(0, 8) + '…'
  }

  const doRevoke = (claim) => confirm(
    'Revoke claim',
    `Revoke claim <strong>${claim.device_id}</strong>? It will no longer be usable for node enrollment.`,
    async () => {
      try { await api.post(`/api/v1/auth/claims/${claim.id}/revoke`); toast(`Claim "${claim.device_id}" revoked`) }
      catch (err) { toast(err.message, 'err') }
    }
  )

  const doDelete = (claim) => confirm(
    'Delete claim',
    `Delete claim <strong>${claim.device_id}</strong>? Its bootstrap token will stop working immediately.`,
    async () => {
      try { await api.delete(`/api/v1/auth/claims/${claim.id}`); toast(`Claim "${claim.device_id}" deleted`) }
      catch (err) { toast(err.message, 'err') }
    }
  )

  return (
    <>
      {/* ── Pending (actionable) ──────────────────────────────── */}
      <div className="section-head">
        <div className="section-title">Pending Claims</div>
        <button className="btn btn-ghost" onClick={() => setShowCreate(true)}>+ New Claim</button>
      </div>

      <div className="table-shell" style={{ marginBottom: 28 }}>
        <table>
          <thead>
            <tr>
              <th>Device ID</th>
              <th>Expected Name</th>
              <th>Site</th>
              <th>Claim Token</th>
              <th>Created</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {pending.length === 0 ? (
              <tr><td colSpan={6}>
                <div className="placeholder">
                  No pending claims — create one to enroll a node with a one-time bootstrap token
                </div>
              </td></tr>
            ) : pending.map(c => (
              <tr key={c.id}>
                <td className="td-name">{c.device_id}</td>
                <td>{c.expected_name || <span className="td-empty">Any</span>}</td>
                <td>{c.site_name    || <span className="td-empty">—</span>}</td>
                <td>
                  <span className="token-str">{c.token_prefix}••••••••••••••••</span>
                </td>
                <td className="ts-warm">{relTime(c.created_at)}</td>
                <td className="td-actions">
                  <button className="row-btn" onClick={() => doRevoke(c)}>Revoke</button>
                  <button className="row-btn" onClick={() => doDelete(c)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ── History (audit) ───────────────────────────────────── */}
      <div className="section-head">
        <div className="section-title">Enrollment History</div>
      </div>

      <div className="table-shell">
        <table>
          <thead>
            <tr>
              <th>Device ID</th>
              <th>Expected Name</th>
              <th>Site</th>
              <th>Status</th>
              <th>Claimed by</th>
              <th>Created</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {history.length === 0 ? (
              <tr><td colSpan={7}>
                <div className="placeholder">No enrollment history yet</div>
              </td></tr>
            ) : history.map(c => (
              <tr key={c.id}>
                <td className="td-name">{c.device_id}</td>
                <td>{c.expected_name || <span className="td-empty">Any</span>}</td>
                <td>{c.site_name    || <span className="td-empty">—</span>}</td>
                <td>
                  <Badge status={c.status} />
                </td>
                <td>
                  {claimedNodeName(c.claimed_by_node_id) || <span className="td-empty">—</span>}
                </td>
                <td className="ts-warm">{relTime(c.created_at)}</td>
                <td className="td-actions">
                  {c.status === 'REVOKED' && (
                    <button className="row-btn" onClick={() => doDelete(c)}>Delete</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showCreate && (
        <CreateClaimModal
          onClose={() => setShowCreate(false)}
          onCreated={(data) => { setShowCreate(false); setRevealClaim(data) }}
        />
      )}

      {revealClaim && (
        <RevealClaimModal claim={revealClaim} onClose={() => setRevealClaim(null)} />
      )}
    </>
  )
}
