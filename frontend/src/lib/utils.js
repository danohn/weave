export function relTime(iso) {
  if (!iso) return '—'
  const sec = (Date.now() - new Date(iso.endsWith('Z') ? iso : iso + 'Z')) / 1000
  if (sec < 60)    return `${Math.round(sec)}s ago`
  if (sec < 3600)  return `${Math.floor(sec / 60)}m ago`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`
  return `${Math.floor(sec / 86400)}d ago`
}

export function tsAgeClass(iso) {
  if (!iso) return ''
  const sec = (Date.now() - new Date(iso.endsWith('Z') ? iso : iso + 'Z')) / 1000
  if (sec < 45)  return 'ts-fresh'
  if (sec < 180) return 'ts-warm'
  return 'ts-stale'
}

export function shellEscape(str) {
  return `'${String(str).replace(/'/g, "'\"'\"'")}'`
}

export function buildInstallCommand(claim) {
  const controllerUrl = location.origin
  const lines = [
    'REF=main',
    `curl -fsSL "https://raw.githubusercontent.com/danohn/weave/\${REF}/agent/install.sh" \\`,
    '  | bash -s -- \\',
    `      --controller-url ${shellEscape(controllerUrl)} \\`,
    `      --claim-token ${shellEscape(claim.token)} \\`,
  ]
  if (claim.expected_name) {
    lines.push(`      --node-name ${shellEscape(claim.expected_name)} \\`)
  }
  lines.push('      --repo-ref "${REF}"')
  return lines.join('\n')
}

export function bgpStateClass(state) {
  if (!state) return 'badge-bgp-unknown'
  if (state === 'Established') return 'badge-bgp-up'
  if (state === 'Active' || state === 'Connect') return 'badge-bgp-pending'
  return 'badge-bgp-down'
}

export function normalizeTransportStatus(status) {
  return status === 'UNKNOWN' ? 'Unmeasured' : (status || 'Unmeasured')
}

export function sortTransports(links = []) {
  return [...links].sort((a, b) => {
    const pa = a.priority ?? 999
    const pb = b.priority ?? 999
    if (pa !== pb) return pa - pb
    return String(a.kind || '').localeCompare(String(b.kind || ''))
  })
}

export function summarizeSite(node, bgp = {}, policies = []) {
  const transports = sortTransports(node.transport_links || [])
  const bgpSessions = []

  for (const transport of transports) {
    if (!transport.overlay_vpn_ip) continue
    bgpSessions.push({
      ip: transport.overlay_vpn_ip,
      info: bgp[transport.overlay_vpn_ip],
      transport: transport.kind,
      link: transport,
    })
  }

  if (!bgpSessions.some((item) => item.ip === node.vpn_ip)) {
    bgpSessions.push({
      ip: node.vpn_ip,
      info: bgp[node.vpn_ip],
      transport: null,
      link: null,
    })
  }

  const establishedSessions = bgpSessions.filter((item) => item.info?.state === 'Established').length
  const pendingSessions = bgpSessions.filter((item) => ['Connect', 'Active'].includes(item.info?.state)).length
  const failedSessions = bgpSessions.filter((item) => item.info && !['Established', 'Connect', 'Active'].includes(item.info.state)).length

  const downTransports = transports.filter((item) => item.status === 'DOWN').length
  const degradedTransports = transports.filter((item) => item.status === 'DEGRADED').length
  const healthyTransports = transports.filter((item) => item.status === 'HEALTHY').length
  const unmeasuredTransports = transports.filter((item) => !item.status || item.status === 'UNKNOWN').length
  const prefixCount = node.site?.prefixes?.length || (node.site_subnet ? 1 : 0)
  const activeTransport = node.active_transport || transports.find((item) => item.is_active) || null

  let health = 'Healthy'
  if (node.status === 'REVOKED') health = 'Down'
  else if (node.status !== 'ACTIVE') health = 'Degraded'
  else if (downTransports > 0 || failedSessions > 0) health = 'Degraded'
  else if (pendingSessions > 0) health = 'Degraded'
  else if (establishedSessions === 0 && bgpSessions.length > 0) health = 'Down'

  return {
    id: node.id,
    node,
    transports,
    bgpSessions,
    establishedSessions,
    pendingSessions,
    failedSessions,
    downTransports,
    degradedTransports,
    healthyTransports,
    unmeasuredTransports,
    prefixCount,
    activeTransport,
    policyCount: policies.filter((policy) => !policy.node_id || policy.node_id === node.id || (!policy.node_id && policy.site_id && policy.site_id === node.site_id) || (!policy.node_id && !policy.site_id)).length,
    health,
  }
}

export function describeSiteHealth(summary) {
  const parts = []
  if (summary.activeTransport) {
    parts.push(`Primary path on ${summary.activeTransport.kind}`)
  }
  if (summary.pendingSessions > 0) {
    parts.push(`${summary.pendingSessions} session${summary.pendingSessions === 1 ? '' : 's'} converging`)
  } else if (summary.downTransports > 0) {
    parts.push(`${summary.downTransports} transport${summary.downTransports === 1 ? '' : 's'} down`)
  } else if (summary.unmeasuredTransports > 0) {
    parts.push(`${summary.unmeasuredTransports} transport${summary.unmeasuredTransports === 1 ? '' : 's'} unmeasured`)
  } else {
    parts.push('All active transport sessions established')
  }
  return parts.join(' · ')
}

export function summarizeFleet(nodes, bgp, policies) {
  const sites = nodes.map((node) => summarizeSite(node, bgp, policies))
  const activeSites = sites.filter((site) => site.node.status === 'ACTIVE').length
  const healthySites = sites.filter((site) => site.health === 'Healthy').length
  const degradedSites = sites.filter((site) => site.health === 'Degraded').length
  const downSites = sites.filter((site) => site.health === 'Down').length
  const transportLinks = sites.flatMap((site) => site.transports.map((transport) => ({ ...transport, node: site.node })))
  const healthyTransports = transportLinks.filter((link) => link.status === 'HEALTHY').length
  const degradedTransports = transportLinks.filter((link) => link.status === 'DEGRADED').length
  const downTransports = transportLinks.filter((link) => link.status === 'DOWN').length
  const unmeasuredTransports = transportLinks.filter((link) => !link.status || link.status === 'UNKNOWN').length
  const bgpPeers = Object.entries(bgp)
  const establishedPeers = bgpPeers.filter(([, info]) => info?.state === 'Established').length
  const pendingPeers = bgpPeers.filter(([, info]) => ['Connect', 'Active'].includes(info?.state)).length

  return {
    sites,
    activeSites,
    healthySites,
    degradedSites,
    downSites,
    transportLinks,
    healthyTransports,
    degradedTransports,
    downTransports,
    unmeasuredTransports,
    establishedPeers,
    pendingPeers,
  }
}
