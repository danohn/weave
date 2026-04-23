import { useAuth } from '../contexts/AuthContext'
import { useData } from '../contexts/DataContext'

export default function Header() {
  const { user, logout } = useAuth()
  const { connected, nodes } = useData()

  return (
    <header>
      <div className="logo">
        <img src="/logo.svg" width="20" height="20" alt="Weave" />
        Weave
      </div>
      <div className="header-right">
        {user && <span className="header-user">{user.username}</span>}
        {user && (
          <button className="btn btn-ghost" onClick={logout}>Sign out</button>
        )}
        <div className="health-badge">
          <div className={`health-dot ${connected ? 'ok' : 'error'}`} />
          <span>
            {connected
              ? `${nodes.length} node${nodes.length !== 1 ? 's' : ''}`
              : 'Connecting…'}
          </span>
        </div>
      </div>
    </header>
  )
}
