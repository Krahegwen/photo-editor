// Espejo de engine/photoeditor/formats.py
export const RAW_EXTS = new Set([
  '.arw', '.dng', '.rw2', '.cr2', '.cr3', '.nef', '.nrw', '.raf', '.orf', '.pef', '.srw',
])

export const isRaw = (ext: string) => RAW_EXTS.has(ext.toLowerCase())
