// Exercise the actual Vue setup script without a browser or production API.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'
import * as vue from 'vue'

const source = fs.readFileSync(new URL('../src/components/dashboard/MacroAnalyticsDashboard.vue', import.meta.url), 'utf8')
const script = source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
const compiled = ts.transpileModule(script, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None } }).outputText
function setup(api, role = 'student') {
  const scope = vue.effectScope()
  const state = scope.run(() => new Function('vue', 'reportApi', 'researchApi', 'role', `
    const {computed,ref,watch}=vue;
    const onMounted=()=>{};
    const defineProps=()=>({userRole:role,classGroups:[]});
    const withDefaults=(props)=>props;
    ${compiled}
    return {fetchRealMacroData,fetchSelectedTaskMeasurement,selectedTaskId,selectedMeasurementRunId,taskMeasurement,taskMeasurementLoading,taskErrorMessage,errorMessage,selectedMeasurement,studentRadarScores,measurementHistory,formatMeasurementOption,analytics,hasRadarData,denominatorDescription};
  `)(vue, api, { getMacroAnalytics: async () => ({ data: null }) }, role))
  return { state, stop: () => scope.stop() }
}
const run = { run_id: 'r', task_ids: ['t'], task_names: ['任务'], score_available: true }
const tick = async () => { await vue.nextTick(); await Promise.resolve(); await vue.nextTick() }

test('latest completed run is selected even when only older runs have scores', async () => {
  const latest = {...run, run_id:'latest', score_available:false, completed_at:'2026-08-28T10:00:00Z'}
  const {state,stop}=setup({listMetacognitionMeasurements:async()=>({data:{items:[latest,run],total:2}})})
  try {
    await state.fetchRealMacroData()
    assert.equal(state.selectedMeasurementRunId.value,'latest')
    assert.deepEqual(state.studentRadarScores.value,[])
    assert.match(state.formatMeasurementOption(latest),/2026.*待分类/)
    assert.match(state.formatMeasurementOption({...latest,score_available:true}),/已有画像/)
    assert.match(state.formatMeasurementOption({...latest,score_available:true,fallback_dialogue_count:2}),/暂定结果/)
    assert.match(state.formatMeasurementOption({...latest,score_available:true,unclassified_count:1}),/暂定结果/)
  } finally {stop()}
})

test('failed task does not block whole-run, next task, or explicit retry', async () => {
  let fail=true
  const {state,stop}=setup({
    listMetacognitionMeasurements:async()=>({data:{items:[run],total:1}}),
    getMetacognitionMeasurement:async(_run,task)=>{if(fail)throw Error('task 500');return {data:{...run,task_id:task}}}
  })
  try {
    await state.fetchRealMacroData()
    state.selectedTaskId.value='t';await tick()
    assert.equal(state.taskErrorMessage.value,'task 500')
    assert.equal(state.errorMessage.value,'')
    state.selectedTaskId.value='all'
    assert.equal(state.taskErrorMessage.value,'')
    assert.equal(state.selectedMeasurement.value.run_id,'r')
    state.selectedTaskId.value='t';await tick()
    fail=false
    await state.fetchSelectedTaskMeasurement()
    assert.equal(state.taskErrorMessage.value,'')
    assert.equal(state.selectedMeasurement.value.task_id,'t')
    state.selectedTaskId.value='t2';await tick()
    assert.equal(state.selectedMeasurement.value.task_id,'t2')
  } finally {stop()}
})

test('switching rounds resets task/error immediately and rejects late failure', async () => {
  let reject
  const older={...run,run_id:'older',dimension_scores:{monitoring:0.7,control_debugging:0.2,evaluation:0.1}}
  const {state,stop}=setup({
    listMetacognitionMeasurements:async()=>({data:{items:[run,older],total:2}}),
    getMetacognitionMeasurement:()=>new Promise((_resolve,fail)=>{reject=fail})
  })
  try {
    await state.fetchRealMacroData()
    state.selectedTaskId.value='t'
    state.selectedMeasurementRunId.value='older'
    assert.equal(state.selectedTaskId.value,'all')
    assert.equal(state.taskMeasurementLoading.value,false)
    assert.equal(state.studentRadarScores.value[0].score,0.7)
    reject(Error('obsolete error'));await tick()
    assert.equal(state.taskErrorMessage.value,'')
    assert.equal(state.selectedMeasurement.value.run_id,'older')
  } finally {stop()}
})

