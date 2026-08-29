import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'
import * as vue from 'vue'
import { parse, compileTemplate } from 'vue/compiler-sfc'

const source = fs.readFileSync(new URL('../src/views/TeacherCenterView.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const script = ts.transpileModule(descriptor.scriptSetup.content.replace(/^import[\s\S]*?from ['"][^'"]+['"]\s*;?\r?\n/gm, ''), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
const row = (id, status = 'draft') => ({ id, run_id: `run-${id}`, user_name: id, username: id, generated_at: '2026-08-28T00:00:00Z', version_no: 1, status, can_reanalyze: true, quality_status: 'eligible', requires_review_count: 0, double_review_pending: 0 })

function fixture(rows, startAnalysis, confirm = async () => true) {
  const calls = [], notices = [], unmount = []
  let dashboardReads = 0
  const api = {
    startAnalysis: async (...args) => { calls.push(args); return startAnalysis(...args) },
    dashboard: async () => { dashboardReads++; return { data: { recent_reports: rows, reports_page: 1, pending_page: 1 } } }
  }
  const request = () => ({ loading: vue.ref(false), error: vue.ref(''), invalidate() {}, run: async (get, apply) => apply(await get()) })
  const state = new Function('computed', 'onMounted', 'onUnmounted', 'ref', 'watch', 'useLatestRequest', 'useUserStore', 'researchApi', 'confirmAction', 'notify', script + '; return {dashboard,selectedReports,selectableReports,allReportsSelected,toggleReportSelection,reanalyzeReports,reportRefreshResults,reportRefreshProgress,refreshingReports,stopReportRefresh,reportStatusLabel,reportChecksText}')(
    vue.computed, () => {}, fn => unmount.push(fn), vue.ref, () => {}, request, () => ({ profile: { role: 'admin' } }), api, confirm, (...args) => notices.push(args)
  )
  state.dashboard.value = { recent_reports: rows }
  return { state, calls, notices, unmount, get dashboardReads() { return dashboardReads } }
}

test('select only eligible drafts; all review statuses have readable labels and checks', () => {
  const rows = [row('a'), row('b', 'review_pending'), row('c', 'reviewed'), row('p', 'published'), row('x', 'archived'), row('u', 'unexpected')]
  const f = fixture(rows, async () => ({}))
  f.state.toggleReportSelection()
  assert.deepEqual(f.state.selectedReports.value, ['a', 'b', 'c'])
  assert.equal(f.state.allReportsSelected.value, true)
  for (const status of ['draft', 'review_pending', 'reviewed', 'published', 'archived']) assert.doesNotMatch(f.state.reportStatusLabel(status), /[a-z_]/)
  assert.equal(f.state.reportStatusLabel('unexpected'), '状态待确认')
  assert.match(f.state.reportChecksText({ ...row('a'), double_review_pending: null }), /尚未建立双人盲编批次/)
  assert.match(f.state.reportChecksText({ ...row('a'), requires_review_count: 2, double_review_pending: 3 }), /2 条.*3 条/)
  f.state.toggleReportSelection(); assert.deepEqual(f.state.selectedReports.value, [])
})

test('batch refresh is serial, preserves coding, binds source generation and reports partial failure', async () => {
  let finish
  const f = fixture([row('a'), row('b'), row('published', 'published')], async run => {
    if (run === 'run-a') return new Promise(resolve => { finish = () => resolve({ data: { status: 'completed' } }) })
    return { data: { status: 'failed', error_message: 'AI 调用失败，原草稿已保留' } }
  })
  f.state.selectedReports.value = ['a', 'b', 'published']
  const pending = f.state.reanalyzeReports()
  await Promise.resolve(); await Promise.resolve()
  assert.equal(f.calls.length, 1)
  assert.deepEqual(f.calls[0], ['run-a', false, { report_only: true, expected_generated_at: '2026-08-28T00:00:00Z' }])
  await f.state.reanalyzeReports(row('b')); assert.equal(f.calls.length, 1)
  finish(); await pending
  assert.equal(f.calls.length, 2)
  assert.deepEqual(f.state.reportRefreshResults.value.map(item => item.success), [true, false])
  assert.deepEqual(f.state.reportRefreshProgress.value, { completed: 2, total: 2 })
  assert.match(f.notices[0][0], /成功 1 份，失败 1 份/)
  assert.equal(f.state.refreshingReports.value, false)
  assert.equal(f.dashboardReads, 1)
  assert.deepEqual(f.state.selectedReports.value, ['b'])
})

test('cancel confirmation does not send requests; stopping leaves in-flight request intact', async () => {
  const cancelled = fixture([row('a')], () => assert.fail('cancelled request'), async () => false)
  await cancelled.state.reanalyzeReports(row('a')); assert.equal(cancelled.calls.length, 0)
  let finish
  const f = fixture([row('a'), row('b')], () => new Promise(resolve => { finish = () => resolve({ data: { status: 'completed' } }) }))
  f.state.toggleReportSelection()
  const pending = f.state.reanalyzeReports(); await Promise.resolve(); await Promise.resolve()
  f.state.stopReportRefresh.value = true
  finish(); await pending
  assert.equal(f.calls.length, 1)
  assert.equal(f.state.reportRefreshProgress.value.completed, 1)
  assert.match(f.notices[0][0], /未执行 1 份/)
})

test('leaving page stops remaining batch and single failed request is visible', async () => {
  const f = fixture([row('a')], async () => { throw new Error('请求状态未知，请刷新核对') })
  await f.state.reanalyzeReports(row('a'))
  assert.equal(f.state.reportRefreshResults.value[0].success, false)
  assert.match(f.state.reportRefreshResults.value[0].message, /状态未知/)
  assert.equal(f.state.refreshingReports.value, false)
  f.unmount.forEach(fn => fn())
  assert.equal(f.state.stopReportRefresh.value, true)
})

test('recent reports renders generation time, explicit selection scope, and no unrelated navigation', () => {
  const card = source.slice(source.indexOf('<h5 class="mb-1">最近报告'), source.indexOf('<h5>基础研究指标'))
  assert.match(card, /生成时间 ↓/)
  assert.match(card, /报告版本 V/)
  assert.match(card, /勾选仅作用于当前页/)
  assert.doesNotMatch(card, /待复核\/双评|进入双人复核|转录校订|bg-light text-dark/)
  assert.match(card, /role="alert"/)
  assert.deepEqual(compileTemplate({ source: descriptor.template.content, filename: 'TeacherCenterView.vue', id: 'recent-reports' }).errors, [])
})
