<script setup lang="ts">
import { computed, ref } from 'vue'
import { api } from '../api'
import type { Photo } from '../types'

const props = defineProps<{ photos: Photo[]; folderName: string }>()
const emit = defineEmits<{ close: []; done: [trashed: string[], errors: string[]] }>()

const busy = ref(false)
const error = ref<string | null>(null)

const totalMb = computed(() =>
  (props.photos.reduce((a, p) => a + (p.files ?? [{ bytes: p.bytes }]).reduce((b, f) => b + f.bytes, 0), 0) / 1e6).toFixed(0),
)

async function send() {
  if (!window.confirm(`¿Enviar ${props.photos.length} fotos a la papelera de Windows?`)) return
  busy.value = true
  error.value = null
  try {
    const res = await api.del(props.photos.map((p) => p.id))
    emit('done', res.trashed, res.errors)
  } catch (e) {
    error.value = String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="review">
    <div class="topbar">
      <b>Revisar descartes</b>
      <span class="dim">{{ folderName }} · {{ photos.length }} fotos con 1★ · {{ totalMb }} MB</span>
      <span class="sp"></span>
      <button class="danger" :disabled="busy || !photos.length" @click="send">
        {{ busy ? 'Enviando…' : `Enviar ${photos.length} a la papelera` }}
      </button>
      <button @click="emit('close')">Cerrar</button>
    </div>
    <div v-if="error" class="err">{{ error }}</div>
    <div class="hint">
      Van a la papelera de Windows (recuperables), junto con su sidecar .xmp si ninguna otra
      foto lo comparte. Quita el 1★ a la que quieras rescatar antes de enviar.
    </div>
    <div class="grid">
      <div v-for="p in photos" :key="p.id" class="mini" :title="p.stem + p.ext">
        <img :src="`/api/preview/${p.id}?s=320`" loading="lazy" :alt="p.stem" />
        <div class="name">
          <b>{{ p.stem.slice(-4) }}</b>
          <span v-if="p.flags.length" class="why">{{ p.flags.join(' · ') }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.review {
  position: fixed;
  inset: 0;
  z-index: 60;
  background: var(--bg);
  display: flex;
  flex-direction: column;
}
.topbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
}
.dim { color: var(--dim); font-size: 13px; }
.sp { flex: 1; }
button {
  background: var(--panel2);
  color: var(--txt);
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 7px 12px;
  font-size: 13.5px;
  cursor: pointer;
}
button:hover:not(:disabled) { border-color: var(--acc); }
button:disabled { opacity: 0.5; cursor: default; }
.danger { background: var(--no); border-color: var(--no); color: #fff; font-weight: 600; }
.danger:hover:not(:disabled) { border-color: #ff9c8f; }
.err { color: #ff9c8f; padding: 8px 16px; }
.hint { color: var(--dim); font-size: 12.5px; padding: 8px 16px 0; }
.grid {
  overflow-y: auto;
  padding: 14px 16px;
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  grid-auto-rows: max-content;
  align-content: start;
}
.mini {
  background: var(--panel);
  border: 2px solid var(--no);
  border-radius: 8px;
  overflow: hidden;
}
.mini img { display: block; width: 100%; height: 112px; object-fit: cover; background: #000; }
.name { display: flex; gap: 6px; align-items: baseline; padding: 4px 8px; font-size: 12px; }
.why { color: #ffb38a; font-size: 10.5px; }
</style>
