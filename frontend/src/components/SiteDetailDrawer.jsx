import { useMemo, useState } from 'react'
import { HealthBadge, BgpBadge, StatusBadge, TransportBadge } from './StatusPill'
import { relTime, summarizeSite, describeSiteHealth } from '../lib/utils'

const TABS = ['Overview', 'Transports', 'Routing', 'Policies', 'Events']

function MetricCard({ label, value, tone = '' }) {
  return (
    <div className={`detail-metric ${tone}`}>
      <div className="detail-metric-label">{label}</div>
      <div className="detail-metric-value">{value}</div>
    </div>
  )
}

function EventBadge({ severity }) {
  const normalized = String(severity || 'INFO').toUpperCase()
  const cls = normalized === 'CRITICAL'
    ? 'badge-bgp-down'
    : normalized === 'WARN'
      ? 'badge-bgp-pending'
      : 'badge-bgp-unknown'
  return <span className={`badge ${cls}`}><span className="badge-pip" />{normalized}</span>
}

function BfdBadge({ status }) {
  const normalized = String(status || 'UNKNOWN').toUpperCase()
  const cls = normalized === 'UP'
    ? 'badge-bgp-up'
    : normalized === 'DOWN'
      ? 'badge-bgp-down'
      : 'badge-bgp-unknown'
  const label = normalized === 'UNKNOWN' ? 'Unmeasured' : normalized
  return <span className={`badge ${cls}`}><span className="badge-pip" />{label}</span>
}

function PolicySummaryCard({ summary }) {
  return (
    <div className="detail-list">
      <div className="detail-row"><span>Scoped policies</span><span>{summary.total}</span></div>
      <div className="detail-row"><span>Preferred path active</span><span>{summary.preferred_active}</span></div>
      <div className="detail-row"><span>Fallback active</span><span>{summary.fallback_active}</span></div>
      <div className="detail-row"><span>Unresolved</span><span>{summary.unresolved}</span></div>
    </div>
  )
}

function ExceptionsPanel({ exceptions }) {
  if (!exceptions.length) {
    return <div className="detail-note ok">No active site exceptions.</div>
  }
  return (
    <ul className="detail-chip-list">
      {exceptions.map((exception, index) => (
        <li key={`${exception}-${index}`} className="detail-chip warn">{exception}</li>
      ))}
    </ul>
  )
}

