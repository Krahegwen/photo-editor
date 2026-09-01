<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, toRaw, watch } from 'vue'
import { api } from '../api'
import type { CropBox, Hist, Photo, PresetKey, Recipe } from '../types'

const props = defineProps<{ photo: Photo }>()
const emit = defineEmits<{ close: []; copy: [recipe: Recipe] }>()

const NEUTRAL: Recipe = {
  temp: 0, tint: 0, exposure: 0, contrast: 0, highlights: 0, shadows: 0,
  blacks: 0, saturation: 0, vibrance: 0, sharpen: 0, rot90: 0, angle: 0, crop: null,
}

const SLIDERS = [
  { key: 'temp', label: 'Temperatura', min: -100, max: 100, step: 1 },
  { key: 'tint', label: 'Tinte', min: -100, max: 100, step: 1 },
  { key: 'exposure', label: 'Exposición', min: -3, max: 3, step: 0.05 },
  { key: 'contrast', label: 'Contraste', min: -100, max: 100, step: 1 },
  { key: 'highlights', label: 'Altas luces', min: -100, max: 100, step: 1 },
  { key: 'shadows', label: 'Sombras', min: -100, max: 100, step: 1 },
  { key: 'blacks', label: 'Negros', min: -100, max: 100, step: 1 },
  { key: 'saturation', label: 'Saturación', min: -100, max: 100, step: 1 },
  { key: 'vibrance', label: 'Vibrance', min: -100, max: 100, step: 1 },
  { key: 'sharpen', label: 'Enfoque', min: 0, max: 100, step: 1 },
] as const

const ASPECTS: { label: string; value: number | null }[] = [
  { label: 'Libre', value: null },
  { label: '3:2', value: 3 / 2 },
  { label: '2:3', value: 2 / 3 },
  { label: '16:9', value: 16 / 9 },
  { label: '1:1', value: 1 },
  { label: '4:5', value: 4 / 5 },
]

const recipe = reactive<Recipe>({ ...NEUTRAL })
const ready = ref(false)
const previewUrl = ref('')
const baseUrl = ref('')
const showBefore = ref(false)
const hist = ref<Hist | null>(null)
const ms = ref(0)
const loading = ref(true)
const saveState = ref<'clean' | 'dirty' | 'saving' | 'saved'>('clean')
const error = ref<string | null>(null)

const cropMode = ref(false)
const cropBox = reactive<CropBox>({ x: 0.02, y: 0.02, w: 0.96, h: 0.96 })
const aspect = ref<number | null>(null)
const imgWrap = ref<HTMLElement | null>(null)
const imgEl = ref<HTMLImageElement | null>(null)
const dispRect = ref<{ left: number; top: number; w: number; h: number } | null>(null)
const natural = ref<{ w: number; h: number }>({ w: 3, h: 2 })

const histCanvas = ref<HTMLCanvasElement | null>(null)

const exportPreset = ref<PresetKey>('normal')
const exporting = ref<string | null>(null)

function plainRecipe(): Recipe {
  const r = { ...toRaw(recipe) }
  r.crop = recipe.crop ? { ...recipe.crop } : null
  return r
}

// ------------------------------------------------------------- preview

let seq = 0
async function updatePreview() {
  const my = ++seq
  loading.value = true
  try {
    const res = await api.developPreview(props.photo.id, plainRecipe(), cropMode.value)
    if (my !== seq) return
    previewUrl.value = `data:image/jpeg;base64,${res.jpeg_b64}`
    hist.value = res.hist
    ms.value = res.ms
    natural.value = { w: res.w, h: res.h }
    error.value = null
  } catch (e) {
    if (my === seq) error.value = String(e)
  } finally {
    if (my === seq) loading.value = false
  }
}

let previewTimer: number | undefined
watch(
  [() => JSON.stringify(recipe), cropMode],
  () => {
    if (!ready.value) return
    markDirty()
    window.clearTimeout(previewTimer)
    previewTimer = window.setTimeout(updatePreview, 130)
  },
)

// ------------------------------------------------------------- guardado

let saveTimer: number | undefined
function markDirty() {
  saveState.value = 'dirty'
  window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(saveNow, 900)
}

