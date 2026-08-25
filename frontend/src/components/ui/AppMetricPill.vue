<script setup lang="ts">
withDefaults(defineProps<{
  value: string | number
  label: string
  tone?: 'neutral' | 'primary' | 'success' | 'warning' | 'danger'
}>(), { tone: 'neutral' })
</script>

<template>
  <span class="ds-metric-pill" :class="`tone-${tone}`">
    <strong>{{ value }}</strong><span>{{ label }}</span>
  </span>
</template>
