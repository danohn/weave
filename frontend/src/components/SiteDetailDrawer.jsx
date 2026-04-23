import { HealthBadge, BgpBadge, StatusBadge, TransportBadge } from './StatusPill'
import { relTime, summarizeSite, describeSiteHealth } from '../lib/utils'

function MetricCard({ label, value, tone = '' }) {
  return (
    <div className={`detail-metric ${tone}`}>
      <div className="detail-metric-label">{label}</div>
      <div className="detail-metric-value">{value}</div>
    </div>
  )
}

function TransportCard({ transport, bgp }) {
  return (
    <div className="transport-card">
      <div className="transport-card-head">
        <div>
          <div className="transport-card-title">
            <TransportBadge transport={transport} />
          </div>
          <div className="transport-card-meta">{transport.name}</div>
        </div>
        <BgpBadge info={bgp} compact />
      </div>
      <div className="detail-list">
        <div className="detail-row">
          <span>Underlay</span>
          <span className="td-mono">{transport.endpoint_ip}:{transport.endpoint_port}</span>
        </div>
        <div className="detail-row">
          <span>Overlay</span>
          <span className="td-mono">{transport.overlay_vpn_ip || '—'}</span>
        </div>
        <div className="detail-row">
          <span>Controller</span>
          <span className="td-mono">{transport.controller_vpn_ip || '—'}</span>
        </div>
        <div className="detail-row">
          <span>Interface</span>
          <span className="td-mono">{transport.interface_name || '—'}</span>
        </div>
        <div className="detail-row">
          <span>Latency</span>
          <span>{transport.rtt_ms != null ? `${transport.rtt_ms}ms` : 'Unmeasured'}</span>
        </div>
        <div className="detail-row">
          <span>Loss</span>
          <span>{transport.loss_pct != null ? `${transport.loss_pct}%` : 'Unmeasured'}</span>
        </div>
      </div>
    </div>
  )
}

export default function SiteDetailDrawer({ node, bgp, onClose }) {
  if (!node) return null

  const summary = summarizeSite(node, bgp)
  const bgpByIp = summary.bgpSessions.reduce((acc, session) => {
    acc[session.ip] = session.info
    return acc
  }, {})

  return (
    <div className="detail-drawer-backdrop" onClick={onClose}>
      <aside className="detail-drawer" onClick={(event) => event.stopPropagation()}>
        <div className="detail-drawer-head">
          <div>
            <div className="detail-kicker">Site Detail</div>
            <h2>{node.name}</h2>
            <p>{describeSiteHealth(summary)}</p>
          </div>
          <button className="detail-close" onClick={onClose}>Close</button>
        </div>

        <div className="detail-summary">
          <MetricCard label="Overall health" value={<HealthBadge health={summary.health} />} />
          <MetricCard label="Node status" value={<StatusBadge status={node.status} />} />
          <MetricCard label="Active transport" value={summary.activeTransport ? <TransportBadge transport={summary.activeTransport} /> : '—'} />
          <MetricCard label="Established BGP" value={`${summary.establishedSessions}/${summary.bgpSessions.length || 0}`} tone={summary.pendingSessions > 0 ? 'warn' : 'ok'} />
        </div>

        <section className="detail-section">
          <div className="detail-section-head">
            <h3>Identity</h3>
          </div>
          <div className="detail-list">
            <div className="detail-row"><span>Site</span><span>{node.site?.name || node.name}</span></div>
            <div className="detail-row"><span>Canonical VPN IP</span><span className="td-mono">{node.vpn_ip}</span></div>
            <div className="detail-row"><span>Active overlay</span><span className="td-mono">{node.active_overlay_vpn_ip || '—'}</span></div>
            <div className="detail-row"><span>Active interface</span><span className="td-mono">{node.active_overlay_interface || '—'}</span></div>
            <div className="detail-row"><span>Endpoint</span><span className="td-mono">{node.endpoint_ip}:{node.endpoint_port}</span></div>
            <div className="detail-row"><span>Last seen</span><span>{relTime(node.last_seen)}</span></div>
          </div>
        </section>

        <section className="detail-section">
          <div className="detail-section-head">
            <h3>Service Routes</h3>
          </div>
          <div className="detail-list">
            <div className="detail-row"><span>Advertised prefixes</span><span>{summary.prefixCount}</span></div>
            <div className="detail-row"><span>Site subnet</span><span className="td-mono">{node.site_subnet || '—'}</span></div>
            <div className="detail-row"><span>Policy count</span><span>{summary.policyCount}</span></div>
          </div>
        </section>

        <section className="detail-section">
          <div className="detail-section-head">
            <h3>Transports</h3>
          </div>
          <div className="transport-grid">
            {(node.transport_links || []).map((transport) => (
              <TransportCard
                key={transport.id || transport.overlay_vpn_ip || transport.name}
                transport={transport}
                bgp={bgpByIp[transport.overlay_vpn_ip]}
              />
            ))}
          </div>
        </section>

        <section className="detail-section">
          <div className="detail-section-head">
            <h3>Routing Sessions</h3>
          </div>
          <div className="table-shell detail-table">
            <table>
              <thead>
                <tr>
                  <th>Transport</th>
                  <th>Peer</th>
                  <th>State</th>
                  <th>Uptime</th>
                  <th>Prefixes</th>
                </tr>
              </thead>
              <tbody>
                {summary.bgpSessions.map((session) => (
                  <tr key={session.ip}>
                    <td>{session.transport || 'Identity'}</td>
                    <td className="td-mono">{session.ip}</td>
                    <td><BgpBadge info={session.info} compact /></td>
                    <td className="td-mono">{session.info?.uptime || '—'}</td>
                    <td>{session.info?.prefixes_received ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </aside>
    </div>
  )
}
