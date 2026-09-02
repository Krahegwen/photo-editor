<script setup lang="ts">
import { computed, ref } from 'vue'
import { api } from '../api'
import { isRaw } from '../formats'
import type { Photo } from '../types'

const props = defineProps<{ photos: Photo[]; folderName: string }>()
const emit = defineEmits<{ close: []; started: [] }>()

const MODES = [
  { key: 'estrellas', label: 'Estrellas', hint: 'alinea el campo estelar (rotación incluida) y apila con sigma-clip' },
  { key: 'trails', label: 'Star trails', hint: 'máximo por píxel con relleno de los huecos entre disparos' },
  { key: 'luna', label: 'Luna / Sol', hint: 'detecta el disco, recorta y alinea subpíxel; sigma-clip' },
  { key: 'max', label: 'Máximo', hint: 'sin alinear, máximo por píxel crudo — composites de fuegos' },
  { key: 'media', label: 'Media', hint: 'sin alinear, media sigma-clip — reducción de ruido en escena fija' },
  { key: 'hdr', label: 'HDR', hint: 'brackets ordenados por exposición, fusión Mertens (máx. 12)' },
  { key: 'timelapse', label: 'Timelapse', hint: 'vídeo MP4 1080p desde la secuencia (mínimo 10 fotos)' },
] as const

const LABELS: Record<string, string> = {
  luna: 'apilado luna', estrellas: 'apilado estrellas', media: 'apilado media',
  max: 'apilado max', trails: 'trails', hdr: 'hdr',
}

const arws = computed(() => {
  const a = props.photos.filter((p) => isRaw(p.ext))
  return a.length ? a : props.photos
})

const mode = ref<string>('estrellas')
const desde = ref(arws.value[0]?.stem.slice(-4) ?? '')
const hasta = ref(arws.value[arws.value.length - 1]?.stem.slice(-4) ?? '')
const escala = ref('auto')
const cropPx = ref(1200)
const fps = ref(24)
const busy = ref(false)
const error = ref<string | null>(null)

const minFotos = computed(() => (mode.value === 'timelapse' ? 10 : 2))

const selected = computed(() => {
  const d = desde.value.trim().slice(-4)
  const h = hasta.value.trim().slice(-4)
  if (!d || !h) return []
  return arws.value.filter((p) => {
    const n = p.stem.slice(-4)
    return /^\d{4}$/.test(n) && d <= n && n <= h
  })
})

// intervalo horario de la selección, como lo nombra el motor (naming.py)
const spanLabel = computed(() => {
  const ts = selected.value
    .map((p) => p.taken_at)
    .filter((t): t is string => !!t)
    .sort()
  if (!ts.length) return `${desde.value || '····'}-${hasta.value || '····'}`
  const hhmm = (t: string) => t.slice(11, 16).replace(':', '')
  return `${hhmm(ts[0])}-${hhmm(ts[ts.length - 1])}`
})

async function launch() {
  if (selected.value.length < minFotos.value || busy.value) return
  busy.value = true
  error.value = null
  try {
    const ids = selected.value.map((p) => p.id)
    if (mode.value === 'timelapse') {
      await api.timelapse(ids, fps.value)
    } else {
      await api.stack(ids, mode.value, { cropPx: cropPx.value, escala: escala.value })
    }
    emit('started')
  } catch (e) {
    error.value = String(e)
    busy.value = false
  }
}
</script>

