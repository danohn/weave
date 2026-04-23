import { useMemo, useState } from 'react'
import { useData } from '../contexts/DataContext'
import { useConfirm } from '../contexts/ConfirmContext'
import { useToast } from '../contexts/ToastContext'
import { api } from '../lib/api'
import { relTime } from '../lib/utils'
import { StatusBadge, HealthBadge, BgpBadge, TransportBadge } from '../components/StatusPill'
import SiteDetailDrawer from '../components/SiteDetailDrawer'
import EditSubnetModal from '../components/EditSubnetModal'

const STATUS_ORDER = { Healthy: 0, Degraded: 1, Down: 2 }

function MetricCard({ label, value, tone = '', note }) {
  return (
    <div className={`stat-card metric-card ${tone}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-num">{value}</div>
      {note ? <div className="metric-note">{note}</div> : null}
    </div>
  )
}

function EventFeed({ title, events, empty }) {
  return (
    <div className="event-panel">
      <div className="event-panel-head">
        <h3>{title}</h3>
      </div>
      {events.length === 0 ? (
        <div className="detail-note">{empty}</div>
      ) : (
        <div className="event-timeline compact">
          {events.map((event) => (
            <div key={event.id || `${event.kind}-${event.occurred_at}-${event.title}`} className="event-row">
              <div className="event-title">{event.title}</div>
              <div className="event-message">{event.message}</div>
              <div className="event-time">{relTime(event.occurred_at)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function SitesView() {
  const { fleet, lastUpdated, bgp } = useData()
  const confirm = useConfirm()
  const toast = useToast()
  const [selectedNode, setSelectedNode] = useState(null)
  const [subnetNode, setSubnetNode] = useState(null)

  const sorted = useMemo(() => [...fleet.sites].sort((a, b) => {
    const healthCompare = (STATUS_ORDER[a.health] ?? 9) - (STATUS_ORDER[b.health] ?? 9)
    if (healthCompare !== 0) return healthCompare
    return a.node.name.localeCompare(b.node.name)
  }), [fleet.sites])

  const doRevoke = (node) => confirm(
    'Revoke site',
    `Revoke <strong>${node.name}</strong>? It will be excluded from all peer lists.`,
    async () => {
      try {
        await api.delete(`/api/v1/nodes/${node.id}/revoke`)
        toast(`${node.name} revoked`)
      } catch (err) {
        toast(err.message, 'err')
      }
    }
  )

  const overview = [
    { label: 'Sites', value: fleet.sites.length || '—', note: `${fleet.activeSites} active` },
    { label: 'Healthy', value: fleet.healthySites || '—', tone: 'live', note: `${fleet.degradedSites} degraded` },
    { label: 'Established paths', value: fleet.establishedPeers || '—', tone: 'live', note: `${fleet.pendingPeers} converging` },
    { label: 'Transport alerts', value: (fleet.degradedTransports + fleet.downTransports) || '—', tone: fleet.degradedTransports + fleet.downTransports > 0 ? 'muted' : '', note: `${fleet.unmeasuredTransports} unmeasured` },
    { label: 'Site exceptions', value: fleet.exceptionCount || '—', tone: fleet.exceptionCount > 0 ? 'muted' : '', note: 'Health and policy exceptions' },
  ]

  return (
    <>
      <div className="stats">
        {overview.map((item) => (
          <MetricCard key={item.label} label={item.label} value={item.value} tone={item.tone} note={item.note} />
        ))}
      </div>

      <div className="section-head">
        <div>
          <div className="section-title">Sites</div>
          <div className="section-subtitle">Fleet health, active path selection, and service reachability.</div>
        </div>
        <div className="section-meta">
          {lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString()}` : ''}
        </div>
      </div>

      <div className="overview-grid">
        <EventFeed
          title="Recent Events"
          events={fleet.recentEvents.slice(0, 8)}
          empty="No recent fleet events."
        />
        <EventFeed
          title="Recent Failovers"
          events={fleet.recentFailovers.slice(0, 6)}
          empty="No recent transport failovers."
        />
      </div>

      <div className="table-shell">
        <table>
          <thead>
            <tr>
              <th>Site</th>
              <th>Health</th>
              <th>Node</th>
              <th>Reachability</th>
              <th>Active path</th>
              <th>Service routes</th>
              <th>Exceptions</th>
              <th>Last seen</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr><td colSpan={9}><div className="placeholder">No sites registered yet</div></td></tr>
            ) : sorted.map((site) => {
              const node = site.node
              const primaryBgp = site.bgpSessions.find((session) => session.ip === (node.active_overlay_vpn_ip || node.vpn_ip))?.info
              return (
                <tr key={node.id}>
                  <td className="td-name">
                    <button className="linkish-btn" onClick={() => setSelectedNode(node)}>
                      {node.site?.name || node.name}
                    </button>
                    <div className="table-subtext">{site.transports.length} transport{site.transports.length === 1 ? '' : 's'}</div>
                  </td>
                  <td><HealthBadge health={site.health} /></td>
                  <td>
                    <div>{node.name}</div>
                    <div className="table-subtext"><StatusBadge status={node.status} /></div>
                  </td>
                  <td><BgpBadge info={primaryBgp} /></td>
                  <td>
                    {site.activeTransport ? <TransportBadge transport={site.activeTransport} /> : <span className="td-empty">—</span>}
                    <div className="table-subtext td-mono">{node.active_overlay_vpn_ip || node.vpn_ip}</div>
                  </td>
                  <td className="td-subnet">
                    {node.site_subnet ? (
                      <>
                        <span className={`reach-dot ${(primaryBgp?.prefixes_received ?? 0) > 0 ? 'reach-ok' : 'reach-no'}`} />
                        <span className="subnet-pill">{node.site_subnet}</span>
                        <button className="edit-btn" onClick={() => setSubnetNode(node)}>Edit</button>
                      </>
                    ) : (
                      <>
                        <span className="td-empty">No prefix</span>
                        <button className="edit-btn" onClick={() => setSubnetNode(node)}>Set</button>
                      </>
                    )}
                  </td>
                  <td>
                    {site.exceptions.length > 0 ? (
                      <>
                        <span className="exception-count">{site.exceptions.length} active</span>
                        <div className="table-subtext">{site.exceptions[0]}</div>
                      </>
                    ) : (
                      <span className="td-empty">None</span>
                    )}
                  </td>
                  <td>{relTime(node.last_seen)}</td>
                  <td className="td-actions">
                    <button className="row-btn" onClick={() => setSelectedNode(node)}>Inspect</button>
                    {node.status !== 'REVOKED' && (
                      <button className="row-btn" onClick={() => doRevoke(node)}>Revoke</button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {selectedNode ? (
        <SiteDetailDrawer node={selectedNode} bgp={bgp} onClose={() => setSelectedNode(null)} />
      ) : null}

      {subnetNode ? (
        <EditSubnetModal node={subnetNode} onClose={() => setSubnetNode(null)} />
      ) : null}
    </>
  )
}
