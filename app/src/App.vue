<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from './api'
import CloseFolder from './components/CloseFolder.vue'
import DeleteReview from './components/DeleteReview.vue'
import Develop from './components/Develop.vue'
import Loupe from './components/Loupe.vue'
import PhotoCard from './components/PhotoCard.vue'
import type { FilterKey, Folder, Health, Job, Photo, PresetKey, Recipe } from './types'

const health = ref<Health | null>(null)
const folders = ref<Folder[]>([])
const current = ref<Folder | null>(null)
const photos = ref<Photo[]>([])
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const loadingPhotos = ref(false)

const filter = ref<FilterKey>('all')
const selIdx = ref(0)
const loupeOpen = ref(false)
const loupeIdx = ref(0)
const deleteOpen = ref(false)
const closeOpen = ref(false)
const gridEl = ref<HTMLElement | null>(null)
const loupeRef = ref<InstanceType<typeof Loupe> | null>(null)

const developOpen = ref(false)
const copiedRecipe = ref<Recipe | null>(null)
const exportPreset = ref<PresetKey>('normal')

const developPhoto = computed(() =>
  loupeOpen.value ? filtered.value[loupeIdx.value] : filtered.value[selIdx.value],
)

// ------------------------------------------------------------- trabajos

const jobs = ref<Job[]>([])
const activeJobs = computed(() =>
  jobs.value.filter((j) => j.state === 'queued' || j.state === 'running'),
)
const runningKind = (kind: string) => activeJobs.value.some((j) => j.kind === kind)
const runningJob = (kind: string) => activeJobs.value.find((j) => j.kind === kind)

let jobsTimer: number | undefined
let jobsWereActive = false

async function refreshJobs() {
  window.clearTimeout(jobsTimer)
  try {
    jobs.value = await api.jobs(8)
  } catch {
    return
  }
  if (activeJobs.value.length) {
    jobsWereActive = true
    jobsTimer = window.setTimeout(refreshJobs, 1200)
  } else if (jobsWereActive) {
    jobsWereActive = false
    const failed = jobs.value.filter((j) => j.state === 'error').slice(0, 2)
    if (failed.length) {
      error.value = failed.map((j) => `${j.title}: ${j.error}`).join(' · ')
    }
    notice.value = 'Trabajos terminados'
    await loadFolders()
    await reloadPhotos()
  }
}

// ------------------------------------------------------------- datos

async function loadFolders() {
  folders.value = await api.folders()
  if (current.value) {
    const again = folders.value.find((f) => f.id === current.value!.id)
    if (again) {
      current.value = again
      return
    }
  }
  if (folders.value.length) await select(folders.value[0])
}

async function select(f: Folder) {
  current.value = f
  filter.value = 'all'
  selIdx.value = 0
  loadingPhotos.value = true
  try {
    photos.value = await api.photos(f.id)
  } finally {
    loadingPhotos.value = false
  }
}

async function reloadPhotos() {
  if (!current.value) return
  const keep = filtered.value[selIdx.value]?.id
  photos.value = await api.photos(current.value.id)
  await nextTick()
  if (keep != null) {
    const i = filtered.value.findIndex((p) => p.id === keep)
    selIdx.value = i >= 0 ? i : Math.min(selIdx.value, Math.max(0, filtered.value.length - 1))
  }
}

// ------------------------------------------------------------- filtros

const filtered = computed(() => {
  const ps = photos.value
  switch (filter.value) {
    case 'unrated':
      return ps.filter((p) => !p.rating)
    case 'best':
      return ps.filter((p) => (p.rating ?? 0) >= 4)
    case 'discard':
      return ps.filter((p) => p.rating === 1)
    case 'suspect':
      return ps.filter((p) => p.flags.length > 0)
    default:
      return ps
  }
})

const counts = computed(() => ({
  all: photos.value.length,
  unrated: photos.value.filter((p) => !p.rating).length,
  best: photos.value.filter((p) => (p.rating ?? 0) >= 4).length,
  discard: photos.value.filter((p) => p.rating === 1).length,
  suspect: photos.value.filter((p) => p.flags.length > 0).length,
}))

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: 'Todas' },
  { key: 'unrated', label: 'Sin puntuar' },
  { key: 'best', label: '★≥4' },
  { key: 'discard', label: '1★' },
  { key: 'suspect', label: 'Sospechosas' },
]