function EventTimeline({ events }) {
  if (!events.length) {
    return <div className="detail-note">No recent site events.</div>
  }
  return (
    <div className="event-timeline">
      {events.map((event) => (
        <div key={event.id || `${event.kind}-${event.occurred_at}-${event.title}`} className="event-row">
          <div className="event-meta">
            <EventBadge severity={event.severity} />
            <span className="event-time">{relTime(event.occurred_at)}</span>
          </div>
          <div className="event-title">{event.title}</div>
          <div className="event-message">{event.message}</div>
        </div>
      ))}
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
        <div className="transport-card-badges">
          <BfdBadge status={transport.bfd_status || bgp?.bfd_status} />
          <BgpBadge info={bgp} compact />
        </div>
      </div>
      <div className="detail-list">
        <div className="detail-row">
          <span>Underlay</span>
          <span className="td-mono">{transport.interface_name || '—'} / {transport.endpoint_ip}:{transport.endpoint_port}</span>
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
          <span>Role</span>
          <span>{transport.is_active ? 'Active path' : 'Standby path'}</span>
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

function OverviewTab({ node, summary }) {
  const failovers = summary.recentEvents.filter((event) => event.kind === 'TRANSPORT_FAILOVER' || event.kind === 'POLICY_FALLBACK_ACTIVE')
  return (
    <>
      <section className="detail-section">
        <div className="detail-section-head">
          <h3>Identity</h3>
        </div>
        <div className="detail-list">
          <div className="detail-row"><span>Site</span><span>{node.site?.name || node.name}</span></div>
          <div className="detail-row"><span>Canonical VPN IP</span><span className="td-mono">{node.vpn_ip}</span></div>
          <div className="detail-row"><span>Active overlay</span><span className="td-mono">{node.active_overlay_vpn_ip || '—'}</span></div>
          <div className="detail-row"><span>Active interface</span><span className="td-mono">{node.active_overlay_interface || '—'}</span></div>
          <div className="detail-row"><span>Last seen</span><span>{relTime(node.last_seen)}</span></div>
        </div>
      </section>

      <section className="detail-section">
        <div className="detail-section-head">
          <h3>Exceptions</h3>
        </div>
        <ExceptionsPanel exceptions={summary.exceptions} />
      </section>

      <section className="detail-section">
        <div className="detail-section-head">
          <h3>Service Routes</h3>
        </div>
        <div className="detail-list">
          <div className="detail-row"><span>Advertised prefixes</span><span>{summary.prefixCount}</span></div>
          <div className="detail-row"><span>Site subnet</span><span className="td-mono">{node.site_subnet || '—'}</span></div>
          <div className="detail-row"><span>Established sessions</span><span>{summary.establishedSessions}/{summary.bgpSessions.length || 0}</span></div>
        </div>
      </section>

      <section className="detail-section">
        <div className="detail-section-head">
          <h3>Policy Summary</h3>
        </div>
        <PolicySummaryCard summary={summary.policySummary} />
      </section>

      <section className="detail-section">
        <div className="detail-section-head">
          <h3>Recent Failovers</h3>
        </div>
        <EventTimeline events={failovers} />
      </section>
    </>
  )
}

function TransportsTab({ node, bgpByIp }) {
  return (
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
  )
}

function RoutingTab({ summary }) {
  return (
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
              <th>BFD</th>
              <th>State</th>
              <th>Uptime</th>
              <th>Prefixes</th>
              <th>Last reset</th>
            </tr>
          </thead>
          <tbody>
            {summary.bgpSessions.map((session) => (
              <tr key={session.ip}>
                <td>{session.transport || 'Identity'}</td>
                <td className="td-mono">{session.ip}</td>
                <td><BfdBadge status={session.link?.bfd_status || session.info?.bfd_status} /></td>
                <td><BgpBadge info={session.info} compact /></td>
                <td className="td-mono">{session.info?.uptime || '—'}</td>
                <td>{session.info?.prefixes_received ?? 0}</td>
                <td>{session.info?.last_reset_due_to || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function PoliciesTab({ summary }) {
  return (
    <>
      <section className="detail-section">
        <div className="detail-section-head">
          <h3>Path Policy</h3>
        </div>
        <PolicySummaryCard summary={summary.policySummary} />
      </section>

      <section className="detail-section">
        <div className="detail-section-head">
          <h3>Policy Exceptions</h3>
        </div>
        <ExceptionsPanel exceptions={summary.exceptions.filter((item) => item.toLowerCase().includes('policy') || item.toLowerCase().includes('fallback'))} />
      </section>
    </>
  )
}

function EventsTab({ summary }) {
  return (
    <section className="detail-section">
      <div className="detail-section-head">
        <h3>Events</h3>
      </div>
      <EventTimeline events={summary.recentEvents} />
    </section>
  )
}

export default function SiteDetailDrawer({ node, bgp, onClose }) {
  const [activeTab, setActiveTab] = useState('Overview')
  const summary = useMemo(() => summarizeSite(node, bgp), [node, bgp])

  if (!node) return null

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
          <MetricCard label="Overall health" value={<HealthBadge health={node.health || summary.health} />} />
          <MetricCard label="Node status" value={<StatusBadge status={node.status} />} />
          <MetricCard label="Active transport" value={summary.activeTransport ? <TransportBadge transport={summary.activeTransport} /> : '—'} />
          <MetricCard label="Established BGP" value={`${summary.establishedSessions}/${summary.bgpSessions.length || 0}`} tone={summary.pendingSessions > 0 ? 'warn' : 'ok'} />
        </div>

        <div className="detail-tabs" role="tablist" aria-label="Site detail tabs">
          {TABS.map((tab) => (
            <button
              key={tab}
              className={`detail-tab ${activeTab === tab ? 'active' : ''}`}
              onClick={() => setActiveTab(tab)}
            >
              {tab}
            </button>
          ))}
        </div>

        {activeTab === 'Overview' ? <OverviewTab node={node} summary={summary} /> : null}
        {activeTab === 'Transports' ? <TransportsTab node={node} bgpByIp={bgpByIp} /> : null}
        {activeTab === 'Routing' ? <RoutingTab summary={summary} /> : null}
        {activeTab === 'Policies' ? <PoliciesTab summary={summary} /> : null}
        {activeTab === 'Events' ? <EventsTab summary={summary} /> : null}
      </aside>
    </div>
  )
}
