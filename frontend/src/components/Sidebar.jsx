import { NavLink } from 'react-router-dom'
import { useData } from '../contexts/DataContext'

export default function Sidebar() {
  const { nodes, claims, routingPeers, transportInventory, policies } = useData()

  const pendingNodes  = nodes.filter(n => n.status === 'PENDING').length
  const pendingClaims = claims.filter(c => c.status === 'UNCLAIMED').length
  const peerCount     = routingPeers.length
  const transportCount = transportInventory.length
  const policyCount   = policies.length

  return (
    <nav className="sidebar">
      <NavLink to="/sites" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
        <span className="nav-label">Sites</span>
        {pendingNodes > 0 && <span className="nav-badge">{pendingNodes}</span>}
      </NavLink>
      <NavLink to="/claims" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
        <span className="nav-label">Claims</span>
        {pendingClaims > 0 && <span className="nav-badge">{pendingClaims}</span>}
      </NavLink>
      <NavLink to="/transports" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
        <span className="nav-label">Transports</span>
        {transportCount > 0 && <span className="nav-badge nav-badge-neutral">{transportCount}</span>}
      </NavLink>
      <NavLink to="/routing" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
        <span className="nav-label">Routing</span>
        {peerCount > 0 && <span className="nav-badge nav-badge-neutral">{peerCount}</span>}
      </NavLink>
      <NavLink to="/policies" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
        <span className="nav-label">Policies</span>
        {policyCount > 0 && <span className="nav-badge nav-badge-neutral">{policyCount}</span>}
      </NavLink>
    </nav>
  )
}
