import { useState, useRef, useEffect } from 'react'
import { api } from '../lib/api'
import { useToast } from '../contexts/ToastContext'

export default function EditSubnetModal({ node, onClose }) {
  const toast  = useToast()
  const [subnet, setSubnet] = useState(node.site_subnet || '')
  const [busy, setBusy] = useState(false)
  const inputRef = useRef(null)

  useEffect(() => { inputRef.current?.focus() }, [])

  const handleSave = async () => {
    setBusy(true)
    try {
      await api.patch(`/api/v1/nodes/${node.id}`, { site_subnet: subnet.trim() || null })
      toast(subnet.trim() ? `Subnet set to ${subnet.trim()}` : 'Subnet cleared')
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
        <div className="modal-title">Edit Site Subnet</div>
        <div className="modal-desc">
          LAN subnet behind <strong>{node.name}</strong>. Agents will add this to WireGuard
          AllowedIPs and BGP will advertise it to peers. Clear the field to remove.
        </div>
        <div className="modal-field">
          <label>Subnet (CIDR)</label>
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
