/**
 * Snackbars con cola: `toast(texto, nivel)` desde cualquier sitio.
 *
 * - info / ok / warn se cierran solos (el tiempo depende del nivel y de la
 *   longitud del texto); error se queda hasta que el usuario lo cierra.
 * - Como mucho MAX_VISIBLE a la vez; el resto espera en cola y va entrando.
 * - Un mensaje idéntico al que ya está visible no se duplica: se reinicia su
 *   tiempo y se le suma un contador (×2, ×3…).
 * - Pasar el ratón por encima pausa el tiempo.
 */
import { reactive } from 'vue'

export type ToastLevel = 'info' | 'ok' | 'warn' | 'error'

export interface Toast {
  id: number
  text: string
  level: ToastLevel
  timeout: number | null
  count: number
  timer?: number
  startedAt?: number
  remaining?: number
}

const MAX_VISIBLE = 3
const BASE_MS: Record<ToastLevel, number | null> = { info: 4000, ok: 3500, warn: 8000, error: null }

let seq = 0
export const toasts = reactive({ visible: [] as Toast[], queue: [] as Toast[] })

function timeoutFor(level: ToastLevel, text: string, override?: number | null): number | null {
  if (override !== undefined) return override
  const base = BASE_MS[level]
  if (base === null) return null
  return base + Math.min(6000, Math.max(0, text.length - 40) * 35) // más texto, más tiempo
}

function arm(t: Toast) {
  if (t.timeout === null) return
  window.clearTimeout(t.timer)
  const ms = t.remaining ?? t.timeout
  t.startedAt = Date.now()
  t.remaining = ms
  t.timer = window.setTimeout(() => dismiss(t.id), ms)
}

function show(t: Toast) {
  toasts.visible.push(t)
  arm(t)
}

export function toast(text: string, level: ToastLevel = 'info', opts: { timeout?: number | null } = {}) {
  const same = toasts.visible.find((t) => t.text === text && t.level === level)
  if (same) {
    same.count += 1
    same.remaining = undefined
    arm(same)
    return same.id
  }
  const t: Toast = { id: ++seq, text, level, timeout: timeoutFor(level, text, opts.timeout), count: 1 }
  if (toasts.visible.length < MAX_VISIBLE) show(t)
  else toasts.queue.push(t)
  return t.id
}

export function dismiss(id: number) {
  const i = toasts.visible.findIndex((t) => t.id === id)
  if (i >= 0) {
    window.clearTimeout(toasts.visible[i].timer)
    toasts.visible.splice(i, 1)
  } else {
    const q = toasts.queue.findIndex((t) => t.id === id)
    if (q >= 0) toasts.queue.splice(q, 1)
  }
  const next = toasts.queue.shift()
  if (next) show(next)
}

export function dismissErrors() {
  toasts.visible.filter((t) => t.level === 'error').forEach((t) => dismiss(t.id))
  toasts.queue = toasts.queue.filter((t) => t.level !== 'error')
}

export function pause(id: number) {
  const t = toasts.visible.find((x) => x.id === id)
  if (!t || t.timeout === null || t.startedAt === undefined) return
  window.clearTimeout(t.timer)
  t.remaining = Math.max(600, (t.remaining ?? t.timeout) - (Date.now() - t.startedAt))
  t.startedAt = undefined
}

export function resume(id: number) {
  const t = toasts.visible.find((x) => x.id === id)
  if (t && t.timeout !== null && t.startedAt === undefined) arm(t)
}
