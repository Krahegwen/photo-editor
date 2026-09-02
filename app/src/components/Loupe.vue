<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '../api'
import type { Exif, Photo, Zoom } from '../types'

const props = defineProps<{ photo: Photo; index: number; total: number }>()
const emit = defineEmits<{ close: []; prev: []; next: []; rate: [n: number]; develop: [] }>()

const zoom = ref<Zoom>('fit')
const showExif = ref(true)
const loading = ref(true)
const exif = ref<Exif | null>(null)

const src = computed(() => {
  const s = zoom.value === 'fit' ? 1600 : zoom.value === 'half' ? 3000 : 6000
  return `/api/preview/${props.photo.id}?s=${s}`
})

watch(src, () => (loading.value = true))
watch(
  () => props.photo.id,
  async (id) => {
    exif.value = null
    try {
      exif.value = await api.exif(id)
    } catch {
      exif.value = null
    }
  },
  { immediate: true },
)

function cycleZoom() {
  zoom.value = zoom.value === 'fit' ? 'half' : zoom.value === 'half' ? 'full' : 'fit'
}
function toggleExif() {
  showExif.value = !showExif.value
}
defineExpose({ cycleZoom, toggleExif })

const exifRows = computed(() => {
  const e = exif.value
  if (!e) return []
  return [
    ['Cámara', e.camara],
    ['Objetivo', e.objetivo],
    ['Expo', e.expo && `${e.expo} s`],
    ['Diafragma', e.f],
    ['ISO', e.iso],
    ['Focal', e.focal],
    ['Fecha', e.fecha],
    ['Tamaño', e.dimensiones],
    ['Peso', `${e.peso_mb} MB`],
  ].filter(([, v]) => v) as [string, string][]
})
</script>

<template>
  <div class="loupe">
    <div class="topbar">
      <div class="left">
        <b>{{ photo.stem }}{{ photo.ext }}</b>
        <span v-if="(photo.formats?.length ?? 0) > 1" class="dim" title="Versiones de esta foto">
          + {{ photo.formats.slice(1).join(' · ') }}
        </span>
        <span class="dim">{{ index + 1 }} / {{ total }}</span>
        <span v-for="fl in photo.flags" :key="fl" class="flag">{{ fl }}</span>
      </div>
      <div class="ratebtns">
        <button
          v-for="n in 5"
          :key="n"
          class="star"
          :class="{ on: (photo.rating ?? 0) >= n }"
          :title="`${n}★`"
          @click="emit('rate', n)"
        >★</button>
        <button class="clear" title="Quitar puntuación (0)" @click="emit('rate', 0)">0</button>
        <button
          class="x"
          :class="{ on: photo.rating === 1 }"
          title="Marcar descarte (X = 1★)"
          @click="emit('rate', photo.rating === 1 ? 0 : 1)"
        >✕</button>
      </div>
      <div class="right">
        <div class="zoombtns">
          <button :class="{ on: zoom === 'fit' }" @click="zoom = 'fit'">Ajustar</button>
          <button :class="{ on: zoom === 'half' }" @click="zoom = 'half'">50%</button>
          <button :class="{ on: zoom === 'full' }" @click="zoom = 'full'">100%</button>
        </div>
        <button title="Revelar (D)" @click="emit('develop')">Revelar</button>
        <button title="Info EXIF (I)" @click="toggleExif">ℹ</button>
        <button title="Cerrar (Esc)" @click="emit('close')">✕</button>
      </div>
    </div>

    <div class="body">
      <button class="navbtn left" title="Anterior (←)" @click="emit('prev')">‹</button>
      <div class="imgwrap" :class="{ zoomed: zoom !== 'fit' }">
        <img :src="src" :alt="photo.stem" @load="loading = false" @error="loading = false" />
        <div v-if="loading" class="loading">
          {{ zoom === 'fit' ? 'cargando…' : 'revelando…' }}
        </div>
      </div>
      <button class="navbtn right" title="Siguiente (→)" @click="emit('next')">›</button>

      <aside v-if="showExif" class="exif">
        <div v-for="[k, v] in exifRows" :key="k" class="row">
          <span class="k">{{ k }}</span><span class="v">{{ v }}</span>
        </div>
        <div v-if="photo.sharp != null" class="row">
          <span class="k">Nitidez</span><span class="v">{{ Math.round(photo.sharp) }}</span>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.loupe {
  position: fixed;
  inset: 0;
  z-index: 50;
  background: rgba(10, 11, 15, 0.96);
  display: flex;
  flex-direction: column;
}
.topbar {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
  font-size: 13.5px;
}
.topbar .left, .topbar .right { display: flex; align-items: center; gap: 8px; min-width: 0; }
.topbar .right { justify-self: end; }
.topbar .ratebtns { justify-self: center; }
@media (max-width: 720px) {
  .topbar { display: flex; flex-wrap: wrap; }
  .topbar .ratebtns { order: 3; width: 100%; justify-content: center; }
}
.dim { color: var(--dim); font-size: 12.5px; }
.sp { flex: 1; }
.flag {
  font-size: 11px;
  color: #ffb38a;
  border: 1px solid #7a4a33;
  border-radius: 4px;
  padding: 0 5px;
}
button {
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
.zoombtns, .ratebtns { display: flex; gap: 4px; }
.star { padding: 3px 10px; font-size: 20px; line-height: 1.2; color: var(--dim); }
.star.on { background: var(--panel2); color: var(--acc); border-color: var(--acc); }
.ratebtns .clear, .ratebtns .x { padding: 5px 10px; font-size: 14px; }
.x.on { background: var(--no); border-color: var(--no); color: #fff; }
.body {
  flex: 1;
  min-height: 0;
  display: flex;
  position: relative;
}
.imgwrap {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}
.imgwrap img { max-width: 100%; max-height: 100%; object-fit: contain; }
.imgwrap.zoomed { display: block; overflow: auto; }
.imgwrap.zoomed img { max-width: none; max-height: none; }
.loading {
  position: absolute;
  top: 12px;
  left: 50%;
  transform: translateX(-50%);
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 4px 12px;
  font-size: 12.5px;
  color: var(--dim);
}
.navbtn {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  z-index: 5;
  font-size: 26px;
  padding: 10px 14px;
  opacity: 0.75;
}
.navbtn:hover { opacity: 1; }
.navbtn.left { left: 12px; }
.navbtn.right { right: 12px; }
.exif {
  width: 230px;
  border-left: 1px solid var(--line);
  background: var(--panel);
  padding: 14px;
  overflow-y: auto;
  font-size: 13px;
}
.exif .row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 4px 0;
  border-bottom: 1px solid var(--line);
}
.exif .k { color: var(--dim); }
.exif .v { text-align: right; }

@media (max-width: 720px) {
  .exif {
    position: absolute;
    right: 0;
    top: 0;
    bottom: 0;
    width: min(230px, 75vw);
    background: rgba(27, 30, 38, 0.96);
  }
}
</style>
