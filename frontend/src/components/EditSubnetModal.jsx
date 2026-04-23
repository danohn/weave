import { useState, useRef, useEffect } from 'react'
import { api } from '../lib/api'
import { useToast } from '../contexts/ToastContext'

export default function EditSubnetModal({ node, onClose }) {
  const toast  = useToast()
  const [siteName, setSiteName] = useState(node.site?.name || node.name)
  const [subnet, setSubnet] = useState(node.site_subnet || '')
  const [busy, setBusy] = useState(false)
  const inputRef = useRef(null)

  useEffect(() => { inputRef.current?.focus() }, [])

  const handleSave = async () => {
    setBusy(true)
    try {
      await api.patch(`/api/v1/nodes/${node.id}`, {
        site_name: siteName.trim() || node.name,
        site_subnet: subnet.trim() || null,
      })
      toast(subnet.trim() ? `Site updated: ${siteName.trim() || node.name} / ${subnet.trim()}` : `Site updated: ${siteName.trim() || node.name}`)
      onClose()
    } catch (err) {
      toast(err.message, 'err')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="overlay open" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-title">Edit Site</div>
        <div className="modal-desc">
          Manage the logical site attached to <strong>{node.name}</strong>. The primary
          site prefix is still projected onto the current WireGuard and FRR data plane.
        </div>
        <div className="modal-field">
          <label>Site Name</label>
          <input
            value={siteName}
            onChange={e => setSiteName(e.target.value)}
            placeholder="e.g. Sydney Branch"
          />
        </div>
        <div className="modal-field">
          <label>Primary Prefix (CIDR)</label>
          <input
            ref={inputRef}
            value={subnet}
            onChange={e => setSubnet(e.target.value)}
            placeholder="e.g. 192.168.1.0/24"
            onKeyDown={e => e.key === 'Enter' && handleSave()}
          />
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={handleSave} disabled={busy}>Save</button>
        </div>
      </div>
    </div>
  )
}