watch(filtered, (list) => {
  if (selIdx.value >= list.length) selIdx.value = Math.max(0, list.length - 1)
  if (loupeIdx.value >= list.length) loupeIdx.value = Math.max(0, list.length - 1)
  if (loupeOpen.value && !list.length) loupeOpen.value = false
})

// ------------------------------------------------------------- rating

async function rate(photo: Photo, n: number) {
  const prev = photo.rating
  photo.rating = n > 0 ? n : null
  try {
    const res = await api.rate([{ photo_id: photo.id, rating: n }])
    const r = res.results[0]
    if (!r?.ok) throw new Error(r?.error ?? 'error desconocido')
  } catch (e) {
    photo.rating = prev
    error.value = `No pude guardar el rating: ${e}`
  }
}

async function markSuspects() {
  const targets = filtered.value.filter((p) => !p.rating)
  if (!targets.length) return
  if (!window.confirm(`¿Marcar ${targets.length} sospechosas sin puntuar con 1★?`)) return
  await api.rate(targets.map((p) => ({ photo_id: p.id, rating: 1 })))
  await reloadPhotos()
}

// ------------------------------------------------------------- acciones (jobs)

async function startScan() {
  error.value = null
  try {
    await api.scan()
    await refreshJobs()
  } catch (e) {
    error.value = String(e)
  }
}

async function startMetrics() {
  if (!current.value) return
  error.value = null
  try {
    await api.metrics(current.value.id)
    await refreshJobs()
  } catch (e) {
    error.value = String(e)
  }
}

async function startExport() {
  if (!filtered.value.length || runningKind('export')) return
  if (!window.confirm(`¿Exportar ${filtered.value.length} fotos con el preset «${exportPreset.value}»?`))
    return
  error.value = null
  try {
    await api.export(filtered.value.map((p) => p.id), exportPreset.value)
    await refreshJobs()
  } catch (e) {
    error.value = String(e)
  }
}

// ------------------------------------------------------------- receta en lote

async function closeDevelop() {
  developOpen.value = false
  await reloadPhotos()
}

function onCopyRecipe(r: Recipe) {
  copiedRecipe.value = r
  notice.value = 'Receta copiada — pégala desde la barra de filtros'
}

async function pasteRecipe() {
  const r = copiedRecipe.value
  if (!r || !filtered.value.length) return
  if (!window.confirm(`¿Aplicar la receta copiada a ${filtered.value.length} fotos del filtro actual?`))
    return
  const res = await api.copyRecipe(r, filtered.value.map((p) => p.id))
  const bad = res.results.filter((x) => !x.ok).length
  notice.value = `Receta aplicada a ${res.results.length - bad} fotos${bad ? ` · ${bad} errores` : ''}`
  await reloadPhotos()
}

// ------------------------------------------------------------- borrado

function onDeleted(trashed: string[], errors: string[]) {
  deleteOpen.value = false
  notice.value = `${trashed.length} fotos enviadas a la papelera${
    errors.length ? ` · ${errors.length} errores` : ''
  }`
  if (errors.length) error.value = errors.join(' · ')
  reloadPhotos()
  loadFolders()
}

function onCloseFolderStarted() {
  closeOpen.value = false
  refreshJobs()
}

// ------------------------------------------------------------- selección y teclado

function selectAt(i: number) {
  selIdx.value = i
}

function openLoupe(i: number) {
  loupeIdx.value = i
  loupeOpen.value = true
}

function closeLoupe() {
  loupeOpen.value = false
  selIdx.value = loupeIdx.value
  nextTick(scrollSelIntoView)
}

function cols(): number {
  const g = gridEl.value
  if (!g) return 4
  return getComputedStyle(g).gridTemplateColumns.split(' ').length
}

function move(d: number) {
  if (!filtered.value.length) return
  selIdx.value = Math.max(0, Math.min(filtered.value.length - 1, selIdx.value + d))
  scrollSelIntoView()
}

function scrollSelIntoView() {
  gridEl.value?.children[selIdx.value]?.scrollIntoView({ block: 'nearest' })
}