async function saveNow() {
  if (saveState.value === 'clean' || saveState.value === 'saved') return
  saveState.value = 'saving'
  try {
    await api.putRecipe(props.photo.id, plainRecipe())
    saveState.value = 'saved'
  } catch (e) {
    saveState.value = 'dirty'
    error.value = `No pude guardar la receta: ${e}`
  }
}

async function resetAll() {
  if (!window.confirm('¿Quitar toda la receta de esta foto?')) return
  window.clearTimeout(saveTimer)
  Object.assign(recipe, NEUTRAL, { crop: null })
  try {
    await api.deleteRecipe(props.photo.id)
    saveState.value = 'clean'
  } catch (e) {
    error.value = String(e)
  }
}

function resetField(key: string) {
  ;(recipe as Record<string, unknown>)[key] = (NEUTRAL as Record<string, unknown>)[key]
}

async function close() {
  window.clearTimeout(saveTimer)
  if (saveState.value === 'dirty' || saveState.value === 'saving') await saveNow()
  emit('close')
}

// ------------------------------------------------------------- histograma

watch(hist, (h) => {
  const cv = histCanvas.value
  if (!cv || !h) return
  const ctx = cv.getContext('2d')!
  const W = cv.width
  const H = cv.height
  ctx.clearRect(0, 0, W, H)
  ctx.fillStyle = 'rgba(224,163,65,.75)'
  const bw = W / h.luma.length
  h.luma.forEach((v, i) => {
    const bh = Math.max(v > 0 ? 1 : 0, v * (H - 4))
    ctx.fillRect(i * bw, H - bh, Math.max(1, bw - 0.5), bh)
  })
})

// ------------------------------------------------------------- recorte

function measure() {
  const wrap = imgWrap.value
  const img = imgEl.value
  if (!wrap || !img || !img.naturalWidth) {
    dispRect.value = null
    return
  }
  const cw = wrap.clientWidth
  const ch = wrap.clientHeight
  const sc = Math.min(cw / img.naturalWidth, ch / img.naturalHeight)
  const w = img.naturalWidth * sc
  const h = img.naturalHeight * sc
  dispRect.value = { left: (cw - w) / 2, top: (ch - h) / 2, w, h }
}

function enterCrop() {
  const c = recipe.crop
  Object.assign(cropBox, c ?? { x: 0.02, y: 0.02, w: 0.96, h: 0.96 })
  cropMode.value = true
}

function applyCrop() {
  recipe.crop = {
    x: +cropBox.x.toFixed(4),
    y: +cropBox.y.toFixed(4),
    w: +cropBox.w.toFixed(4),
    h: +cropBox.h.toFixed(4),
  }
  cropMode.value = false
}

function clearCrop() {
  recipe.crop = null
  cropMode.value = false
}

function fitAspect() {
  const a = aspect.value
  if (!a) return
  // h del recorte en coords normalizadas para el aspecto pedido (px reales)
  const { w: W, h: H } = natural.value
  let h = (cropBox.w * W) / (a * H)
  if (h > 1 - cropBox.y) {
    h = 1 - cropBox.y
    cropBox.w = (h * H * a) / W
  }
  cropBox.h = h
}

type DragMode = 'move' | 'nw' | 'ne' | 'sw' | 'se'
let drag: { mode: DragMode; sx: number; sy: number; b: CropBox } | null = null

function startDrag(e: PointerEvent, mode: DragMode) {
  e.preventDefault()
  e.stopPropagation()
  ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
  drag = { mode, sx: e.clientX, sy: e.clientY, b: { ...cropBox } }
}

