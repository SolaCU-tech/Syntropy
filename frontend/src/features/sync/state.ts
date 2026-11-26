import { create } from 'zustand'

/** Connection and sync status for the top-bar pill (spec section 13, UX). */
type SyncState = {
  online: boolean
  syncing: boolean
  lastSync?: string
  setOnline: (online: boolean) => void
  setSyncing: (syncing: boolean) => void
  setLastSync: (at: string) => void
}

export const useSyncState = create<SyncState>((set) => ({
  online: typeof navigator === 'undefined' ? true : navigator.onLine,
  syncing: false,
  setOnline: (online) => set({ online }),
  setSyncing: (syncing) => set({ syncing }),
  setLastSync: (lastSync) => set({ lastSync }),
}))
