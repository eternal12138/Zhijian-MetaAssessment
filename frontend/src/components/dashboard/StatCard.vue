<script setup lang="ts">
withDefaults(defineProps<{
  icon: string
  tone: 'purple' | 'blue' | 'coral'
  label: string
  value: string | number
  unit?: string
  hint: string
  trend?: 'up' | 'neutral'
}>(), {
  unit: '',
  trend: 'neutral'
})
</script>

<template>
  <article class="stat-card">
    <span class="stat-icon" :class="tone"><i class="bi" :class="icon"></i></span>
    <div>
      <p>{{ label }}</p>
      <h3>{{ value }} <small v-if="unit">{{ unit }}</small></h3>
      <span class="trend" :class="trend"><i v-if="trend === 'up'" class="bi bi-arrow-up"></i> {{ hint }}</span>
    </div>
  </article>
</template>
