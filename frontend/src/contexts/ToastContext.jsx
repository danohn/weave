import { createContext, useContext, useState, useCallback, useRef } from 'react'
import { createPortal } from 'react-dom'

const ToastContext = createContext(null)

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const idRef = useRef(0)

  const toast = useCallback((msg, type = 'ok') => {
    const id = ++idRef.current
    setToasts(prev => [...prev, { id, msg, type }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 3500)
  }, [])

  return (
    <ToastContext.Provider value={toast}>
      {children}
      {createPortal(
        <div id="toasts">
          {toasts.map(t => (
            <div key={t.id} className={`toast toast-${t.type}`}>{t.msg}</div>
          ))}
        </div>,
        document.body
      )}
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)
