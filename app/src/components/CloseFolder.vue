<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import type { CloseReport, Folder } from '../types'

const props = defineProps<{ folder: Folder }>()
const emit = defineEmits<{ close: []; started: [] }>()

const report = ref<CloseReport | null>(null)
const error = ref<string | null>(null)
const busy = ref(false)

onMounted(async () => {
  try {
    report.value = (await api.closeFolder(props.folder.id, false)).report
  } catch (e) {
    error.value = String(e)
  }
})

async function execute() {
  const r = report.value
  if (!r || !r.borrar.length || busy.value) return
  if (!window.confirm(`¿Enviar ${r.borrar.length} RAW (y sus sidecars) a la papelera de Windows?`))
    return
  busy.value = true
  try {
    await api.closeFolder(props.folder.id, true)
    emit('started')
  } catch (e) {
    error.value = String(e)
    busy.value = false
  }
}
</script>

<template>
  <div class="closer">
    <div class="topbar">
      <b>Cerrar carpeta</b>
      <span class="dim">{{ folder.label ?? folder.name }}</span>
      <span class="sp"></span>
      <button
        class="danger"
        :disabled="busy || !report || !report.borrar.length"
        @click="execute"
      >
        {{ busy ? 'Encolando…' : `Enviar ${report?.borrar.length ?? 0} RAW a la papelera` }}
      </button>
      <button @click="emit('close')">Cerrar</button>
    </div>

    <div v-if="error" class="err">{{ error }}</div>
    <div v-else-if="!report" class="hint">Analizando la carpeta…</div>

    <div v-else class="body">
      <p class="hint">
        Política de archivo: tras procesar quedan solo los finales. Informe dry-run —
        no se toca nada hasta que pulses el botón rojo.
      </p>

      <div class="summary">
        <span>{{ report.total_fotos }} fotos en catálogo</span>
        <span>{{ report.finales }} finales JPG</span>
        <span class="del">{{ report.borrar.length }} RAW a borrar</span>
        <span class="pend">{{ report.pendientes.length }} pendientes</span>
      </div>

      <h3 v-if="report.borrar.length">Se enviarían a la papelera</h3>
      <div class="rows">
        <div v-for="b in report.borrar" :key="b.id" class="row">
          <b>{{ b.stem.slice(-4) }}</b>
          <span class="dim">{{ b.stem }}.arw</span>
          <span class="why">{{ b.motivo }}</span>
        </div>
      </div>

      <template v-if="report.pendientes.length">
        <h3>Pendientes (RAW sin revelar y sin 1★) — no se tocan</h3>
        <p class="list dim">{{ report.pendientes.map((s) => s.slice(-4)).join(' · ') }}</p>
      </template>

      <template v-if="report.tiff_sin_favs.length">
        <h3 class="warn">TIFF sin copia en FAVS (¿favorita a medias o TIFF huérfano?)</h3>
        <p class="list dim">{{ report.tiff_sin_favs.map((s) => s.slice(-4)).join(' · ') }}</p>
      </template>

      <p v-if="!report.borrar.length" class="hint ok">
        Nada que borrar: la carpeta ya cumple la política (o no hay RAW revelados/1★).
      </p>
    </div>
  </div>
</template>

<style scoped>
.closer {
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
  flex-wrap: wrap;
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
.err { color: #ff9c8f; padding: 10px 16px; }
.hint { color: var(--dim); font-size: 12.5px; padding: 8px 16px 0; max-width: 75ch; }
.hint.ok { color: var(--ok); }
.body { overflow-y: auto; padding-bottom: 30px; }
.summary {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  padding: 12px 16px;
  font-size: 13px;
}
.summary .del { color: var(--no); font-weight: 600; }
.summary .pend { color: var(--acc); }
h3 {
  font-size: 13px;
  margin: 14px 16px 6px;
  color: var(--txt);
}
h3.warn { color: #ffb38a; }
.rows { padding: 0 16px; }
.row {
  display: flex;
  gap: 10px;
  align-items: baseline;
  padding: 3px 0;
  font-size: 13px;
  border-bottom: 1px solid var(--line);
  max-width: 640px;
}
.row .why { margin-left: auto; color: #ffb38a; font-size: 12px; }
.list { padding: 0 16px; margin: 4px 0; max-width: 80ch; }
</style>
