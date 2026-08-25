<script setup lang="ts">
withDefaults(defineProps<{
  eyebrow?: string
  title: string
  description?: string
  icon?: string
  compact?: boolean
}>(), {
  eyebrow: '',
  description: '',
  icon: '',
  compact: false
})
</script>

<template>
  <header class="ds-page-header" :class="{ 'is-compact': compact }">
    <div class="ds-page-heading">
      <p v-if="eyebrow" class="ds-eyebrow">{{ eyebrow }}</p>
      <div class="ds-title-row">
        <span v-if="icon" class="ds-title-icon"><i class="bi" :class="icon" /></span>
        <h2>{{ title }}</h2>
      </div>
      <p v-if="description" class="ds-page-description">{{ description }}</p>
      <slot name="meta" />
    </div>
    <div v-if="$slots.actions" class="ds-page-actions"><slot name="actions" /></div>
  </header>
</template>
