export interface Folder {
  id: number
  name: string
  photo_count: number
  last_scan: number | null
}

export interface Photo {
  id: number
  stem: string
  ext: string
  bytes: number
  mtime: number
  taken_at: string | null
  rating: number | null
  sharp: number | null
  clip_hi: number | null
  clip_lo: number | null
  bright: number | null
  metrics_at: number | null
  flags: string[]
  burst_n: number | null
  best_of_burst: boolean
  has_recipe: boolean
}

export interface JobProgress {
  done: number
  total: number
  current: string | null
}

export interface Job {
  id: string
  kind: string
  title: string
  state: 'queued' | 'running' | 'done' | 'error'
  progress: JobProgress
  result: unknown
  error: string | null
  created: number
  started: number | null
  finished: number | null
}

export interface CloseReportItem {
  stem: string
  id: number
  motivo: string
}

export interface CloseReport {
  folder_id: number
  folder: string
  borrar: CloseReportItem[]
  pendientes: string[]
  tiff_sin_favs: string[]
  finales: number
  total_fotos: number
  trashed?: string[]
  errors?: string[]
}

export interface Health {
  ok: boolean
  root: string | null
  root_error: string | null
  folders: number
  photos: number
  version: string
}

export interface Exif {
  archivo: string
  camara: string | null
  objetivo: string | null
  expo: string | null
  f: string | null
  iso: string | null
  focal: string | null
  fecha: string | null
  dimensiones: string | null
  peso_mb: number
}

export interface CropBox {
  x: number
  y: number
  w: number
  h: number
}

export interface Recipe {
  temp: number
  tint: number
  exposure: number
  contrast: number
  highlights: number
  shadows: number
  blacks: number
  saturation: number
  vibrance: number
  sharpen: number
  rot90: number
  angle: number
  crop: CropBox | null
  curve: [number, number][] | null
}

export interface Hist {
  luma: number[]
  clip_hi: number
  clip_lo: number
}

export interface PreviewResult {
  jpeg_b64: string
  hist: Hist
  w: number
  h: number
  ms: number
}

export interface ExportResult {
  stem: string
  ok: boolean
  error?: string
  written?: string[]
}

export type FilterKey = 'all' | 'unrated' | 'best' | 'discard' | 'suspect'

export type Zoom = 'fit' | 'half' | 'full'

export type PresetKey = 'normal' | 'favorita' | 'redes' | 'impresion'
