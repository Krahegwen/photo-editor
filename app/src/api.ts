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
  root: (path?: string) =>
    req<RootInfo>(`/api/root${path ? `?path=${encodeURIComponent(path)}` : ''}`),
  setRoot: (root: string) => post<RootInfo>('/api/root', { root }),
  browseRoot: () => post<RootInfo>('/api/root/browse', {}),
  setGpu: (enabled: boolean) => post<GpuInfo>('/api/gpu', { enabled }),
  renameFolder: (folderId: number, name: string) =>
    post<{ ok: boolean; name: string; previews_migradas: number }>(
      `/api/folders/${folderId}/rename`,
      { name },
    ),
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
  stack: (
    photoIds: number[],
    mode: string,
    opts: { cropPx?: number; escala?: string; force?: boolean } = {},
  ) =>
    post<Job>('/api/stack', {
      photo_ids: photoIds,
      mode,
      crop_px: opts.cropPx ?? 1200,
      escala: opts.escala ?? 'auto',
      force: opts.force ?? false,
    }),
  timelapse: (photoIds: number[], fps = 24, force = false) =>
    post<Job>('/api/timelapse', { photo_ids: photoIds, fps, force }),
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
