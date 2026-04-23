import { createContext, useContext, useState, useCallback } from 'react'
import ConfirmModal from '../components/ConfirmModal'

const ConfirmContext = createContext(null)

export function ConfirmProvider({ children }) {
  const [state, setState] = useState(null)

  const confirm = useCallback((title, desc, onOk) => {
    setState({ title, desc, onOk })
  }, [])

  const close = () => setState(null)

  const handleOk = async () => {
    const cb = state?.onOk
    close()
    if (cb) await cb()
  }

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {state && (
        <ConfirmModal
          title={state.title}
          desc={state.desc}
          onOk={handleOk}
          onCancel={close}
        />
      )}
    </ConfirmContext.Provider>
  )
}

export const useConfirm = () => useContext(ConfirmContext)
