<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from './api'
import type { Folder, Health, Photo, ScanState } from './types'

const health = ref<Health | null>(null)
const folders = ref<Folder[]>([])
const current = ref<Folder | null>(null)
const photos = ref<Photo[]>([])
const scan = ref<ScanState | null>(null)
const error = ref<string | null>(null)
const loadingPhotos = ref(false)

async function loadFolders() {
  folders.value = await api.folders()
  if (current.value) {
    const again = folders.value.find((f) => f.id === current.value!.id)
    if (again) {
      await select(again)
      return
    }
  }
  if (folders.value.length) await select(folders.value[0])
}

async function select(f: Folder) {
  current.value = f
  loadingPhotos.value = true
  try {
    photos.value = await api.photos(f.id)
  } finally {
    loadingPhotos.value = false
  }
}

async function pollScan(refreshWhenDone: boolean) {
  scan.value = await api.scanStatus()
  if (scan.value.running) {
    window.setTimeout(() => pollScan(true), 1500)
  } else if (refreshWhenDone) {
    await loadFolders()
  }
}

async function startScan() {
  error.value = null
  try {
    await api.scan()
    await pollScan(true)
  } catch (e) {
    error.value = String(e)
  }
}

onMounted(async () => {
  try {
    health.value = await api.health()
    await loadFolders()
    await pollScan(true) // por si había un escaneo en marcha de antes
  } catch (e) {
    error.value = String(e)
  }
})

const last4 = (stem: string) => stem.slice(-4)
const stars = (n: number | null) => (n && n > 0 ? '★'.repeat(n) : '')
</script>

<template>
  <div class="layout">
    <aside>
      <div class="brand">photo<span>-editor</span></div>
      <div class="scanbox">
        <button :disabled="scan?.running" @click="startScan">
          {{ scan?.running ? 'Escaneando…' : 'Escanear archivo' }}
        </button>
        <div v-if="scan?.running" class="scanprog">
          {{ scan.done }}/{{ scan.total }} · {{ scan.folder }}
        </div>
        <div v-if="scan?.error" class="err">{{ scan.error }}</div>
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
    </aside>

    <main>
      <header>
        <h1>{{ current?.name ?? 'Sin carpeta' }}</h1>
        <span v-if="current" class="count">{{ photos.length }} fotos</span>
        <span class="spacer"></span>
        <span v-if="health" class="health">
          catálogo: {{ health.photos }} fotos en {{ health.folders }} carpetas
        </span>
      </header>

      <div v-if="error" class="err big">{{ error }}</div>
      <div v-else-if="health && !health.ok" class="err big">{{ health.root_error }}</div>
      <div v-else-if="!folders.length" class="empty">
        Catálogo vacío — pulsa «Escanear archivo» para indexar tus carpetas.
      </div>
      <div v-else-if="loadingPhotos" class="empty">Cargando…</div>
      <div v-else class="grid">
        <a
          v-for="p in photos"
          :key="p.id"
          class="card"
          :href="`/api/preview/${p.id}?s=1600`"
          target="_blank"
          rel="noopener"
        >
          <img :src="`/api/preview/${p.id}?s=320`" loading="lazy" :alt="p.stem" />
          <div class="meta">
            <b>{{ last4(p.stem) }}</b>
            <span v-if="p.ext !== '.arw'" class="ext">{{ p.ext.slice(1).toUpperCase() }}</span>
            <span v-if="stars(p.rating)" class="stars">{{ stars(p.rating) }}</span>
          </div>
        </a>
      </div>
    </main>
  </div>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 290px 1fr;
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
.scanbox {
  padding: 0 12px 12px;
  border-bottom: 1px solid var(--line);
}
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
.scanprog {
  margin-top: 6px;
  font-size: 12px;
  color: var(--dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
nav {
  overflow-y: auto;
  flex: 1;
  padding: 8px;
}
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
.folder.on {
  background: var(--panel2);
  box-shadow: inset 2px 0 0 var(--acc);
}
.fname {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fcount { color: var(--dim); font-size: 12px; }
main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
header {
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--line);
}
h1 { font-size: 16px; margin: 0; }
.count, .health { color: var(--dim); font-size: 12.5px; }
.spacer { flex: 1; }
.err { color: #ff9c8f; padding: 8px 12px; font-size: 13px; }
.err.big {
  margin: 24px;
  background: var(--panel);
  border: 1px solid var(--no);
  border-radius: 8px;
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
}
.card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 9px;
  overflow: hidden;
  text-decoration: none;
  color: var(--txt);
}
.card:hover { border-color: var(--acc); }
.card img {
  display: block;
  width: 100%;
  height: 158px;
  object-fit: cover;
  background: #000;
}
.meta {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 6px 9px;
  font-size: 12.5px;
}
.meta b { font-size: 13px; }
.ext {
  color: var(--dim);
  font-size: 10.5px;
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 0 4px;
}
.stars {
  margin-left: auto;
  color: var(--acc);
  letter-spacing: 1px;
}
</style>
