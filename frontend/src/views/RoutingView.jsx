import { useState } from 'react'
import { useData } from '../contexts/DataContext'
import { BgpBadge } from '../components/StatusPill'
import SiteDetailDrawer from '../components/SiteDetailDrawer'

function SummaryCard({ label, value, note = '', tone = '' }) {
  return (
    <div className={`stat-card metric-card ${tone}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-num">{value}</div>
      {note ? <div className="metric-note">{note}</div> : null}
    </div>
  )
}

export default function RoutingView() {
  const { routingPeers, bgp } = useData()
  const [selectedNode, setSelectedNode] = useState(null)

  const established = routingPeers.filter((peer) => peer.info?.state === 'Established').length
  const pending = routingPeers.filter((peer) => ['Connect', 'Active'].includes(peer.info?.state)).length

  return (
    <>
      <div className="stats">
        <SummaryCard label="BGP peers" value={routingPeers.length || '—'} note={`${established} established`} />
        <SummaryCard label="Converging" value={pending || '—'} tone={pending > 0 ? 'muted' : ''} note="Sessions in Connect/Active" />
      </div>

      <div className="section-head">
        <div>
          <div className="section-title">Routing</div>
          <div className="section-subtitle">Control-plane sessions grouped by site and transport.</div>
        </div>
      </div>

      <div className="table-shell">
        <table>
          <thead>
            <tr>
              <th>Site</th>
              <th>Transport</th>
              <th>Peer IP</th>
              <th>State</th>
              <th>Uptime</th>
              <th>Prefixes received</th>
            </tr>
          </thead>
          <tbody>
            {routingPeers.length === 0 ? (
              <tr><td colSpan={6}><div className="placeholder">No routing peers discovered</div></td></tr>
            ) : routingPeers.map((peer) => (
              <tr key={peer.ip}>
                <td className="td-name">
                  {peer.node ? (
                    <button className="linkish-btn" onClick={() => setSelectedNode(peer.node)}>
                      {peer.node.name}
                    </button>
                  ) : peer.ip}
                </td>
                <td>{peer.transport?.kind || 'identity'}</td>
                <td className="td-mono">{peer.ip}</td>
                <td><BgpBadge info={peer.info} compact /></td>
                <td className="td-mono">{peer.info?.uptime || '—'}</td>
                <td>{peer.info?.prefixes_received ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selectedNode ? (
        <SiteDetailDrawer node={selectedNode} bgp={bgp} onClose={() => setSelectedNode(null)} />
      ) : null}
    </>
  )
}
