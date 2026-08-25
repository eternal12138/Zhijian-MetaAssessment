<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useUiFeedback } from '../../composables/useUiFeedback'

const {
  confirmState,
  toasts,
  resolveConfirmation,
  dismissToast
} = useUiFeedback()
const confirmButton = ref<HTMLButtonElement | null>(null)

const toneIcons = {
  primary: 'bi-question-circle-fill',
  success: 'bi-check-circle-fill',
  warning: 'bi-exclamation-circle-fill',
  danger: 'bi-exclamation-triangle-fill'
}

watch(() => confirmState.value.open, async open => {
  if (!open) return
  await nextTick()
  confirmButton.value?.focus()
})

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && confirmState.value.open) {
    resolveConfirmation(false)
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <Transition name="app-modal">
      <div
        v-if="confirmState.open"
        class="app-dialog-backdrop"
        role="presentation"
        @click.self="resolveConfirmation(false)"
      >
        <section
          class="app-dialog"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="app-dialog-title"
          aria-describedby="app-dialog-message"
        >
          <span class="app-dialog-icon" :class="`tone-${confirmState.tone}`">
            <i class="bi" :class="toneIcons[confirmState.tone]"></i>
          </span>
          <div class="app-dialog-copy">
            <h5 id="app-dialog-title">{{ confirmState.title }}</h5>
            <p id="app-dialog-message">{{ confirmState.message }}</p>
          </div>
          <div class="app-dialog-actions">
            <button class="btn btn-outline-secondary" type="button" @click="resolveConfirmation(false)">
              {{ confirmState.cancelText }}
            </button>
            <button
              ref="confirmButton"
              class="btn"
              :class="`btn-${confirmState.tone}`"
              type="button"
              @click="resolveConfirmation(true)"
            >
              {{ confirmState.confirmText }}
            </button>
          </div>
        </section>
      </div>
    </Transition>

    <div class="app-toast-region" aria-live="polite" aria-atomic="false">
      <TransitionGroup name="app-toast">
        <div
          v-for="toast in toasts"
          :key="toast.id"
          class="app-toast"
          :class="`tone-${toast.tone}`"
          role="status"
        >
          <i class="bi" :class="toneIcons[toast.tone]"></i>
          <span>{{ toast.message }}</span>
          <button type="button" aria-label="关闭提示" @click="dismissToast(toast.id)">
            <i class="bi bi-x-lg"></i>
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>