function onKey(e: KeyboardEvent) {
  if (e.target instanceof HTMLElement && ['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return
  if (e.ctrlKey || e.metaKey || e.altKey) return

  if (deleteOpen.value) {
    if (e.key === 'Escape') deleteOpen.value = false
    return
  }
  if (closeOpen.value) {
    if (e.key === 'Escape') closeOpen.value = false
    return
  }
  if (developOpen.value) return // Develop gestiona su propio teclado

  const list = filtered.value
  const ph = loupeOpen.value ? list[loupeIdx.value] : list[selIdx.value]

  if (ph && e.key >= '0' && e.key <= '5') {
    rate(ph, Number(e.key))
    e.preventDefault()
    return
  }
  if (ph && (e.key === 'x' || e.key === 'X')) {
    rate(ph, ph.rating === 1 ? 0 : 1)
    e.preventDefault()
    return
  }
  if (ph && (e.key === 'd' || e.key === 'D')) {
    developOpen.value = true
    e.preventDefault()
    return
  }

  if (loupeOpen.value) {
    if (e.key === 'Escape') closeLoupe()
    else if (e.key === 'ArrowLeft') loupeIdx.value = Math.max(0, loupeIdx.value - 1)
    else if (e.key === 'ArrowRight')
      loupeIdx.value = Math.min(list.length - 1, loupeIdx.value + 1)
    else if (e.key === 'f' || e.key === 'F') loupeRef.value?.cycleZoom()
    else if (e.key === 'i' || e.key === 'I') loupeRef.value?.toggleExif()
    else return
    e.preventDefault()
    return
  }

  if (e.key === 'ArrowLeft') move(-1)
  else if (e.key === 'ArrowRight') move(1)
  else if (e.key === 'ArrowUp') move(-cols())
  else if (e.key === 'ArrowDown') move(cols())
  else if (e.key === 'Enter' && ph) openLoupe(selIdx.value)
  else return
  e.preventDefault()
}

onMounted(async () => {
  window.addEventListener('keydown', onKey)
  try {
    health.value = await api.health()
    await loadFolders()
    await refreshJobs()
  } catch (e) {
    error.value = String(e)
  }
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  window.clearTimeout(jobsTimer)
})
</script>

<template>
  <div class="layout">
    <aside>
      <div class="brand">photo<span>-editor</span></div>
      <div class="scanbox">
        <button :disabled="runningKind('scan')" @click="startScan">
          {{ runningKind('scan') ? 'Escaneando…' : 'Escanear archivo' }}
        </button>
      </div>
      <nav>
        <button
          v-for="f in folders"
          :key="f.id"
          class="folder"
          :class="{ on: current?.id === f.id }"
          @click="select(f)"
        >
          <span class="fname">{{ f.name }}</span>
          <span class="fcount">{{ f.photo_count }}</span>
        </button>
      </nav>
      <div v-if="jobs.length" class="jobsbox">
        <div
          v-for="j in jobs.slice(0, 5)"
          :key="j.id"
          class="jobrow"
          :class="j.state"
          :title="j.error ?? j.title"
        >
          <span class="jt">{{ j.title }}</span>
          <span class="js">{{
            j.state === 'running'
              ? j.progress.total
                ? `${j.progress.done}/${j.progress.total}`
                : '…'
              : j.state === 'queued'
                ? 'cola'
                : j.state === 'done'
                  ? '✔'
                  : '✖'
          }}</span>
        </div>
      </div>
    </aside>

    <main>
      <header>
        <h1>{{ current?.name ?? 'Sin carpeta' }}</h1>
        <span v-if="current" class="dim">{{ filtered.length }} fotos</span>
        <span class="spacer"></span>
        <span v-if="health" class="dim">
          catálogo: {{ health.photos }} fotos en {{ health.folders }} carpetas
        </span>
      </header>

      <div class="toolbar">
        <button
          v-for="f in FILTERS"
          :key="f.key"
          class="pill"
          :class="{ on: filter === f.key }"
          @click="filter = f.key; selIdx = 0"
        >
          {{ f.label }} <b>{{ counts[f.key] }}</b>
        </button>
        <span class="spacer"></span>
        <button
          v-if="filter === 'suspect' && filtered.some((p) => !p.rating)"
          class="pill warn"
          @click="markSuspects"
        >
          Marcar sin puntuar con 1★
        </button>
        <button class="pill" :disabled="runningKind('metrics') || !current" @click="startMetrics">
          {{
            runningKind('metrics')
              ? `Analizando ${runningJob('metrics')?.progress.done ?? 0}/${runningJob('metrics')?.progress.total || '?'}…`
              : 'Analizar nitidez'
          }}
        </button>
        <button
          class="pill"
          :disabled="!filtered.length"
          title="Revelar la foto seleccionada (D)"
          @click="developOpen = true"
        >
          Revelar
        </button>
        <button
          v-if="copiedRecipe"
          class="pill warn"
          :disabled="!filtered.length"
          @click="pasteRecipe"
        >
          Pegar receta a {{ filtered.length }}
        </button>
        <select v-model="exportPreset" class="pillsel" title="Preset de exportación">
          <option value="normal">Normal 4K</option>
          <option value="favorita">Favorita → FAVS</option>
          <option value="redes">Redes 2048</option>
          <option value="impresion">Impresión q100</option>
        </select>
        <button
          class="pill"
          :disabled="!filtered.length || runningKind('export')"
          @click="startExport"
        >
          {{
            runningKind('export')
              ? `Exportando ${runningJob('export')?.progress.done ?? 0}/${runningJob('export')?.progress.total || '?'}…`
              : `Exportar ${filtered.length}`
          }}
        </button>
        <button class="pill" :disabled="!current || runningKind('close')" @click="closeOpen = true">
          Cerrar carpeta
        </button>
        <button class="pill danger" :disabled="!counts.discard" @click="deleteOpen = true">
          Revisar descartes <b>{{ counts.discard }}</b>
        </button>
      </div>

      <div v-if="notice" class="notice" @click="notice = null">{{ notice }}</div>
      <div v-if="error" class="err big" @click="error = null">{{ error }}</div>

      <div v-if="health && !health.ok" class="err big">{{ health.root_error }}</div>
      <div v-else-if="!folders.length && !loadingPhotos" class="empty">
        Catálogo vacío — pulsa «Escanear archivo» para indexar tus carpetas.
      </div>
      <div v-else-if="loadingPhotos" class="empty">Cargando…</div>
      <div v-else-if="!filtered.length" class="empty">Nada con este filtro.</div>
      <div v-else ref="gridEl" class="grid">
        <PhotoCard
          v-for="(p, i) in filtered"
          :key="p.id"
          :photo="p"
          :selected="i === selIdx"
          @select="selectAt(i)"
          @open="openLoupe(i)"
        />
      </div>

      <footer class="keys">
        ← → ↑ ↓ moverse · 1-5 estrellas · 0 quitar · X descartar (1★) · D revelar · Enter lupa ·
        F zoom · I info · Esc cerrar
      </footer>
    </main>

    <Loupe
      v-if="loupeOpen && filtered[loupeIdx]"
      ref="loupeRef"
      :photo="filtered[loupeIdx]"
      :index="loupeIdx"
      :total="filtered.length"
      @close="closeLoupe"
      @prev="loupeIdx = Math.max(0, loupeIdx - 1)"
      @next="loupeIdx = Math.min(filtered.length - 1, loupeIdx + 1)"
      @rate="(n) => rate(filtered[loupeIdx], n)"
      @develop="developOpen = true"
    />

    <Develop
      v-if="developOpen && developPhoto"
      :photo="developPhoto"
      @close="closeDevelop"
      @copy="onCopyRecipe"
    />

    <DeleteReview
      v-if="deleteOpen && current"
      :photos="photos.filter((p) => p.rating === 1)"
      :folder-name="current.name"
      @close="deleteOpen = false"
      @done="onDeleted"
    />

    <CloseFolder
      v-if="closeOpen && current"
      :folder="current"
      @close="closeOpen = false"
      @started="onCloseFolderStarted"
    />
  </div>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 290px minmax(0, 1fr);
  height: 100%;
}
aside {
  background: var(--panel);
  border-right: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.brand {
  padding: 14px 16px 10px;
  font-weight: 700;
  letter-spacing: 0.4px;
  font-size: 15px;
}
.brand span { color: var(--acc); }
.scanbox { padding: 0 12px 12px; border-bottom: 1px solid var(--line); }
.scanbox button {
  width: 100%;
  background: var(--panel2);
  color: var(--txt);
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 8px;
  font-size: 13.5px;
  cursor: pointer;
}
.scanbox button:hover:not(:disabled) { border-color: var(--acc); }
.scanbox button:disabled { opacity: 0.6; cursor: default; }
nav { overflow-y: auto; flex: 1; padding: 8px; }
.folder {
  display: flex;
  gap: 8px;
  width: 100%;
  align-items: center;
  text-align: left;
  background: none;
  border: 0;
  color: var(--txt);
  padding: 7px 9px;
  border-radius: 7px;
  cursor: pointer;
  font-size: 13.5px;
}
.folder:hover { background: var(--panel2); }
.folder.on { background: var(--panel2); box-shadow: inset 2px 0 0 var(--acc); }
.fname { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fcount { color: var(--dim); font-size: 12px; }

.jobsbox {
  border-top: 1px solid var(--line);
  padding: 8px 12px;
  font-size: 11.5px;
  max-height: 140px;
  overflow-y: auto;
}
.jobrow {
  display: flex;
  gap: 8px;
  padding: 3px 0;
  color: var(--dim);
}
.jobrow .jt {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.jobrow .js { font-variant-numeric: tabular-nums; white-space: nowrap; }
.jobrow.running { color: var(--acc); }
.jobrow.queued { color: var(--dim); }
.jobrow.done .js { color: var(--ok); }
.jobrow.error { color: #ff9c8f; }

main { min-width: 0; display: flex; flex-direction: column; min-height: 0; }
header {
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding: 12px 18px 8px;
}
h1 { font-size: 16px; margin: 0; }
.dim { color: var(--dim); font-size: 12.5px; }
.spacer { flex: 1; }

.toolbar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 18px 10px;
  border-bottom: 1px solid var(--line);
  flex-wrap: wrap;
}
.pill {
  background: var(--panel2);
  color: var(--txt);
  border: 1px solid var(--line);
  border-radius: 20px;
  padding: 5px 12px;
  font-size: 12.5px;
  cursor: pointer;
}
.pill b { font-weight: 600; color: var(--dim); margin-left: 2px; }
.pill:hover:not(:disabled) { border-color: var(--acc); }
.pill.on { background: var(--acc); color: #1a1408; border-color: var(--acc); font-weight: 600; }
.pill.on b { color: #1a1408; }
.pill.danger:not(:disabled) { border-color: var(--no); }
.pill.warn { border-color: #7a4a33; color: #ffb38a; }
.pill:disabled { opacity: 0.5; cursor: default; }
.pillsel {
  background: var(--panel2);
  color: var(--txt);
  border: 1px solid var(--line);
  border-radius: 20px;
  padding: 4px 8px;
  font-size: 12.5px;
  cursor: pointer;
}

.notice {
  margin: 10px 18px 0;
  background: var(--panel);
  border: 1px solid var(--ok);
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
  cursor: pointer;
}
.err { color: #ff9c8f; padding: 8px 12px; font-size: 13px; }
.err.big {
  margin: 10px 18px 0;
  background: var(--panel);
  border: 1px solid var(--no);
  border-radius: 8px;
  cursor: pointer;
}
.empty { margin: 60px auto; color: var(--dim); }

.grid {
  overflow-y: auto;
  padding: 14px 18px;
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  /* max-content: sin esto, un grid que además es scroller colapsa sus filas
     auto en Chromium cuando el contenido desborda */
  grid-auto-rows: max-content;
  align-content: start;
  flex: 1;
}
.keys {
  border-top: 1px solid var(--line);
  padding: 6px 18px;
  font-size: 11.5px;
  color: var(--dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Pantallas estrechas (móvil, panel lateral): sidebar como tira superior */
@media (max-width: 720px) {
  .layout {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr);
  }
  aside {
    flex-direction: row;
    align-items: center;
    gap: 8px;
    border-right: 0;
    border-bottom: 1px solid var(--line);
    padding: 6px 10px;
    min-height: 0;
    min-width: 0;
  }
  .brand { display: none; }
  .scanbox { padding: 0; border: 0; flex: none; }
  .scanbox button { width: auto; white-space: nowrap; }
  .jobsbox { display: none; }
  nav { display: flex; flex-direction: row; overflow-x: auto; overflow-y: hidden; padding: 0; }
  .folder { width: auto; white-space: nowrap; flex: none; }
  .fname { max-width: 150px; }
  header { flex-wrap: wrap; padding: 8px 12px 4px; }
  .toolbar { padding: 0 12px 8px; }
  .grid { padding: 10px 12px; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); }
  .keys { display: none; }
}
</style>
