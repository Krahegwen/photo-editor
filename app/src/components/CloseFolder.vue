<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import type { CloseReport, FavCandidate, Folder } from '../types'

const props = defineProps<{ folder: Folder }>()
const emit = defineEmits<{ close: []; started: [] }>()

const report = ref<CloseReport | null>(null)
const error = ref<string | null>(null)
const busy = ref(false)
const bigId = ref<number | null>(null)

// favoritas: marcadas por defecto salvo las que ya están en FAVS; nombre editable
const favSel = reactive<Record<number, { on: boolean; nombre: string }>>({})

onMounted(async () => {
  try {
    report.value = (await api.closeFolder(props.folder.id, false)).report
    for (const f of report.value.favoritas ?? []) {
      favSel[f.id] = { on: !f.ya_en_favs, nombre: f.nombre }
    }
  } catch (e) {
    error.value = String(e)
  }
})

const favsChecked = computed(() =>
  (report.value?.favoritas ?? []).filter((f) => favSel[f.id]?.on && favSel[f.id].nombre.trim()),
)
const canExecute = computed(
  () => !!report.value && (report.value.borrar.length > 0 || favsChecked.value.length > 0),
)

const hhmm = (t: string | null) => (t ? t.slice(11, 16) : '')

async function execute() {
  const r = report.value
  if (!r || !canExecute.value || busy.value) return
  const parts: string[] = []
  if (r.borrar.length) parts.push(`enviar ${r.borrar.length} RAW (y sus sidecars) a la papelera`)
  if (favsChecked.value.length) parts.push(`copiar ${favsChecked.value.length} favoritas a FAVS`)
  if (!window.confirm(`¿${parts.join(' y ')}?`)) return
  busy.value = true
  try {
    await api.closeFolder(
      props.folder.id,
      true,
      favsChecked.value.map((f) => ({ photo_id: f.id, nombre: favSel[f.id].nombre.trim() })),
    )
    emit('started')
  } catch (e) {
    error.value = String(e)
    busy.value = false
  }
}

function fmt(f: FavCandidate) {
  const v = [f.tiene_jpg ? 'JPG' : '', f.tiene_tif ? 'TIF' : ''].filter(Boolean)
  return v.length ? v.join(' + ') : 'solo RAW'
}
</script>

<template>
  <div class="closer">
    <div class="topbar">
      <b>Cerrar carpeta</b>
      <span class="dim">{{ folder.label ?? folder.name }}</span>
      <span class="sp"></span>
      <button class="danger" :disabled="busy || !canExecute" @click="execute">
        {{
          busy
            ? 'Encolando…'
            : `${report?.borrar.length ? `${report.borrar.length} RAW a la papelera` : ''}${
                report?.borrar.length && favsChecked.length ? ' · ' : ''
              }${favsChecked.length ? `${favsChecked.length} favoritas a FAVS` : ''}` || 'Nada que hacer'
        }}
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
        <span class="fav">{{ report.favoritas?.length ?? 0 }} favoritas 5★</span>
      </div>

      <template v-if="report.favoritas?.length">
        <h3 class="favh">Favoritas (5★) → 999999 - FAVS</h3>
        <p class="hint tight">
          Se copian con el nombre <b>carpeta + hora</b>. Desmarca las que no quieras, cambia el
          nombre si procede y pulsa la miniatura para verla en grande. Las que ya están en FAVS
          salen desmarcadas.
        </p>
        <div class="favs">
          <div v-for="f in report.favoritas" :key="f.id" class="favrow" :class="{ off: !favSel[f.id]?.on }">
            <input v-model="favSel[f.id].on" type="checkbox" />
            <img :src="`/api/preview/${f.id}?s=320`" :alt="f.stem" @click="bigId = f.id" />
            <div class="favinfo">
              <div class="favmeta">
                <b>{{ f.stem }}</b>
                <span class="dim">{{ hhmm(f.taken_at) }} · {{ fmt(f) }}</span>
                <span v-if="f.ya_en_favs" class="tag ok">ya en FAVS</span>
                <span v-else-if="f.revelar" class="tag warn">se revelará (sin JPG aún)</span>
              </div>
              <input v-model="favSel[f.id].nombre" class="favname" spellcheck="false" />
            </div>
          </div>
        </div>
      </template>

      <h3 v-if="report.borrar.length">Se enviarían a la papelera</h3>
      <div class="rows">
        <div v-for="b in report.borrar" :key="b.id" class="row">
          <b>{{ b.stem.slice(-4) }}</b>
          <span class="dim">{{ b.stem }}</span>
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

      <p v-if="!canExecute" class="hint ok">
        Nada que hacer: la carpeta ya cumple la política (o no hay RAW revelados/1★ ni 5★ nuevas).
      </p>
    </div>

    <div v-if="bigId !== null" class="big" @click="bigId = null">
      <img :src="`/api/preview/${bigId}?s=1600`" alt="" />
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
.hint.tight { padding-top: 0; }
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
.summary .fav { color: var(--ok); }
h3 {
  font-size: 13px;
  margin: 14px 16px 6px;
  color: var(--txt);
}
h3.warn { color: #ffb38a; }
h3.favh { color: var(--ok); }
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

.favs { padding: 0 16px; display: flex; flex-direction: column; gap: 6px; max-width: 760px; }
.favrow {
  display: grid;
  grid-template-columns: auto 120px 1fr;
  gap: 10px;
  align-items: center;
  padding: 6px 8px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
}
.favrow.off { opacity: 0.55; }
.favrow input[type='checkbox'] { accent-color: var(--ok); width: 16px; height: 16px; }
.favrow img {
  width: 120px;
  height: 80px;
  object-fit: cover;
  border-radius: 6px;
  background: #000;
  cursor: zoom-in;
}
.favinfo { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.favmeta { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; font-size: 13px; }
.tag { font-size: 11px; border-radius: 4px; padding: 0 6px; border: 1px solid; }
.tag.ok { color: var(--ok); border-color: var(--ok); }
.tag.warn { color: #ffb38a; border-color: #7a4a33; }
.favname {
  background: var(--panel2);
  color: var(--txt);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 5px 8px;
  font-size: 13px;
  width: 100%;
  max-width: 420px;
}
.favname:focus { border-color: var(--acc); outline: none; }
.big {
  position: fixed;
  inset: 0;
  z-index: 70;
  background: rgba(8, 9, 12, 0.94);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: zoom-out;
}
.big img { max-width: 96vw; max-height: 94vh; object-fit: contain; }
</style>