test('history loading errors cannot be cleared by selecting a task', async () => {
  const {state,stop}=setup({listMetacognitionMeasurements:async()=>{throw Error('history failed')}})
  try {
    await state.fetchRealMacroData()
    await state.fetchSelectedTaskMeasurement()
    assert.equal(state.errorMessage.value,'history failed')
    assert.equal(state.taskErrorMessage.value,'')
  } finally {stop()}
})

test('all 206 completed rounds survive three-page loading; selection survives refresh', async () => {
  const items=Array.from({length:206},(_,i)=>({...run,run_id:`r${i}`,score_available:i!==0}))
  const pages=[]
  const {state,stop}=setup({listMetacognitionMeasurements:async(page,size)=>{
    pages.push(page);return {data:{items:items.slice((page-1)*size,page*size),total:items.length}}
  }})
  try {
    await state.fetchRealMacroData()
    assert.deepEqual(pages,[1,2,3])
    assert.equal(state.measurementHistory.value.length,206)
    assert.equal(state.selectedMeasurementRunId.value,'r0')
    state.selectedMeasurementRunId.value='r205'
    await state.fetchRealMacroData()
    assert.equal(state.selectedMeasurementRunId.value,'r205')
  } finally {stop()}
})

test('refresh also reloads the selected task', async () => {
  let version = 1, detailCalls = 0
  const {state,stop} = setup({
    listMetacognitionMeasurements: async () => ({data:{items:[run],total:1}}),
    getMetacognitionMeasurement: async () => {detailCalls++;return {data:{version}}}
  })
  try {
    await state.fetchRealMacroData(); await tick()
    state.selectedTaskId.value='t'; await tick()
    assert.equal(state.taskMeasurement.value.version, 1)
    version=2
    await state.fetchRealMacroData(); await tick()
    assert.equal(state.taskMeasurement.value.version, 2)
    assert.equal(detailCalls, 2)
  } finally { stop() }
})

test('switching to whole-run cancels task loading and ignores late response', async () => {
  let resolve
  const {state,stop} = setup({
    listMetacognitionMeasurements: async () => ({data:{items:[run],total:1}}),
    getMetacognitionMeasurement: () => new Promise(done => {resolve=done})
  })
  try {
    await state.fetchRealMacroData(); await tick()
    state.selectedTaskId.value='t'; await tick()
    assert.equal(state.taskMeasurementLoading.value,true)
    state.selectedTaskId.value='all'; await tick()
    assert.equal(state.taskMeasurementLoading.value,false)
    resolve({data:{stale:true}}); await tick()
    assert.equal(state.taskMeasurement.value,null)
    assert.equal(state.taskMeasurementLoading.value,false)
  } finally {stop()}
})

test('history fetch includes subsequent pages instead of silently hiding older runs', async () => {
  const pages=[]
  const {state,stop}=setup({ listMetacognitionMeasurements: async page => {
    pages.push(page);return {data:{items:[{...run,run_id:`r${page}`}],total:2}}
  }})
  try {await state.fetchRealMacroData();assert.deepEqual(pages,[1,2]);assert.equal(state.measurementHistory.value.length,2)}
  finally {stop()}
})

test('zero class hits with a real reviewed denominator can render; fallback is named', () => {
  const {state,stop}=setup({},'admin')
  try {
    state.analytics.value={radar_profiles:{selected:{total:0,effective_dialogue_count:3,score_available:true,scores:[{},{},{}]}}}
    assert.equal(state.hasRadarData.value,true)
    assert.match(state.denominatorDescription({human_review:10,label_total_fallback:2}),/暂定/)
    assert.match(source, /v-if="props.userRole === 'admin'" class="correction-upload/)
    assert.doesNotMatch(source, /三条轴合计约为 100%/)
  } finally {stop()}
})
