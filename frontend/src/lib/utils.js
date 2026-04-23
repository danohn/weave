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
