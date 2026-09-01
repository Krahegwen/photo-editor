<script setup lang="ts">
import type { Photo } from '../types'

defineProps<{ photo: Photo; selected: boolean }>()
const emit = defineEmits<{ select: []; open: [] }>()

// Fotos de cámara: los 4 dígitos finales. Salidas con nombre largo
// ('<carpeta> - trails 0202-0217', samples con espacios…): lo que sigue al
// último ' - ', que es la parte que distingue.
const last4 = (s: string) => {
  if (/^[A-Za-z_]*\d{4,5}$/.test(s)) return s.slice(-4)
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
      <span v-if="photo.ext !== '.arw'" class="ext">{{ photo.ext.slice(1).toUpperCase() }}</span>
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
