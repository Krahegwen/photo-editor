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
}

export interface ScanState {
  running: boolean
  folder: string | null
  done: number
  total: number
  error: string | null
  finished_at: number | null
}

export interface MetricsState {
  running: boolean
  folder_id: number | null
  done: number
  total: number
  error: string | null
  finished_at: number | null
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

export type FilterKey = 'all' | 'unrated' | 'best' | 'discard' | 'suspect'

export type Zoom = 'fit' | 'half' | 'full'
