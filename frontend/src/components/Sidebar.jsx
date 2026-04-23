import { NavLink } from 'react-router-dom'
import { useData } from '../contexts/DataContext'

export default function Sidebar() {
  const { nodes, claims, bgp, policies } = useData()

  const pendingNodes  = nodes.filter(n => n.status === 'PENDING').length
  const pendingClaims = claims.filter(c => c.status === 'UNCLAIMED').length
  const bgpCount      = Object.keys(bgp).length
  const policyCount   = policies.length

  return (
    <nav className="sidebar">
      <NavLink to="/nodes" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
        <span className="nav-label">Nodes</span>
        {pendingNodes > 0 && <span className="nav-badge">{pendingNodes}</span>}
      </NavLink>
      <NavLink to="/claims" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
        <span className="nav-label">Claims</span>
        {pendingClaims > 0 && <span className="nav-badge">{pendingClaims}</span>}
      </NavLink>
      <NavLink to="/bgp" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
        <span className="nav-label">BGP</span>
        {bgpCount > 0 && <span className="nav-badge nav-badge-neutral">{bgpCount}</span>}
      </NavLink>
      <NavLink to="/policies" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
        <span className="nav-label">Policies</span>
        {policyCount > 0 && <span className="nav-badge nav-badge-neutral">{policyCount}</span>}
      </NavLink>
    </nav>
  )
}
