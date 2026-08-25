<script setup lang="ts">
withDefaults(defineProps<{
  icon?: string
  title: string
  description?: string
  tone?: 'neutral' | 'success' | 'warning'
}>(), {
  icon: 'bi-inbox',
  description: '',
  tone: 'neutral'
})
</script>

<template>
  <div class="ds-empty-state" :class="`tone-${tone}`">
    <span class="ds-empty-icon"><i class="bi" :class="icon" /></span>
    <h3>{{ title }}</h3>
    <p v-if="description">{{ description }}</p>
    <div v-if="$slots.default" class="ds-empty-actions"><slot /></div>
  </div>
</template>
