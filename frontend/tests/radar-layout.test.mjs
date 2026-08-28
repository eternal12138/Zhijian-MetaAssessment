import {test} from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'
import * as vue from 'vue'
import { parse, compileStyle, compileTemplate } from 'vue/compiler-sfc'

const helper=ts.transpileModule(fs.readFileSync(new URL('../src/components/charts/radarLayout.ts',import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText
const {radarLayout,radarAxisLabel,escapeChartText}=await import('data:text/javascript;base64,'+Buffer.from(helper).toString('base64'))
test('label room is reserved across phone, tablet and desktop container widths',()=>{
  for(const width of [200,240,280,320,375,480,640,900]){
    const {radius,labelWidth,center}=radarLayout(width,320)
    assert.ok(radius>0)
    assert.ok(radius*Math.sqrt(3)/2+labelWidth/2+14<=width/2)
    assert.ok(center[1]-radius>=52)
    assert.ok(center[1]+radius/2<=320-52)
    assert.equal(center[0],width/2)
    assert.ok(Math.abs(((center[1]-radius)+(center[1]+radius/2))/2-160)<.001)
  }
  assert.equal(radarLayout(0,0).radius,0)
})
test('non-triangular radar consumers retain a centred circular layout',()=>{
  for(const count of [4,5,6]){
    const {radius,labelWidth,center}=radarLayout(480,320,count)
    assert.deepEqual(center,[240,160])
    assert.ok(radius+labelWidth/2+14<=240)
    assert.ok(radius+52<=160)
  }
})
test('both role layouts isolate the chart from legacy grid styles and separate metadata',()=>{
  const source=fs.readFileSync(new URL('../src/components/dashboard/MacroAnalyticsDashboard.vue',import.meta.url),'utf8')
  const {descriptor}=parse(source)
  const template=descriptor.template.content
  assert.equal((template.match(/class="measurement-radar-stage"/g)||[]).length,2)
  assert.equal((template.match(/class="radar-context"/g)||[]).length,2)
  assert.ok(!/class="radar-wrap"/.test(template))
  assert.equal(compileTemplate({source:template,filename:'MacroAnalyticsDashboard.vue',id:'radar-test'}).errors.length,0)
  const style=compileStyle({source:descriptor.styles[0].content,filename:'MacroAnalyticsDashboard.vue',id:'data-v-radar-test',scoped:true})
  assert.equal(style.errors.length,0)
  const stage=style.code.match(/\.measurement-radar-stage\[data-v-radar-test\]\s*\{([^}]+)\}/)[1]
  assert.match(stage,/display:\s*grid/)
  assert.match(stage,/place-items:\s*center/)
  assert.match(stage,/width:\s*100%/)
  assert.match(style.code,/\.measurement-radar-stage\[data-v-radar-test\] \.radar-chart-wrapper/)
  assert.match(style.code,/grid-column:\s*1 \/ -1/)
})
test('bilingual axes wrap without deleting their English explanation',()=>{
  assert.equal(radarAxisLabel('监控（Monitoring）'),'监控\n（Monitoring）')
  assert.equal(radarAxisLabel('调控 (Regulation)'),'调控\n(Regulation)')
  assert.equal(radarAxisLabel('评估'),'评估')
})
test('tooltip names cannot inject HTML',()=>assert.equal(escapeChartText('<img src="x">&'), '&lt;img src=&quot;x&quot;&gt;&amp;'))

const source=fs.readFileSync(new URL('../src/components/charts/RadarChart.vue',import.meta.url),'utf8')
const script=source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm,'').replace(/^use\(.*$/gm,'')
const compiled=ts.transpileModule(script,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.None}}).outputText
function fixture(){
  const theme=vue.ref('light'),frames=new Map(),callbacks={},options=[]
  let id=0,disconnects=0,disposes=0,resizeCount=0,initCount=0
  const fakeChart={clear(){},setOption(o){options.push(o)},off(){},on(){},resize(){resizeCount++},dispose(){disposes++},dispatchAction(){}}
  const scores=['监控（Monitoring）','调控（Regulation）','评估（Evaluation）'].map((label,i)=>({label,dimension:String(i),score:30,max:100}))
  const props=vue.reactive({scores,name:'个人',comparisonSeries:[{name:'全班',scores}],height:320,globalMax:100})
  const scope=vue.effectScope()
  const state=scope.run(()=>new Function('vue','testTheme','testProps','hooks','echarts','ResizeObserver','window','getComputedStyle','requestAnimationFrame','cancelAnimationFrame','radarLayout','radarAxisLabel','escapeChartText',`
    const {computed,ref,watch}=vue;
    const onMounted=f=>hooks.mount=f, onBeforeUnmount=f=>hooks.unmount=f;
    const defineProps=()=>testProps,withDefaults=x=>x,defineEmits=()=>()=>{},useTheme=()=>({theme:testTheme});
    ${compiled}
    return {chartRef,renderChart,legendItems,hiddenSeries,toggleSeries};
  `)(vue,theme,props,callbacks,{init(){initCount++;return fakeChart}},class {constructor(cb){callbacks.resize=cb}observe(){}disconnect(){disconnects++}},
    {addEventListener(){},removeEventListener(){},matchMedia(){return {matches:true}}},
    ()=>({getPropertyValue(){return ''}}),cb=>{frames.set(++id,cb);return id},n=>frames.delete(n),radarLayout,radarAxisLabel,escapeChartText))
  state.chartRef.value={clientWidth:480,clientHeight:320}
  callbacks.mount()
  return {state,theme,options,callbacks,props,stats:()=>({disconnects,disposes,resizeCount,initCount}),flush(){const pending=[...frames.values()];frames.clear();pending.forEach(f=>f())},stop(){callbacks.unmount();scope.stop()}}
}
test('explicit light mode wins over a dark OS, and switching theme redraws the same instance',async()=>{
  const f=fixture()
  try{
    assert.deepEqual(f.options.at(-1).radar.splitArea.areaStyle.color,['#ffffff','#f8f8fc'])
    f.theme.value='dark';await vue.nextTick();f.flush()
    assert.deepEqual(f.options.at(-1).radar.splitArea.areaStyle.color,['#1a1b26','#222434'])
    f.theme.value='light';await vue.nextTick();f.flush()
    assert.equal(f.options.at(-1).tooltip.backgroundColor,'#ffffff')
    assert.equal(f.stats().initCount,1)
  }finally{f.stop()}
})
test('container resize recalculates geometry; legends remain selected after redraw; cleanup disposes resources',()=>{
  const f=fixture()
  const first=f.options.at(-1).radar.radius
  f.state.toggleSeries('全班')
  f.state.chartRef.value.clientWidth=240;f.callbacks.resize();f.flush()
  assert.ok(f.options.at(-1).radar.radius<first)
  assert.equal(f.options.at(-1).legend.selected['全班'],false)
  assert.equal(f.options.at(-1).tooltip.confine,true)
  f.stop()
  assert.equal(f.stats().disconnects,1)
  assert.equal(f.stats().disposes,1)
})