function onDrag(e: PointerEvent) {
  if (!drag || !dispRect.value) return
  const R = dispRect.value
  const dx = (e.clientX - drag.sx) / R.w
  const dy = (e.clientY - drag.sy) / R.h
  const b = drag.b
  const MIN = 0.05
  const { w: W, h: H } = natural.value
  const a = aspect.value

  if (drag.mode === 'move') {
    cropBox.x = Math.min(Math.max(0, b.x + dx), 1 - b.w)
    cropBox.y = Math.min(Math.max(0, b.y + dy), 1 - b.h)
    return
  }
  let x = b.x
  let y = b.y
  let w = b.w
  let h = b.h
  if (drag.mode === 'se') {
    w = Math.min(Math.max(MIN, b.w + dx), 1 - b.x)
    h = Math.min(Math.max(MIN, b.h + dy), 1 - b.y)
  } else if (drag.mode === 'ne') {
    w = Math.min(Math.max(MIN, b.w + dx), 1 - b.x)
    const y1 = b.y + b.h
    h = Math.min(Math.max(MIN, b.h - dy), y1)
    y = y1 - h
  } else if (drag.mode === 'sw') {
    const x1 = b.x + b.w
    w = Math.min(Math.max(MIN, b.w - dx), x1)
    x = x1 - w
    h = Math.min(Math.max(MIN, b.h + dy), 1 - b.y)
  } else {
    const x1 = b.x + b.w
    const y1 = b.y + b.h
    w = Math.min(Math.max(MIN, b.w - dx), x1)
    x = x1 - w
    h = Math.min(Math.max(MIN, b.h - dy), y1)
    y = y1 - h
  }
  if (a) {
    h = (w * W) / (a * H)
    if (drag.mode === 'ne' || drag.mode === 'nw') y = b.y + b.h - h
    if (y < 0 || y + h > 1) {
      h = Math.min(h, drag.mode === 'ne' || drag.mode === 'nw' ? b.y + b.h : 1 - y)
      w = (h * H * a) / W
      if (drag.mode === 'sw' || drag.mode === 'nw') x = b.x + b.w - w
      if (drag.mode === 'ne' || drag.mode === 'nw') y = b.y + b.h - h
    }
  }
  cropBox.x = Math.max(0, x)
  cropBox.y = Math.max(0, y)
  cropBox.w = Math.min(w, 1 - cropBox.x)
  cropBox.h = Math.min(h, 1 - cropBox.y)
}

function endDrag() {
  drag = null
}

const cropStyle = computed(() => {
  const R = dispRect.value
  if (!R) return {}
  return {
    left: `${R.left + cropBox.x * R.w}px`,
    top: `${R.top + cropBox.y * R.h}px`,
    width: `${cropBox.w * R.w}px`,
    height: `${cropBox.h * R.h}px`,
  }
})

// ------------------------------------------------------------- exportar

async function exportThis() {
  exporting.value = 'exportando…'
  try {
    await saveNow()
    await api.export([props.photo.id], exportPreset.value)
    for (;;) {
      await new Promise((r) => setTimeout(r, 800))
      const s = await api.exportStatus()
      if (!s.running) {
        const r0 = s.results[0]
        exporting.value = r0?.ok
          ? `✔ ${r0.written?.join(' · ')}`
          : `✖ ${r0?.error ?? s.error ?? 'error'}`
        break
      }
      exporting.value = `exportando… ${s.done}/${s.total}`
    }
  } catch (e) {
    exporting.value = `✖ ${e}`
  }
}

// ------------------------------------------------------------- teclado / ciclo

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    if (cropMode.value) cropMode.value = false
    else void close()
  } else if (e.key === 'b' || e.key === 'B') {
    showBefore.value = !showBefore.value
  }
}

onMounted(async () => {
  window.addEventListener('keydown', onKey)
  window.addEventListener('resize', measure)
  try {
    const { recipe: saved, defaults } = await api.getRecipe(props.photo.id)
    Object.assign(recipe, defaults, saved ?? {})
    const base = await api.developPreview(props.photo.id, { ...NEUTRAL }, false)
    baseUrl.value = `data:image/jpeg;base64,${base.jpeg_b64}`
    ready.value = true
    await updatePreview()
  } catch (e) {
    error.value = String(e)
    ready.value = true
  }
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('resize', measure)
  window.clearTimeout(previewTimer)
  window.clearTimeout(saveTimer)
})
</script>

