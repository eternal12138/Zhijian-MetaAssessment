import {test} from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'
import * as vue from 'vue'
import {parse,compileTemplate} from 'vue/compiler-sfc'

const source=fs.readFileSync(new URL('../src/views/ReportView.vue',import.meta.url),'utf8')
const {descriptor}=parse(source)
const script=ts.transpileModule(descriptor.scriptSetup.content.replace(/^import[\s\S]*?from ['"][^'"]+['"]\s*;?\r?\n/gm,''),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText
function fixture(role='admin',api={},research={}) {
  const route={path:role==='student'?'/report':'/report-review',query:{id:'r1'}}, calls=[], scope=vue.effectScope()
  let state
  scope.run(()=>{
    state=new Function('computed','nextTick','onScopeDispose','ref','watch','useRoute','useRouter','useUserStore','reportApi','researchApi','confirmAction','notify',script+';return {loadPage,report,review,reviewConfirmed,publishReviewedReport,updateDraft,regenerating,measurementError,publishError,isLoading,selectedMeasurement}')(
      vue.computed,vue.nextTick,vue.onScopeDispose,vue.ref,()=>{},()=>route,()=>({replace(){}}),()=>({profile:{role}}),api,
      {publishReport:async(...args)=>calls.push(args),...research},async()=>true,()=>{})
  })
  return {state,route,calls,scope}
}
const result=id=>({data:{report:{id,run_id:'run',summary:'draft',workflow_status:'draft',generated_at:'2026-08-01T00:00:00Z'},owner:{name:'Student',username:'001'},can_publish:true,checks:[],measurement:null,measurement_error:''}})
test('student-facing card names the output as evidence-based uplift strategies',()=>{
  assert.match(source,/个性化提升策略/)
  assert.match(source,/依据本轮元认知模式及有效对话证据生成/)
  assert.doesNotMatch(source,/个性化练习建议/)
})
test('staff opens draft by ID without own-report list or student-only measurements',async()=>{
  const f=fixture('teacher',{review:async id=>result(id),list:()=>assert.fail('staff must not list own reports'),listMetacognitionMeasurements:()=>assert.fail('student-only API')})
  await f.state.loadPage();assert.equal(f.state.report.value.id,'r1');assert.equal(f.state.measurementError.value,'')
  await f.state.publishReviewedReport();assert.equal(f.calls.length,0)
  f.state.reviewConfirmed.value=true;await f.state.publishReviewedReport()
  assert.equal(f.calls.length,1);assert.equal(f.calls[0][0],'r1');assert.equal(f.calls[0][2].review_confirmed,true)
  assert.equal(f.calls[0][2].expected_generated_at,'2026-08-01T00:00:00Z');assert.equal(f.state.reviewConfirmed.value,false);f.scope.stop()
})
test('switching draft discards stale response and resets review confirmation',async()=>{
  let resolveOld
  const f=fixture('admin',{review:id=>id==='r1'?new Promise(resolve=>resolveOld=resolve):Promise.resolve(result(id))})
  const old=f.state.loadPage();f.state.reviewConfirmed.value=true;f.route.query.id='r2';await f.state.loadPage()
  resolveOld(result('r1'));await old
  assert.equal(f.state.report.value.id,'r2');assert.equal(f.state.reviewConfirmed.value,false);assert.equal(f.state.isLoading.value,false);f.scope.stop()
})
test('run link resolves exact draft and blocked review cannot publish',async()=>{
  const f=fixture('admin',{getByRun:async run=>{assert.equal(run,'run-2');return {data:{id:'r2'}}},review:async id=>({...result(id),data:{...result(id).data,can_publish:false}})})
  f.route.query={run:'run-2'};await f.state.loadPage();assert.equal(f.state.report.value.id,'r2')
  f.state.reviewConfirmed.value=true;await f.state.publishReviewedReport();assert.equal(f.calls.length,0);f.scope.stop()
})
test('student stays on own-report API and cannot invoke review or publish',async()=>{
  const f=fixture('student',{list:async()=>({data:[]}),listMetacognitionMeasurements:async()=>({data:{items:[]}}),get:async()=>({data:result('r1').data.report}),review:()=>assert.fail('student review')})
  await f.state.loadPage();f.state.reviewConfirmed.value=true;await f.state.publishReviewedReport();assert.equal(f.calls.length,0);f.scope.stop()
})

test('legacy report without frozen snapshot never substitutes a live measurement',async()=>{
  const f=fixture('student',{list:async()=>({data:[]}),listMetacognitionMeasurements:()=>assert.fail('history must not load'),
    get:async()=>({data:result('r1').data.report}),
    getMetacognitionMeasurement:()=>assert.fail('live measurement must not replace a historical snapshot')})
  await f.state.loadPage()
  assert.equal(f.state.selectedMeasurement.value,null)
  assert.match(f.state.measurementError.value,/未保存生成时的三维画像快照/)
  f.scope.stop()
})

test('frozen report snapshot survives failed history query and never loads live measurement',async()=>{
  const f=fixture('student',{list:async()=>({data:[]}),listMetacognitionMeasurements:()=>assert.fail('history must not load'),
    get:async()=>({data:{...result('r1').data.report,measurement_snapshot:{run_id:'run',data_version:'frozen-v1'}}}),
    getMetacognitionMeasurement:()=>assert.fail('must not replace frozen chart with live data')})
  await f.state.loadPage()
  assert.equal(f.state.selectedMeasurement.value.data_version,'frozen-v1')
  assert.equal(f.state.measurementError.value,'')
  f.scope.stop()
})

test('regenerating a draft prevents publication and requires fresh confirmation',async()=>{
  let finish
  let generation=0
  const f=fixture('admin',{review:async id=>{
    const response=result(id)
    response.data.report.generated_at=`2026-08-0${generation+1}T00:00:00Z`
    return response
  }},{startAnalysis:async run=>{
    assert.equal(run,'run');generation++
    return new Promise(resolve=>finish=()=>resolve({data:{status:'completed'}}))
  }})
  await f.state.loadPage();f.state.reviewConfirmed.value=true
  const update=f.state.updateDraft();await Promise.resolve()
  assert.equal(f.state.regenerating.value,true);assert.equal(f.state.reviewConfirmed.value,false)
  f.state.reviewConfirmed.value=true;await f.state.publishReviewedReport();assert.equal(f.calls.length,0)
  finish();await update
  assert.equal(f.state.regenerating.value,false);assert.equal(f.state.reviewConfirmed.value,false)
  assert.equal(f.state.report.value.generated_at,'2026-08-02T00:00:00Z')
  f.state.reviewConfirmed.value=true;await f.state.publishReviewedReport()
  assert.equal(f.calls[0][2].expected_generated_at,'2026-08-02T00:00:00Z');f.scope.stop()
})

test('failed draft update preserves readable content and reports the failure',async()=>{
  const f=fixture('admin',{review:async id=>result(id)}, {startAnalysis:async()=>({data:{status:'failed',error_message:'转录尚未准备完成'}})})
  await f.state.loadPage();f.state.reviewConfirmed.value=true;await f.state.updateDraft()
  assert.equal(f.state.report.value.id,'r1');assert.equal(f.state.reviewConfirmed.value,false)
  assert.equal(f.state.regenerating.value,false);assert.equal(f.state.publishError.value,'转录尚未准备完成');f.scope.stop()
})
test('review entry is role-gated, list has no direct publish, and draft print is labeled',()=>{
  const routes=fs.readFileSync(new URL('../src/router/index.ts',import.meta.url),'utf8')
  assert.match(routes,/path: '\/report-review'[\s\S]*?allowedRoles: \['teacher', 'admin'\]/)
  const list=fs.readFileSync(new URL('../src/views/TeacherCenterView.vue',import.meta.url),'utf8')
  assert.match(list,/查看草稿/);assert.doesNotMatch(list,/@click="publish\(/);assert.doesNotMatch(list,/@click="bulkPublish"/)
  assert.match(source,/草稿·未发布/);assert.match(source,/review-controls \{ display:none !important/)
  assert.doesNotMatch(source,/与历史记录对比/)
  assert.match(source,/<h6>本轮元认知模式<\/h6>/)
  assert.match(source,/群体常模.*待接入/)
  assert.match(source,/v-if="isReviewer" class="row g-4 mt-1 dimension-grid"/)
  assert.match(source,/v-if="isReviewer" class="card border-0 shadow-sm mt-4"/)
  assert.deepEqual(compileTemplate({source:descriptor.template.content,filename:'ReportView.vue',id:'review'}).errors,[])
})
