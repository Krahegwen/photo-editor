<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { api } from '../api'
import type { RootInfo } from '../types'

const emit = defineEmits<{ close: []; saved: [info: RootInfo] }>()

const path = ref('')
const current = ref<RootInfo | null>(null)
const info = ref<RootInfo | null>(null)
const busy = ref(false)
const browsing = ref(false)
const error = ref<string | null>(null)
let timer: number | undefined

onMounted(async () => {
  try {
    current.value = await api.root()
    if (current.value.root) {
      path.value = current.value.root
      info.value = current.value
    }
  } catch (e) {
    error.value = String(e)
  }
})

watch(path, (p) => {
  window.clearTimeout(timer)
  info.value = null
  if (!p.trim()) return
  timer = window.setTimeout(async () => {
    try {
      info.value = await api.root(p.trim())
    } catch (e) {
      error.value = String(e)
    }
  }, 450)
})

async function browse() {
  browsing.value = true
  error.value = null
  try {
    const r = await api.browseRoot()
    if (r.root) {
      path.value = r.root
      info.value = r
    }
  } catch (e) {
    error.value = String(e)
  } finally {
    browsing.value = false
  }
}

async function save() {
  if (!path.value.trim() || busy.value) return
  busy.value = true
  error.value = null
  try {
    const r = await api.setRoot(path.value.trim())
    emit('saved', r)
  } catch (e) {
    error.value = String(e)
    busy.value = false
  }
}

function basename(p: string) {
  const parts = p.replace(/[\\/]+$/, '').split(/[\\/]/)
  return parts[parts.length - 1] || p
}
</script>

<template>
  <div class="rootdlg" @click.self="emit('close')">
    <div class="box">
      <div class="head">
        <b>Carpeta de fotos</b>
        <span class="sp"></span>
        <button v-if="current?.root" @click="emit('close')">✕</button>
      </div>

      <p class="dim">
        Elige la raíz de tu archivo. Vale una carpeta con subcarpetas por sesión
        (<code>240812 - Estrellas</code>, …) o directamente una carpeta con fotos:
        en ese caso se indexa como una única carpeta.
      </p>

      <div class="row">
        <input
          v-model="path"
          class="path"
          spellcheck="false"
          placeholder="C:\Users\…\Fotos"
          :disabled="current?.por_entorno"
          @keydown.enter.prevent="save"
        />
        <button :disabled="browsing || current?.por_entorno" @click="browse">
          {{ browsing ? 'Abriendo…' : 'Examinar…' }}
        </button>
      </div>
      <p v-if="current?.por_entorno" class="warn">
        La raíz viene fijada por la variable de entorno PHOTOED_ROOT; cámbiala ahí.
      </p>

      <div v-if="info" class="preview">
        <template v-if="info.existe === false">
          <span class="bad">Esa ruta no existe.</span>
        </template>
        <template v-else>
          <div>
            <b>{{ info.subcarpetas ?? 0 }}</b> subcarpetas con fotos
            <span v-if="info.ejemplos?.length" class="dim">
              ({{ info.ejemplos.join(', ') }}{{ (info.subcarpetas ?? 0) > info.ejemplos.length ? ', …' : '' }})
            </span>
          </div>
          <div>
            <b>{{ info.fotos_sueltas ?? 0 }}</b> fotos sueltas en la raíz
            <span v-if="info.fotos_sueltas" class="dim">
              (irán a la carpeta «{{ basename(path) }}»)
            </span>
          </div>
          <div v-if="!info.subcarpetas && !info.fotos_sueltas" class="bad">
            Ahí no hay nada que indexar.
          </div>
        </template>
      </div>

      <p class="dim small">
        «Examinar…» abre el explorador de carpetas en el PC donde corre el motor
        (si estás en el móvil, aparecerá allí). Al cambiar de raíz se escanea de nuevo;
        las puntuaciones y recetas viven en los sidecars junto a las fotos, no se pierden.
      </p>

      <div v-if="error" class="err">{{ error }}</div>

      <div class="foot">
        <button
          class="primary"
          :disabled="busy || !path.trim() || info?.existe === false || current?.por_entorno"
          @click="save"
        >
          {{ busy ? 'Guardando…' : 'Guardar y escanear' }}
        </button>
        <button v-if="current?.root" @click="emit('close')">Cancelar</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rootdlg {
  position: fixed;
  inset: 0;
  z-index: 70;
  background: rgba(10, 11, 15, 0.75);
  display: flex;
  align-items: safe center;
  justify-content: center;
  padding: 20px;
}
.box {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  width: min(600px, 100%);
  padding: 14px 16px;
}
.head { display: flex; gap: 10px; align-items: baseline; margin-bottom: 8px; }
.sp { flex: 1; }
.dim { color: var(--dim); font-size: 12.5px; }
.small { font-size: 12px; }
code { background: var(--panel2); padding: 1px 5px; border-radius: 4px; }
button, input {
  background: var(--panel2);
  color: var(--txt);
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 7px 10px;
  font-size: 13px;
}
button { cursor: pointer; white-space: nowrap; }
button:hover:not(:disabled) { border-color: var(--acc); }
button:disabled { opacity: 0.5; cursor: default; }
button.primary { background: var(--acc); border-color: var(--acc); color: #1a1408; font-weight: 600; }
.row { display: flex; gap: 8px; margin: 10px 0 6px; }
.path { flex: 1; min-width: 0; font-family: Consolas, monospace; }
.preview {
  margin: 8px 0;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  font-size: 13px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.bad { color: #ff9c8f; }
.warn { color: #ffb38a; font-size: 12.5px; }
.err { color: #ff9c8f; font-size: 13px; margin: 8px 0; }
.foot { display: flex; gap: 8px; margin-top: 10px; }
</style>