<template>
  <div class="stacker" @click.self="emit('close')">
    <div class="box">
      <div class="head">
        <b>Apilar</b>
        <span class="dim">{{ folderName }}</span>
        <span class="sp"></span>
        <button @click="emit('close')">✕</button>
      </div>

      <div class="modes">
        <label v-for="m in MODES" :key="m.key" class="mode" :class="{ on: mode === m.key }">
          <input v-model="mode" type="radio" :value="m.key" name="stackmode" />
          <b>{{ m.label }}</b>
          <span>{{ m.hint }}</span>
        </label>
      </div>

      <div class="row">
        <label>Rango</label>
        <input v-model="desde" class="num" maxlength="4" inputmode="numeric" />
        <span class="dim">a</span>
        <input v-model="hasta" class="num" maxlength="4" inputmode="numeric" />
        <span class="count" :class="{ bad: selected.length < minFotos }">
          {{ selected.length }} fotos
        </span>
      </div>

      <div v-if="mode !== 'timelapse'" class="row">
        <label>Escala</label>
        <select v-model="escala">
          <option value="auto">auto (media salvo luna/max)</option>
          <option value="completa">completa (6000 px, más disco y tiempo)</option>
          <option value="media">media (3000 px, rápida)</option>
        </select>
        <template v-if="mode === 'luna'">
          <label>Recorte</label>
          <select v-model.number="cropPx">
            <option :value="900">900 px</option>
            <option :value="1200">1200 px</option>
            <option :value="1600">1600 px</option>
          </select>
        </template>
      </div>
      <div v-else class="row">
        <label>FPS</label>
        <select v-model.number="fps">
          <option :value="12">12</option>
          <option :value="24">24</option>
          <option :value="30">30</option>
        </select>
        <span class="dim">
          ≈ {{ selected.length && fps ? (selected.length / fps).toFixed(1) : '?' }} s de vídeo
        </span>
      </div>

      <p v-if="mode !== 'timelapse'" class="dim note">
        El resultado queda como <code>{{ folderName }} - {{ LABELS[mode] }} {{ spanLabel }}.tif/jpg</code>
        en la carpeta (TIFF de 16 bits para seguir editándolo en Revelar). Los temporales van
        fuera de tus carpetas y se borran solos.
      </p>
      <p v-else class="dim note">
        El resultado queda como <code>{{ folderName }} - timelapse {{ spanLabel }} {{ fps }}fps.mp4</code>
        (1080p H.264) en la carpeta.
      </p>

      <div v-if="error" class="err">{{ error }}</div>

      <div class="foot">
        <button class="primary" :disabled="selected.length < minFotos || busy" @click="launch">
          {{
            busy
              ? 'Encolando…'
              : mode === 'timelapse'
                ? `Timelapse de ${selected.length} fotos`
                : `Apilar ${selected.length} fotos`
          }}
        </button>
        <button @click="emit('close')">Cancelar</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stacker {
  position: fixed;
  inset: 0;
  z-index: 60;
  background: rgba(10, 11, 15, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
.box {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  width: min(560px, 100%);
  max-height: 90vh;
  overflow-y: auto;
  padding: 14px 16px;
}
.head { display: flex; gap: 10px; align-items: baseline; margin-bottom: 10px; }
.dim { color: var(--dim); font-size: 12.5px; }
.sp { flex: 1; }
button, select, input {
  background: var(--panel2);
  color: var(--txt);
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 6px 10px;
  font-size: 13px;
}
button { cursor: pointer; }
button:hover:not(:disabled) { border-color: var(--acc); }
button:disabled { opacity: 0.5; cursor: default; }
button.primary { background: var(--acc); border-color: var(--acc); color: #1a1408; font-weight: 600; }
.modes { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
.mode {
  display: grid;
  grid-template-columns: auto auto 1fr;
  gap: 8px;
  align-items: baseline;
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
}
.mode span { color: var(--dim); font-size: 12px; }
.mode.on { border-color: var(--acc); background: var(--panel2); }
.mode input { accent-color: var(--acc); }
.row { display: flex; gap: 8px; align-items: center; margin: 8px 0; flex-wrap: wrap; }
.row label { color: var(--dim); font-size: 12.5px; min-width: 46px; }
.num { width: 64px; text-align: center; font-variant-numeric: tabular-nums; }
.count { font-size: 12.5px; color: var(--ok); }
.count.bad { color: var(--no); }
.note { font-size: 12px; margin: 10px 0; max-width: 60ch; }
.note code { background: var(--panel2); padding: 1px 5px; border-radius: 4px; }
.err { color: #ff9c8f; font-size: 13px; margin: 8px 0; }
.foot { display: flex; gap: 8px; margin-top: 10px; }
</style>
