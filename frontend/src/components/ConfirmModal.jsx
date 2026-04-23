export default function ConfirmModal({ title, desc, onOk, onCancel }) {
  return (
    <div className="overlay open" onClick={e => e.target === e.currentTarget && onCancel()}>
      <div className="modal">
        <div className="modal-title">{title}</div>
        {/* desc may contain <strong> tags */}
        <div className="modal-desc" dangerouslySetInnerHTML={{ __html: desc }} />
        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onCancel}>Cancel</button>
          <button className="btn btn-primary" onClick={onOk}>Confirm</button>
        </div>
      </div>
    </div>
  )
}
