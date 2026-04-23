import { createContext, useContext, useState, useEffect, useRef, useCallback } from 'react'
import { summarizeFleet, sortTransports } from '../lib/utils'

const DataContext = createContext(null)

const WS_RECONNECT_MS = 5000

export function DataProvider({ children }) {
  const [nodes, setNodes] = useState([])
  const [claims, setClaims] = useState([])
  const [bgp, setBgp] = useState({})
  const [policies, setPolicies] = useState([])
  const [connected, setConnected] = useState(false)
  const [lastUpdated, setLastUpdated] = useState(null)

  const wsRef = useRef(null)
  const timerRef = useRef(null)
  const mountedRef = useRef(true)

  const applyMessage = useCallback((data) => {
    if (data.nodes !== undefined) setNodes(data.nodes)
    if (data.claims !== undefined) setClaims(data.claims)
    if (data.bgp !== undefined) setBgp(data.bgp)
    if (data.policies !== undefined) setPolicies(data.policies)
    setConnected(true)
    setLastUpdated(new Date())
  }, [])

  useEffect(() => {
    mountedRef.current = true

    function connect() {
      if (!mountedRef.current) return
      const wsUrl = location.origin.replace(/^http/, 'ws') + '/ws'
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onmessage = (ev) => {
        try { applyMessage(JSON.parse(ev.data)) } catch {}
      }

      ws.onclose = (ev) => {
        if (!mountedRef.current) return
        setConnected(false)
        if (ev.code === 4001) {
          // Auth expired — signal global logout
          window.dispatchEvent(new Event('auth:expired'))
          return
        }
        timerRef.current = setTimeout(connect, WS_RECONNECT_MS)
      }
    }

    connect()

    return () => {
      mountedRef.current = false
      clearTimeout(timerRef.current)
      if (wsRef.current) {
        wsRef.current.onclose = null  // prevent reconnect loop on unmount
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [applyMessage])

  const fleet = summarizeFleet(nodes, bgp, policies)
  const transportInventory = fleet.transportLinks
    .map((transport) => ({
      ...transport,
      bgp: transport.overlay_vpn_ip ? bgp[transport.overlay_vpn_ip] : null,
    }))
    .sort((a, b) => {
      const siteCompare = String(a.node?.name || '').localeCompare(String(b.node?.name || ''))
      if (siteCompare !== 0) return siteCompare
      const transportCompare = (a.priority ?? 999) - (b.priority ?? 999)
      if (transportCompare !== 0) return transportCompare
      return String(a.kind || '').localeCompare(String(b.kind || ''))
    })

  const routingPeers = Object.entries(bgp)
    .map(([ip, info]) => {
      for (const node of nodes) {
        for (const link of sortTransports(node.transport_links || [])) {
          if (link.overlay_vpn_ip === ip) {
            return { ip, info, node, transport: link }
          }
        }
        if (node.vpn_ip === ip) {
          return { ip, info, node, transport: null }
        }
      }
      return { ip, info, node: null, transport: null }
    })
    .sort((a, b) => String(a.node?.name || a.ip).localeCompare(String(b.node?.name || b.ip)))

  return (
    <DataContext.Provider value={{
      nodes,
      claims,
      bgp,
      policies,
      connected,
      lastUpdated,
      fleet,
      transportInventory,
      routingPeers,
    }}>
      {children}
    </DataContext.Provider>
  )
}

export const useData = () => useContext(DataContext)
