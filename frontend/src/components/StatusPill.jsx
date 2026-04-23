import { bgpStateClass } from '../lib/utils'

export function StatusBadge({ status }) {
  return (
    <span className={`badge badge-${String(status || 'unknown').toLowerCase()}`}>
      <span className="badge-pip" />
      {status}
    </span>
  )
}

export function BgpBadge({ info, compact = false }) {
  if (!info) {
    return <span className="badge badge-bgp-unknown"><span className="badge-pip" />—</span>
  }
  const cls = bgpStateClass(info.state)
  const label = compact || info.state !== 'Established'
    ? (info.state || '—')
    : `${info.state} (${info.uptime})`
  return <span className={`badge ${cls}`}><span className="badge-pip" />{label}</span>
}

export function HealthBadge({ health }) {
  const normalized = String(health || 'unknown').toLowerCase()
  const cls = normalized === 'healthy'
    ? 'badge-bgp-up'
    : normalized === 'degraded'
      ? 'badge-bgp-pending'
      : normalized === 'down'
        ? 'badge-bgp-down'
        : 'badge-bgp-unknown'
  return (
    <span className={`badge ${cls}`}>
      <span className="badge-pip" />
      {health || 'Unknown'}
    </span>
  )
}

export function TransportBadge({ transport, verbose = false }) {
  if (!transport) {
    return <span className="badge badge-bgp-unknown"><span className="badge-pip" />—</span>
  }
  const status = transport.status === 'UNKNOWN' ? 'Unmeasured' : transport.status
  const cls = transport.status === 'HEALTHY'
    ? 'badge-bgp-up'
    : transport.status === 'DEGRADED'
      ? 'badge-bgp-pending'
      : transport.status === 'DOWN'
        ? 'badge-bgp-down'
        : 'badge-bgp-unknown'
  const label = verbose ? `${transport.kind} / ${status}` : transport.kind
  return <span className={`badge ${cls}`}><span className="badge-pip" />{label}</span>
}
