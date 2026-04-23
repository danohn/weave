import { useData } from '../contexts/DataContext'
import { bgpStateClass } from '../lib/utils'

function BgpBadge({ state }) {
  const cls = bgpStateClass(state)
  return (
    <span className={`badge ${cls}`}>
      <span className="badge-pip" />
      {state || '—'}
    </span>
  )
}

export default function BgpView() {
  const { bgp, nodes } = useData()

  const peerContext = (vpnIp) => {
    for (const node of nodes) {
      for (const link of node.transport_links || []) {
        if (link.overlay_vpn_ip === vpnIp) {
          return { name: node.name, transport: link.kind }
        }
      }
      if (node.vpn_ip === vpnIp) {
        return { name: node.name, transport: null }
      }
    }
    return { name: vpnIp, transport: null }
  }

  const peers = Object.entries(bgp)

  return (
    <>
      <div className="section-head">
        <div className="section-title">BGP Neighbors</div>
      </div>

      <div className="table-shell">
        <table>
          <thead>
            <tr>
              <th>Node</th>
              <th>Transport</th>
              <th>VPN IP</th>
              <th>State</th>
              <th>Uptime</th>
              <th>Prefixes Received</th>
            </tr>
          </thead>
          <tbody>
            {peers.length === 0 ? (
              <tr><td colSpan={6}>
                <div className="placeholder">
                  No BGP neighbors — FRR may not be running or no nodes are ACTIVE
                </div>
              </td></tr>
            ) : peers.map(([ip, info]) => {
              const ctx = peerContext(ip)
              return (
              <tr key={ip}>
                <td className="td-name">{ctx.name}</td>
                <td>{ctx.transport || '—'}</td>
                <td className="td-mono">{ip}</td>
                <td><BgpBadge state={info.state} /></td>
                <td className="td-mono">{info.uptime || '—'}</td>
                <td>{info.prefixes_received ?? 0}</td>
              </tr>
            )})}
          </tbody>
        </table>
      </div>
    </>
  )
}
