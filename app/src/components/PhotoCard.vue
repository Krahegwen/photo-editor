<script setup lang="ts">
import { computed } from 'vue'
import { isRaw } from '../formats'
import type { Photo } from '../types'

const props = defineProps<{ photo: Photo; selected: boolean; folderName?: string }>()

// Versiones de la foto: si la principal es RAW, solo se listan las demás
// (JPG, TIF = ya revelada); si no hay RAW, se listan todas.
const versionChips = computed(() => {
  const fm = props.photo.formats ?? []
  return isRaw(props.photo.ext) ? fm.slice(1) : fm
})
const emit = defineEmits<{ select: []; open: [] }>()

// Fotos de cámara: los 4 dígitos finales. Salidas del programa
// ('<carpeta> 02h02-02h17 trails'): lo que sigue al nombre de la carpeta.
// Otros nombres largos: lo que sigue al último ' - '.
const last4 = (s: string) => {
  if (/^[A-Za-z_]*\d{4,5}$/.test(s)) return s.slice(-4)
  if (props.folderName && s.startsWith(props.folderName + ' ')) {
    return s.slice(props.folderName.length + 1)
  }
  const i = s.lastIndexOf(' - ')
  return i >= 0 ? s.slice(i + 3) : s.slice(-4)
}
</script>

<template>
  <div
    class="card"
    :class="{ sel: selected, discard: photo.rating === 1 }"
    :title="photo.stem + photo.ext"
    @click="emit('select')"
    @dblclick="emit('open')"
  >
    <img :src="`/api/preview/${photo.id}?s=320`" loading="lazy" :alt="photo.stem" />
    <div class="meta">
      <b>{{ last4(photo.stem) }}</b>
      <span v-for="f in versionChips" :key="f" class="ext" :title="`también en ${f}`">{{ f }}</span>
      <span v-if="photo.burst_n" class="ext burst" :title="`ráfaga de ${photo.burst_n}`">
        ⧉{{ photo.burst_n }}
      </span>
      <span
        v-if="photo.best_of_burst"
        class="ext best"
        title="La más nítida de su ráfaga"
      >★⧉</span>
      <span v-if="photo.has_recipe" class="ext recipe" title="Tiene receta de revelado">✎</span>
      <span v-for="fl in photo.flags" :key="fl" class="flag">{{ fl }}</span>
      <span class="right">
        <span v-if="photo.rating === 1" class="discardmark">1★</span>
        <span v-else-if="photo.rating" class="stars">{{ '★'.repeat(photo.rating) }}</span>
      </span>
    </div>
  </div>
</template>

<style scoped>
.card {
  background: var(--panel);
  border: 2px solid var(--line);
  border-radius: 9px;
  overflow: hidden;
  cursor: pointer;
  transition: border-color 0.1s;
}
.card:hover { border-color: var(--acc); }
.card.sel { box-shadow: 0 0 0 3px var(--acc); border-color: var(--acc); }
.card.discard { border-color: var(--no); opacity: 0.55; }
.card img {
  display: block;
  width: 100%;
  height: 158px;
  object-fit: cover;
  background: #000;
}
.meta {
  display: flex;
  gap: 6px;
  align-items: center;
  padding: 6px 9px;
  font-size: 12.5px;
  min-height: 30px;
}
.meta b { font-size: 13px; }
.ext {
  color: var(--dim);
  font-size: 10.5px;
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 0 4px;
  white-space: nowrap;
}
.flag {
  font-size: 10.5px;
  color: #ffb38a;
  border: 1px solid #7a4a33;
  border-radius: 4px;
  padding: 0 4px;
}
.ext.recipe { color: var(--acc); border-color: var(--acc); }
.ext.best { color: var(--ok); border-color: var(--ok); }
.right { margin-left: auto; }
.stars { color: var(--acc); letter-spacing: 1px; }
.discardmark { color: var(--no); font-weight: 700; }
.meta b { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
