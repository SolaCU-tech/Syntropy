import { useCallback, useState, type ReactNode } from 'react'

import { ToastContext } from './toast-context'

type Toast = { id: number; text: string }

/** Small, polite confirmations ("Sale saved on this device…"). */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const push = useCallback((text: string) => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, text }])
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000)
  }, [])
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div aria-live="polite" role="status" className="pointer-events-none fixed inset-x-0 bottom-20 z-50 flex flex-col items-center gap-2 px-4 md:bottom-6">
        {toasts.map((t) => (
          <div key={t.id} className="pointer-events-auto rounded-lg bg-brand px-4 py-3 text-sm text-on-brand shadow-md">
            {t.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
