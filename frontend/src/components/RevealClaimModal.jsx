import { useEffect, useRef } from 'react'
import { buildInstallCommand } from '../lib/utils'
import { useToast } from '../contexts/ToastContext'

export default function RevealClaimModal({ claim, onClose }) {
  const toast   = useToast()
  const tokenRef = useRef(null)
  const command  = buildInstallCommand(claim)

  useEffect(() => { tokenRef.current?.select() }, [])

  const copy = (text, label) =>
    navigator.clipboard.writeText(text)
      .then(() => toast(`${label} copied`))
      .catch(() => toast('Select and copy manually', 'err'))

  return (
    <div className="overlay open" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-title">Claim Created</div>
        <div className="modal-desc">
          Copy this claim token now — <strong>it won't be shown again.</strong>
        </div>
        <div className="modal-field">
          <label>Claim Token</label>
          <div className="token-reveal-row">
            <input ref={tokenRef} type="text" readOnly value={claim.token} />
            <button className="btn btn-ghost" onClick={() => copy(claim.token, 'Token')}>Copy</button>
          </div>
        </div>
        <div className="modal-field">
          <label>Install Command</label>
          <div className="install-command-row">
            <textarea readOnly value={command} />
            <button className="btn btn-ghost" onClick={() => copy(command, 'Install command')}>Copy</button>
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn btn-primary" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  )
}
