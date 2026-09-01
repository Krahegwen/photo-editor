import type { Exif, Folder, Health, MetricsState, Photo, ScanState } from './types'

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`)
  return r.json() as Promise<T>
}

function post<T>(url: string, body: unknown): Promise<T> {
  return req<T>(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export const api = {
  health: () => req<Health>('/api/health'),
  folders: () => req<Folder[]>('/api/folders'),
  photos: (folderId: number) => req<Photo[]>(`/api/photos?folder_id=${folderId}`),
  exif: (photoId: number) => req<Exif>(`/api/exif/${photoId}`),
  rate: (items: { photo_id: number; rating: number }[]) =>
    post<{ results: { photo_id: number; ok: boolean; error?: string }[] }>('/api/rating', {
      items,
    }),
  metrics: (folderId: number) =>
    post<{ started: boolean }>('/api/metrics', { folder_id: folderId }),
  metricsStatus: () => req<MetricsState>('/api/metrics/status'),
  del: (photoIds: number[]) =>
    post<{ trashed: string[]; errors: string[] }>('/api/delete', { photo_ids: photoIds }),
  scan: (folders?: string[]) =>
    post<{ started: boolean }>('/api/scan', folders ? { folders } : {}),
  scanStatus: () => req<ScanState>('/api/scan/status'),
}
