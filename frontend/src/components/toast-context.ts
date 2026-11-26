import { createContext, useContext } from 'react'

export const ToastContext = createContext<(text: string) => void>(() => undefined)

export function useToast() {
  return useContext(ToastContext)
}
