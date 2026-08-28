// Development-only fixture: no network requests or business database mutations.
import { createApp, h, ref } from 'vue'
import 'bootstrap/dist/css/bootstrap.min.css'
import 'bootstrap-icons/font/bootstrap-icons.css'
import '../../src/styles/main.css'
import MacroAnalyticsDashboard from '../../src/components/dashboard/MacroAnalyticsDashboard.vue'
import { useTheme } from '../../src/composables/useTheme'
import { reportApi } from '../../src/api/reports'
import { researchApi } from '../../src/api/research'

const profile = (scope,label,values) => ({
  scope,label,counts:{monitoring:values[0],controlDebugging:values[1],evaluation:values[2]},
  percentages:{monitoring:values[0],controlDebugging:values[1],evaluation:values[2]},
  total:values.reduce((a,b)=>a+b,0),effective_dialogue_count:100,denominator_breakdown:{human_review:100},
  fallback_dialogue_count:0,unclassified_count:0,score_available:true,sample_count:10,primary_source:'production_model',
  scores:['monitoring','controlDebugging','evaluation'].map((dimension,i)=>({dimension,label:['监控（Monitoring）','调控（Regulation）','评估（Evaluation）'][i],score:values[i],max:100}))
})
const student={run_id:'fixture-run', task_ids:['pitching','jumps'],task_names:['最优投球机判断','跨项目最优运动员判断'],
  completed_at:'2026-08-28T10:00:00Z',score_available:true,source:'hybrid',effective_dialogue_count:100,
  denominator_breakdown:{human_review:100},dimension_counts:{monitoring:30,control_debugging:45,evaluation:15},
  dimension_scores:{monitoring:.3,control_debugging:.45,evaluation:.15},data_version:'fixture-long-version-'+ '0123456789abcdef'.repeat(12)}
reportApi.listMetacognitionMeasurements=async()=>({data:{items:[student],total:1}})
reportApi.getMetacognitionMeasurement=async(_id,task)=>({data:{...student,task_name:task==='pitching'?'最优投球机判断':'跨项目最优运动员判断'}})
researchApi.getMacroAnalytics=async()=>({data:{
  available_class_groups:['2026级实验班'],available_participants:[],
  radar_profiles:{selected:profile('participant','演示学生（仅模拟数据）',[30,45,15]),participant:profile('participant','演示学生（仅模拟数据）',[30,45,15]),
    class_group:profile('class','2026级实验班（较长班级名称换行测试）',[20,50,20]),overall:profile('overall','全体样本',[35,40,15])},
  profile_source:'仅用于页面布局验证的模拟数据，不代表实际研究结果。'.repeat(3),
  dimension_distribution:{total:90,counts:{monitoring:30,controlDebugging:45,evaluation:15},primary_source:'production_model'}
}})
createApp({setup(){
  const {setTheme}=useTheme();setTheme('light',false)
  const width=ref('1200'),role=ref('admin')
  return ()=>h('main',{style:{padding:'16px',maxWidth:'100%',minWidth:0}},[
    h('h1',{style:{fontSize:'20px'}},'布局验收 · 仅模拟数据，不写入数据库'),
    h('div',{style:{display:'flex',gap:'8px',flexWrap:'wrap'}},[
      h('button',{onClick:()=>setTheme('light',false)},'浅色'),h('button',{onClick:()=>setTheme('dark',false)},'深色'),
      h('select',{'aria-label':'卡片宽度',value:width.value,onChange:e=>width.value=e.target.value},['1600','1440','1200','940','800','600','375','320'].map(v=>h('option',{value:v},v))),
      h('select',{'aria-label':'身份',value:role.value,onChange:e=>role.value=e.target.value},['admin','teacher','student'].map(v=>h('option',{value:v},v)))
    ]),
    h('div',{style:{width:width.value+'px',maxWidth:'100%',minWidth:0}},[h(MacroAnalyticsDashboard,{key:role.value,userRole:role.value})])
  ])
}}).mount('#app')
