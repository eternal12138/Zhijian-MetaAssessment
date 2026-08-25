<script setup lang="ts">
import { onBeforeUnmount, onMounted, watch } from 'vue'

const props = withDefaults(defineProps<{
  open: boolean
  title?: string
  icon?: string
  maxWidth?: string
  closeOnBackdrop?: boolean
  closeOnEsc?: boolean
}>(), {
  title: '',
  icon: '',
  maxWidth: '430px',
  closeOnBackdrop: true,
  closeOnEsc: true
})

const emit = defineEmits<{
  (e: 'close'): void
}>()

function handleBackdropClick(event: MouseEvent) {
  if (props.closeOnBackdrop && event.target === event.currentTarget) {
    emit('close')
  }
}

function handleKeydown(event: KeyboardEvent) {
  if (props.open && props.closeOnEsc && event.key === 'Escape') {
    emit('close')
  }
}

watch(() => props.open, (isOpen) => {
  if (isOpen) {
    document.body.style.overflow = 'hidden'
  } else {
    document.body.style.overflow = ''
  }
})

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <Transition name="app-modal">
      <div
        v-if="open"
        class="modal-backdrop"
        role="presentation"
        @click="handleBackdropClick"
      >
        <div
          class="modal-card"
          :style="{ maxWidth }"
          role="dialog"
          aria-modal="true"
          :aria-label="title || undefined"
        >
          <div v-if="$slots.header || title" class="modal-card-header mb-3">
            <slot name="header">
              <h5 class="mb-0">
                <i v-if="icon" class="bi" :class="icon"></i>
                {{ title }}
              </h5>
            </slot>
          </div>

          <div class="modal-card-body">
            <slot />
          </div>

          <div v-if="$slots.footer" class="modal-card-footer mt-3">
            <slot name="footer" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.modal-card-header h5 {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 700;
  color: var(--color-text);
}
</style>
