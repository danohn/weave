import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './contexts/AuthContext'
import { DataProvider } from './contexts/DataContext'
import LoginView from './views/LoginView'
import SitesView from './views/SitesView'
import ClaimsView from './views/ClaimsView'
import RoutingView from './views/RoutingView'
import TransportsView from './views/TransportsView'
import PoliciesView from './views/PoliciesView'
import Sidebar from './components/Sidebar'
import Header from './components/Header'

/**
 * Authenticated shell — DataProvider only mounts when the user is logged in.
 * This guarantees:
 *  - No WebSocket connection while logged out
 *  - WS closes immediately on logout (DataProvider unmounts)
 *  - No API polling of any kind before auth is confirmed
 */
function AppShell() {
  return (
    <DataProvider>
      <Header />
      <div className="app-body">
        <Sidebar />
        <main className="content">
          <Routes>
            <Route path="/" element={<Navigate to="/sites" replace />} />
            <Route path="/nodes" element={<Navigate to="/sites" replace />} />
            <Route path="/bgp" element={<Navigate to="/routing" replace />} />
            <Route path="/sites" element={<SitesView />} />
            <Route path="/claims" element={<ClaimsView />} />
            <Route path="/transports" element={<TransportsView />} />
            <Route path="/routing" element={<RoutingView />} />
            <Route path="/policies" element={<PoliciesView />} />
          </Routes>
        </main>
      </div>
    </DataProvider>
  )
}

export default function App() {
  const { user, loading } = useAuth()

  // Hold render until the /auth/me check resolves to avoid a flash of login
  if (loading) return null

  return user ? <AppShell /> : <LoginView />
}