<template>
  <div class="dev">
    <div class="topbar">
      <b>{{ photo.stem }}{{ photo.ext }}</b>
      <span class="dim">{{ ms }} ms</span>
      <span
        class="dim save"
        :class="{ ok: saveState === 'saved' }"
      >{{
        saveState === 'saving' ? 'guardando…'
        : saveState === 'saved' ? 'receta guardada ✔'
        : saveState === 'dirty' ? 'sin guardar' : ''
      }}</span>
      <span class="sp"></span>
      <button :class="{ on: showBefore }" title="Antes/después (B)" @click="showBefore = !showBefore">
        Antes
      </button>
      <button @click="emit('copy', plainRecipe())">Copiar receta</button>
      <button @click="resetAll">Restablecer</button>
      <select v-model="exportPreset" title="Preset de exportación">
        <option value="normal">Normal (4K q95)</option>
        <option value="favorita">Favorita (TIFF16+JPG → FAVS)</option>
        <option value="redes">Redes (2048)</option>
        <option value="impresion">Impresión (q100 300dpi)</option>
      </select>
      <button @click="exportThis">Exportar</button>
      <button title="Cerrar (Esc)" @click="close">✕</button>
    </div>

    <div v-if="exporting" class="exportline" @click="exporting = null">{{ exporting }}</div>
    <div v-if="error" class="err" @click="error = null">{{ error }}</div>

    <div class="body">
      <div ref="imgWrap" class="imgwrap">
        <img
          ref="imgEl"
          :src="showBefore && !cropMode ? baseUrl : previewUrl"
          alt=""
          @load="measure"
        />
        <div v-if="loading" class="loading">revelando…</div>
        <div v-if="showBefore && !cropMode" class="beforetag">ANTES</div>

        <template v-if="cropMode && dispRect">
          <div
            class="cropbox"
            :style="cropStyle"
            @pointerdown="startDrag($event, 'move')"
            @pointermove="onDrag"
            @pointerup="endDrag"
          >
            <span
              v-for="m in (['nw', 'ne', 'sw', 'se'] as const)"
              :key="m"
              class="handle"
              :class="m"
              @pointerdown="startDrag($event, m)"
              @pointermove="onDrag"
              @pointerup="endDrag"
            ></span>
          </div>
        </template>
      </div>

      <aside class="panel">
        <canvas ref="histCanvas" width="252" height="72" class="hist"></canvas>
        <div v-if="hist" class="clips">
          <span :class="{ warn: hist.clip_lo > 0.001 }">◤ {{ (hist.clip_lo * 100).toFixed(1) }}%</span>
          <span class="dim">recorte</span>
          <span :class="{ warn: hist.clip_hi > 0.001 }">{{ (hist.clip_hi * 100).toFixed(1) }}% ◥</span>
        </div>

        <div v-for="s in SLIDERS" :key="s.key" class="slider" @dblclick="resetField(s.key)">
          <div class="srow">
            <label :for="`sl-${s.key}`">{{ s.label }}</label>
            <span class="val">{{ (recipe as Record<string, unknown>)[s.key] }}</span>
          </div>
          <input
            :id="`sl-${s.key}`"
            v-model.number="(recipe as Record<string, any>)[s.key]"
            type="range"
            :min="s.min"
            :max="s.max"
            :step="s.step"
          />
        </div>

        <div class="geom">
          <div class="srow"><label>Geometría</label></div>
          <div class="geombtns">
            <button title="Girar 90° izquierda" @click="recipe.rot90 = (recipe.rot90 + 1) % 4">⟲</button>
            <button title="Girar 90° derecha" @click="recipe.rot90 = (recipe.rot90 + 3) % 4">⟳</button>
            <button v-if="!cropMode" :class="{ on: !!recipe.crop }" @click="enterCrop">
              {{ recipe.crop ? 'Recorte ✔' : 'Recortar' }}
            </button>
          </div>
          <div class="srow" @dblclick="recipe.angle = 0">
            <label for="sl-angle">Enderezar</label>
            <span class="val">{{ recipe.angle.toFixed(1) }}°</span>
          </div>
          <input id="sl-angle" v-model.number="recipe.angle" type="range" min="-15" max="15" step="0.1" />
        </div>

        <div v-if="cropMode" class="cropctl">
          <div class="aspects">
            <button
              v-for="a in ASPECTS"
              :key="a.label"
              :class="{ on: aspect === a.value }"
              @click="aspect = a.value; fitAspect()"
            >{{ a.label }}</button>
          </div>
          <div class="cropacts">
            <button class="primary" @click="applyCrop">Aplicar recorte</button>
            <button v-if="recipe.crop" @click="clearCrop">Quitar</button>
            <button @click="cropMode = false">Cancelar</button>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.dev {
  position: fixed;
  inset: 0;
  z-index: 55;
  background: var(--bg);
  display: flex;
  flex-direction: column;
}
.topbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
  font-size: 13.5px;
  flex-wrap: wrap;
}
.dim { color: var(--dim); font-size: 12px; }
.save.ok { color: var(--ok); }
.sp { flex: 1; }
button, select {
  background: var(--panel2);
  color: var(--txt);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 5px 10px;
  font-size: 13px;
  cursor: pointer;
}
button:hover { border-color: var(--acc); }
button.on { background: var(--acc); color: #1a1408; border-color: var(--acc); font-weight: 600; }
button.primary { background: var(--ok); border-color: var(--ok); color: #fff; font-weight: 600; }
.exportline {
  padding: 6px 14px;
  font-size: 12.5px;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
  color: var(--ok);
  cursor: pointer;
}
.err { color: #ff9c8f; padding: 6px 14px; font-size: 13px; cursor: pointer; }

.body { flex: 1; min-height: 0; display: flex; }
.imgwrap {
  flex: 1;
  min-width: 0;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.imgwrap img { max-width: 100%; max-height: 100%; object-fit: contain; user-select: none; }
.loading {
  position: absolute;
  top: 10px;
  left: 50%;
  transform: translateX(-50%);
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 3px 10px;
  font-size: 12px;
  color: var(--dim);
}
.beforetag {
  position: absolute;
  top: 10px;
  left: 10px;
  background: var(--acc);
  color: #1a1408;
  font-weight: 700;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  letter-spacing: 0.08em;
}
.cropbox {
  position: absolute;
  border: 2px solid var(--acc);
  box-shadow: 0 0 0 9999px rgba(10, 11, 15, 0.45);
  cursor: move;
  touch-action: none;
}
.handle {
  position: absolute;
  width: 14px;
  height: 14px;
  background: var(--acc);
  border-radius: 3px;
  touch-action: none;
}
.handle.nw { left: -7px; top: -7px; cursor: nwse-resize; }
.handle.ne { right: -7px; top: -7px; cursor: nesw-resize; }
.handle.sw { left: -7px; bottom: -7px; cursor: nesw-resize; }
.handle.se { right: -7px; bottom: -7px; cursor: nwse-resize; }

.panel {
  width: 284px;
  border-left: 1px solid var(--line);
  background: var(--panel);
  padding: 12px 16px 20px;
  overflow-y: auto;
}
.hist {
  width: 100%;
  height: 72px;
  background: var(--panel2);
  border: 1px solid var(--line);
  border-radius: 6px;
  display: block;
}
.clips {
  display: flex;
  justify-content: space-between;
  font-size: 11.5px;
  color: var(--dim);
  margin: 4px 0 12px;
}
.clips .warn { color: var(--no); font-weight: 700; }
.slider { margin: 8px 0; }
.srow { display: flex; justify-content: space-between; align-items: baseline; }
.srow label { font-size: 12.5px; color: var(--dim); }
.val { font-size: 12px; color: var(--txt); font-variant-numeric: tabular-nums; }
input[type='range'] { width: 100%; accent-color: var(--acc); }
.geom { margin-top: 14px; border-top: 1px solid var(--line); padding-top: 10px; }
.geombtns { display: flex; gap: 6px; margin: 6px 0; }
.cropctl { margin-top: 12px; border-top: 1px solid var(--line); padding-top: 10px; }
.aspects { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 8px; }
.aspects button { padding: 4px 9px; font-size: 12px; }
.cropacts { display: flex; gap: 6px; flex-wrap: wrap; }

@media (max-width: 720px) {
  .body { flex-direction: column; }
  .imgwrap { min-height: 45vh; }
  .panel { width: auto; border-left: 0; border-top: 1px solid var(--line); }
}
</style>
