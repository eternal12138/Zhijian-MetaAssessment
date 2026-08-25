import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { AssessmentReport } from '../types/assessment'

export const useReportStore = defineStore('report', () => {
  const reports = ref<AssessmentReport[]>([])
  const latestReport = computed(() => reports.value[0] ?? null)

  function addReport(report: AssessmentReport) { reports.value.unshift(report) }
  function clearReports() { reports.value = [] }

  return { reports, latestReport, addReport, clearReports }
}, {
  persist: {
    key: 'mc-report',
    storage: localStorage,
    pick: ['reports']
  }
})
