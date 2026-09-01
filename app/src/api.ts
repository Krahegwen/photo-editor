import type {
  Exif,
  ExportState,
  Folder,
  Health,
  MetricsState,
  Photo,
  PresetKey,
  PreviewResult,
  Recipe,
  ScanState,
} from './types'

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

  getRecipe: (photoId: number) =>
    req<{ recipe: Recipe | null; defaults: Recipe }>(`/api/develop/${photoId}`),
  putRecipe: (photoId: number, recipe: Recipe) =>
    req<{ ok: boolean }>(`/api/develop/${photoId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ recipe }),
    }),
  deleteRecipe: (photoId: number) =>
    req<{ ok: boolean }>(`/api/develop/${photoId}`, { method: 'DELETE' }),
  developPreview: (photoId: number, recipe: Recipe, skipCrop = false) =>
    post<PreviewResult>('/api/develop/preview', {
      photo_id: photoId,
      recipe,
      skip_crop: skipCrop,
    }),
  copyRecipe: (recipe: Recipe, toPhotoIds: number[], includeGeometry = false) =>
    post<{ results: { photo_id: number; ok: boolean; error?: string }[] }>(
      '/api/develop/copy',
      { recipe, to_photo_ids: toPhotoIds, include_geometry: includeGeometry },
    ),
  export: (photoIds: number[], preset: PresetKey, force = false) =>
    post<{ started: boolean }>('/api/export', { photo_ids: photoIds, preset, force }),
  exportStatus: () => req<ExportState>('/api/export/status'),
}
