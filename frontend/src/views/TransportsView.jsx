import { useState } from 'react'
import { useData } from '../contexts/DataContext'
import { relTime, normalizeTransportStatus } from '../lib/utils'
import { BgpBadge, TransportBadge } from '../components/StatusPill'
import SiteDetailDrawer from '../components/SiteDetailDrawer'

export default function TransportsView() {
  const { transportInventory, bgp } = useData()
  const [selectedNode, setSelectedNode] = useState(null)

  return (
    <>
      <div className="section-head">
        <div>
          <div className="section-title">Transports</div>
          <div className="section-subtitle">Underlay bindings, overlay identities, and per-transport control-plane state.</div>
        </div>
      </div>

      <div className="table-shell">
        <table>
          <thead>
            <tr>
              <th>Site</th>
              <th>Transport</th>
              <th>Health</th>
              <th>Overlay</th>
              <th>Underlay</th>
              <th>Interface</th>
              <th>BGP</th>
              <th>Latency</th>
              <th>Loss</th>
            </tr>
          </thead>
          <tbody>
            {transportInventory.length === 0 ? (
              <tr><td colSpan={9}><div className="placeholder">No transport links available</div></td></tr>
            ) : transportInventory.map((transport) => (
              <tr key={transport.id || `${transport.node?.id}-${transport.kind}`}>
                <td className="td-name">
                  <button className="linkish-btn" onClick={() => setSelectedNode(transport.node)}>
                    {transport.node?.name || '—'}
                  </button>
                </td>
                <td>
                  <TransportBadge transport={transport} />
                  <div className="table-subtext">{transport.name}</div>
                </td>
                <td>{normalizeTransportStatus(transport.status)}</td>
                <td className="td-mono">{transport.overlay_vpn_ip || '—'}</td>
                <td className="td-mono">{transport.endpoint_ip}:{transport.endpoint_port}</td>
                <td className="td-mono">{transport.interface_name || '—'}</td>
                <td><BgpBadge info={transport.bgp} compact /></td>
                <td>{transport.rtt_ms != null ? `${transport.rtt_ms}ms` : 'Unmeasured'}</td>
                <td>{transport.loss_pct != null ? `${transport.loss_pct}%` : 'Unmeasured'}</td>
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
