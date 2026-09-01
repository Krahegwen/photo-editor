import type {
  CloseReport,
  Exif,
  Folder,
  Health,
  Job,
  Photo,
  PresetKey,
  PreviewResult,
  Recipe,
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
  del: (photoIds: number[]) =>
    post<{ trashed: string[]; errors: string[] }>('/api/delete', { photo_ids: photoIds }),

  scan: (folders?: string[]) => post<Job>('/api/scan', folders ? { folders } : {}),
  metrics: (folderId: number) => post<Job>('/api/metrics', { folder_id: folderId }),
  export: (photoIds: number[], preset: PresetKey, force = false) =>
    post<Job>('/api/export', { photo_ids: photoIds, preset, force }),
  closeFolder: (folderId: number, execute = false) =>
    post<{ report: CloseReport; job: Job | null }>('/api/close_folder', {
      folder_id: folderId,
      execute,
    }),
  jobs: (limit = 20) => req<Job[]>(`/api/jobs?limit=${limit}`),
  job: (id: string) => req<Job>(`/api/jobs/${id}`),

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
}
