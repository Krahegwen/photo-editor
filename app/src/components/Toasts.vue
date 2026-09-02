<script setup lang="ts">
import { dismiss, pause, resume, toasts } from '../toasts'

const ICON = { info: 'ℹ', ok: '✓', warn: '⚠', error: '✕' } as const
</script>

<template>
  <div class="toasts" aria-live="polite">
    <TransitionGroup name="toast">
      <div
        v-for="t in toasts.visible"
        :key="t.id"
        class="toast"
        :class="t.level"
        role="status"
        @mouseenter="pause(t.id)"
        @mouseleave="resume(t.id)"
      >
        <span class="icon">{{ ICON[t.level] }}</span>
        <span class="text">{{ t.text }}<b v-if="t.count > 1" class="count">×{{ t.count }}</b></span>
        <button class="close" title="Cerrar" @click="dismiss(t.id)">✕</button>
        <span
          v-if="t.timeout !== null"
          class="bar"
          :style="{ animationDuration: `${t.timeout}ms` }"
        ></span>
      </div>
    </TransitionGroup>
    <div v-if="toasts.queue.length" class="pending">+{{ toasts.queue.length }} en cola</div>
  </div>
</template>

<style scoped>
.toasts {
  position: fixed;
  left: 50%;
  bottom: 44px;
  transform: translateX(-50%);
  z-index: 90;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  width: min(560px, calc(100vw - 24px));
  pointer-events: none;
}
.toast {
  pointer-events: auto;
  position: relative;
  overflow: hidden;
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 10px;
  align-items: center;
  width: 100%;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--panel);
  border: 1px solid var(--line);
  color: var(--txt);
  font-size: 13.5px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45);
}
.toast.ok { border-color: var(--ok); }
.toast.warn { border-color: #c48a3a; }
.toast.error { border-color: var(--no); background: #2a1a1a; }
.icon { font-size: 15px; width: 18px; text-align: center; }
.toast.ok .icon { color: var(--ok); }
.toast.warn .icon { color: #ffb38a; }
.toast.error .icon { color: #ff9c8f; }
.toast.info .icon { color: var(--acc); }
.text { line-height: 1.35; overflow-wrap: anywhere; }
.count {
  margin-left: 8px;
  font-size: 11px;
  color: var(--dim);
  background: var(--panel2);
  border-radius: 999px;
  padding: 1px 6px;
}
.close {
  background: none;
  border: 1px solid transparent;
  color: var(--dim);
  border-radius: 6px;
  padding: 2px 6px;
  cursor: pointer;
}
.close:hover { color: var(--txt); border-color: var(--line); }
.bar {
  position: absolute;
  left: 0;
  bottom: 0;
  height: 2px;
  width: 100%;
  background: currentColor;
  opacity: 0.35;
  transform-origin: left;
  animation: shrink linear forwards;
}
.toast.ok .bar { color: var(--ok); }
.toast.warn .bar { color: #ffb38a; }
.toast.info .bar { color: var(--acc); }
.toast:hover .bar { animation-play-state: paused; }
@keyframes shrink {
  from { transform: scaleX(1); }
  to { transform: scaleX(0); }
}
.pending { font-size: 11px; color: var(--dim); }

/* entrada / salida (TransitionGroup) */
.toast-enter-active { transition: transform 0.28s cubic-bezier(0.2, 0.8, 0.2, 1), opacity 0.28s; }
.toast-leave-active { transition: transform 0.22s ease-in, opacity 0.22s; position: absolute; width: 100%; }
.toast-enter-from { transform: translateY(18px) scale(0.98); opacity: 0; }
.toast-leave-to { transform: translateY(10px) scale(0.98); opacity: 0; }
.toast-move { transition: transform 0.28s; }
</style>
