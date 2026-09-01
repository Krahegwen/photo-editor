import type { Folder, Health, Photo, ScanState } from './types'

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`)
  return r.json() as Promise<T>
}

export const api = {
  health: () => req<Health>('/api/health'),
  folders: () => req<Folder[]>('/api/folders'),
  photos: (folderId: number) => req<Photo[]>(`/api/photos?folder_id=${folderId}`),
  scan: (folders?: string[]) =>
    req<{ started: boolean }>('/api/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(folders ? { folders } : {}),
    }),
  scanStatus: () => req<ScanState>('/api/scan/status'),
}
