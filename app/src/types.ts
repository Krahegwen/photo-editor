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
}

export interface ScanState {
  running: boolean
  folder: string | null
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
