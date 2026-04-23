import { useState, useRef, useEffect } from 'react'
import { api } from '../lib/api'
import { useToast } from '../contexts/ToastContext'

export default function CreateClaimModal({ onClose, onCreated }) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({
    device_id: '', expected_name: '', site_name: '', site_subnet: '',
  })
  const firstRef = useRef(null)

  useEffect(() => { firstRef.current?.focus() }, [])

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const handleCreate = async () => {
    if (!form.device_id.trim()) { firstRef.current?.focus(); return }
    setBusy(true)
    try {
      const data = await api.post('/api/v1/auth/claims', {
        device_id:     form.device_id.trim(),
        expected_name: form.expected_name.trim() || null,
        site_name:     form.site_name.trim() || null,
        site_subnet:   form.site_subnet.trim() || null,
      })
      onCreated(data)
    } catch (err) {
      toast(err.message, 'err')
    } finally {
      setBusy(false)
    }
  }

  const onKey = e => { if (e.key === 'Enter') handleCreate() }

  return (
    <div className="overlay open" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-title">New Bootstrap Claim</div>
        <div className="modal-desc">
          Single-use. A claimed node will auto-activate and link back to this inventory record.
        </div>
        <div className="modal-field">
          <label>Device ID</label>
          <input
            ref={firstRef}
            value={form.device_id}
            onChange={e => set('device_id', e.target.value)}
            placeholder="e.g. branch-sydney-01"
            onKeyDown={onKey}
          />
        </div>
        <div className="modal-field">
          <label>Expected Node Name</label>
          <input
            value={form.expected_name}
            onChange={e => set('expected_name', e.target.value)}
            placeholder="e.g. branch-sydney"
            onKeyDown={onKey}
          />
        </div>
        <div className="modal-field">
          <label>Site Name</label>
          <input
            value={form.site_name}
            onChange={e => set('site_name', e.target.value)}
            placeholder="e.g. sydney"
            onKeyDown={onKey}
          />
        </div>
        <div className="modal-field">
          <label>Site Subnet</label>
          <input
            value={form.site_subnet}
            onChange={e => set('site_subnet', e.target.value)}
            placeholder="e.g. 192.168.1.0/24"
            onKeyDown={onKey}
          />
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={handleCreate} disabled={busy}>Create</button>
        </div>
      </div>
    </div>
  )
}
