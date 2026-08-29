import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'
import * as vue from 'vue'
import { parse, compileTemplate } from 'vue/compiler-sfc'

const code = ts.transpileModule(fs.readFileSync(new URL('../src/composables/useLatestRequest.ts', import.meta.url), 'utf8').replace(/^import .*$/m, '').replace('export function', 'function'), {compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText
const create = new Function('ref', 'onScopeDispose', code + '; return useLatestRequest')
function fixture() { const scope=vue.effectScope(); let request; scope.run(()=>request=create(vue.ref, vue.onScopeDispose)()); return {scope,request} }
function deferred() { let resolve, reject; const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject} }

test('out-of-order pages and stale errors cannot replace the latest result', async()=>{
  const {scope,request}=fixture(), old=deferred(), current=deferred(); let value
  const a=request.run(()=>old.promise,v=>value=v)
  const b=request.run(()=>current.promise,v=>value=v)
  current.resolve('page 2');await b;old.reject(new Error('stale'));await a
  assert.equal(value,'page 2');assert.equal(request.error.value,'');assert.equal(request.loading.value,false);scope.stop()
})
test('filter debounce invalidation and unmount discard pending responses', async()=>{
  const {scope,request}=fixture(), old=deferred();let applied=false
  const a=request.run(()=>old.promise,()=>applied=true);request.invalidate();old.resolve('old');await a
  assert.equal(applied,false);assert.equal(request.loading.value,true)
  const next=deferred(),b=request.run(()=>next.promise,()=>applied=true);scope.stop();next.resolve('next');await b;assert.equal(applied,false)
})
test('failure is visible and successful retry clears it',async()=>{
  const {scope,request}=fixture();await request.run(()=>Promise.reject(new Error('offline')),()=>{})
  assert.equal(request.error.value,'offline');assert.equal(request.loading.value,false)
  await request.run(()=>Promise.resolve('ok'),()=>{});assert.equal(request.error.value,'');scope.stop()
})
test('four independent pagers render with bounded sizes, explicit batch scope and loading feedback',()=>{
  const source=fs.readFileSync(new URL('../src/views/TeacherCenterView.vue',import.meta.url),'utf8')
  assert.equal((source.match(/<SectionPagination /g)||[]).length,4)
  for(const name of ['qualityPageSize','taskOrderPageSize','reportsPageSize','pendingPageSize']) assert.match(source,new RegExp(`const ${name} = ref\\(10\\)`))
  assert.match(source,/生成本页/);assert.doesNotMatch(source,/一键批量生成全部报告/)
  assert.match(source,/dashboard\.unanalyzed_total/)
  assert.doesNotMatch(source,/filteredQualityRuns/)
  for(const filename of ['../src/views/TeacherCenterView.vue','../src/components/ui/SectionPagination.vue']) {
    const {descriptor}=parse(fs.readFileSync(new URL(filename,import.meta.url),'utf8'))
    assert.deepEqual(compileTemplate({source:descriptor.template.content,filename,id:'pagination'}).errors,[])
  }
})

test('pager exposes correct ranges and clamps typed page numbers',()=>{
  const {descriptor}=parse(fs.readFileSync(new URL('../src/components/ui/SectionPagination.vue',import.meta.url),'utf8'))
  const code=ts.transpileModule(descriptor.scriptSetup.content.replace(/^import .*$/gm,''),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText
  const props=vue.reactive({page:3,pageSize:10,total:26,label:'Reports',disabled:false}), events=[]
  const ui=new Function('computed','defineProps','defineEmits','withDefaults',code+';return {pages,start,end,jump}')(vue.computed,()=>props,()=>((...args)=>events.push(args)),v=>v)
  assert.equal(ui.pages.value,3);assert.equal(ui.start.value,21);assert.equal(ui.end.value,26)
  ui.jump({target:{value:999}});ui.jump({target:{value:-1}})
  assert.deepEqual(events,[['update:page',3],['update:page',1]])
  props.total=0;props.page=1;assert.equal(ui.pages.value,1);assert.equal(ui.start.value,0);assert.equal(ui.end.value,0)
})

test('page filters reset once, clear selection, and refresh clamps without a request loop',async()=>{
  const {descriptor}=parse(fs.readFileSync(new URL('../src/views/TeacherCenterView.vue',import.meta.url),'utf8'))
  const source=descriptor.scriptSetup.content.replace(/^import[\s\S]*?from ['"][^'"]+['"]\s*;?\r?\n/gm,'')
  const script=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText
  const calls=[],timers=new Map();let timerId=0
  const setTimer=fn=>{timers.set(++timerId,fn);return timerId},clearTimer=id=>timers.delete(id)
  const api={
    listRunQuality:async params=>{calls.push(['quality',params]);return {data:[],headers:{'x-total-count':'0'}}},
    taskOrderAssignments:async params=>{calls.push(['orders',params]);return {data:{students:[],tasks:[],total:0}}},
    dashboard:async params=>{calls.push(['dashboard',params]);return {data:{recent_reports:[],reports_page:1,pending_page:1}}}
  }
  const scope=vue.effectScope();let state
  scope.run(()=>{
    state=new Function('computed','onMounted','onUnmounted','ref','watch','useLatestRequest','useUserStore','researchApi','setTimeout','clearTimeout',script+';return {qualityPage,qualitySearch,taskOrderSearch,selectedStudents,reportsPage,pendingPage,loadDashboardPage}')(
      vue.computed,()=>{},()=>{},vue.ref,vue.watch,create(vue.ref,vue.onScopeDispose),()=>({profile:{role:'admin'}}),api,setTimer,clearTimer)
  })
  state.qualityPage.value=3;state.qualitySearch.value='new';state.selectedStudents.value=['hidden'];state.taskOrderSearch.value='class'
  await vue.nextTick()
  assert.equal(state.qualityPage.value,1);assert.deepEqual(state.selectedStudents.value,[])
  for(const callback of [...timers.values()])callback();timers.clear()
  await Promise.resolve();await vue.nextTick()
  assert.equal(calls.filter(([type])=>type==='quality').length,1)
  assert.equal(calls.find(([type])=>type==='quality')[1].search,'new')
  state.reportsPage.value=9;state.pendingPage.value=9;timers.clear()
  await state.loadDashboardPage();await vue.nextTick()
  assert.equal(state.reportsPage.value,1);assert.equal(state.pendingPage.value,1);assert.equal(timers.size,0)
  scope.stop()
})
