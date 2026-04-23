import { useMemo, useState } from 'react'
import { useData } from '../contexts/DataContext'
import { useToast } from '../contexts/ToastContext'
import { api } from '../lib/api'

const EMPTY_FORM = {
  name: '',
  destination_prefix: '',
  description: '',
  scope_type: 'global',
  site_id: '',
  node_id: '',
  preferred_transport: 'mpls',
  fallback_transport: 'internet',
  priority: 100,
  enabled: true,
}

export default function PoliciesView() {
  const { policies, nodes } = useData()
  const toast = useToast()
  const [form, setForm] = useState(EMPTY_FORM)
  const [saving, setSaving] = useState(false)

  const sites = useMemo(() => {
    const seen = new Map()
    for (const node of nodes) {
      if (node.site?.id && !seen.has(node.site.id)) {
        seen.set(node.site.id, node.site)
      }
    }
    return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name))
  }, [nodes])

  async function createPolicy(e) {
    e.preventDefault()
    setSaving(true)
    try {
      const payload = {
        name: form.name,
        destination_prefix: form.destination_prefix,
        description: form.description || null,
        preferred_transport: form.preferred_transport,
        fallback_transport: form.fallback_transport || null,
        priority: Number(form.priority),
        enabled: form.enabled,
        site_id: form.scope_type === 'site' ? form.site_id || null : null,
        node_id: form.scope_type === 'node' ? form.node_id || null : null,
      }
      await api.post('/api/v1/policies/', payload)
      setForm(EMPTY_FORM)
      toast(`Policy ${payload.name} created`)
    } catch (err) {
      toast(err.message, 'err')
    } finally {
      setSaving(false)
    }
  }

  async function togglePolicy(policy) {
    try {
      await api.patch(`/api/v1/policies/${policy.id}`, { enabled: !policy.enabled })
      toast(`${policy.name} ${policy.enabled ? 'disabled' : 'enabled'}`)
    } catch (err) {
      toast(err.message, 'err')
    }
  }

  async function deletePolicy(policy) {
    try {
      await api.delete(`/api/v1/policies/${policy.id}`)
      toast(`${policy.name} deleted`)
    } catch (err) {
      toast(err.message, 'err')
    }
  }

  return (
    <>
      <div className="section-head">
        <div className="section-title">Policies</div>
        <div className="section-meta">{policies.length} total</div>
      </div>

      <div className="policy-layout">
        <form className="policy-form" onSubmit={createPolicy}>
          <div className="policy-form-title">New Destination Policy</div>
          <label>Name</label>
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />

          <label>Destination Prefix</label>
          <input value={form.destination_prefix} onChange={(e) => setForm({ ...form, destination_prefix: e.target.value })} placeholder="10.50.0.0/24" required />

          <label>Description</label>
          <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="PBX traffic over MPLS" />

          <label>Scope</label>
          <select value={form.scope_type} onChange={(e) => setForm({ ...form, scope_type: e.target.value, site_id: '', node_id: '' })}>
            <option value="global">Global</option>
            <option value="site">Site</option>
            <option value="node">Node</option>
          </select>

          {form.scope_type === 'site' && (
            <>
              <label>Site</label>
              <select value={form.site_id} onChange={(e) => setForm({ ...form, site_id: e.target.value })} required>
                <option value="">Select site</option>
                {sites.map((site) => <option key={site.id} value={site.id}>{site.name}</option>)}
              </select>
            </>
          )}

          {form.scope_type === 'node' && (
            <>
              <label>Node</label>
              <select value={form.node_id} onChange={(e) => setForm({ ...form, node_id: e.target.value })} required>
                <option value="">Select node</option>
                {nodes.map((node) => <option key={node.id} value={node.id}>{node.name}</option>)}
              </select>
            </>
          )}

          <label>Preferred Transport</label>
          <select value={form.preferred_transport} onChange={(e) => setForm({ ...form, preferred_transport: e.target.value })}>
            <option value="internet">internet</option>
            <option value="mpls">mpls</option>
            <option value="lte">lte</option>
            <option value="other">other</option>
          </select>

          <label>Fallback Transport</label>
          <select value={form.fallback_transport} onChange={(e) => setForm({ ...form, fallback_transport: e.target.value })}>
            <option value="">none</option>
            <option value="internet">internet</option>
            <option value="mpls">mpls</option>
            <option value="lte">lte</option>
            <option value="other">other</option>
          </select>

          <label>Priority</label>
          <input type="number" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })} />

          <button className="btn btn-primary" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Create policy'}</button>
        </form>

        <div className="table-shell">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Destination</th>
                <th>Scope</th>
                <th>Preferred</th>
                <th>Fallback</th>
                <th>Priority</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {policies.length === 0 ? (
                <tr><td colSpan={8}><div className="placeholder">No destination policies yet</div></td></tr>
              ) : policies.map((policy) => (
                <tr key={policy.id}>
                  <td className="td-name">{policy.name}</td>
                  <td className="td-mono">{policy.destination_prefix}</td>
                  <td>
                    {policy.node_name ? `Node: ${policy.node_name}` : policy.site_name ? `Site: ${policy.site_name}` : 'Global'}
                  </td>
                  <td>{policy.preferred_transport}</td>
                  <td>{policy.fallback_transport || '—'}</td>
                  <td>{policy.priority}</td>
                  <td>{policy.enabled ? 'Enabled' : 'Disabled'}</td>
                  <td className="td-actions">
                    <button className="row-btn" onClick={() => togglePolicy(policy)}>
                      {policy.enabled ? 'Disable' : 'Enable'}
                    </button>
                    <button className="row-btn" onClick={() => deletePolicy(policy)}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
