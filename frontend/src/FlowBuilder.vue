<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from './api'

const props = defineProps({ currentUser: { type: Object, required: true } })

const flows = ref([])
const selectedId = ref(null)
const selected = ref(null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const success = ref('')
const tags = ref([])
const fields = ref([])
const agents = ref([])

const canManage = computed(() => ['admin','manager'].includes(props.currentUser.role))
const createForm = reactive({ name:'', description:'', trigger_type:'manual', trigger_value:'', stop_on_reply:false })
const stepForm = reactive({ step_type:'send_message', text:'', tag_id:'', field_id:'', value:'', user_id:'', status:'open', seconds:60 })

const stepLabels = {
  send_message:'Send WhatsApp message', add_tag:'Add tag', remove_tag:'Remove tag',
  set_field:'Set custom field', assign_user:'Assign user', set_status:'Change conversation status', delay:'Delay'
}
const triggerLabels = { manual:'Manual', keyword:'Keyword', first_message:'First message' }

async function loadFlows(autoSelect=true){
  loading.value=true; error.value=''
  try{
    flows.value=await api.flows()
    if(autoSelect && !selectedId.value && flows.value.length) await selectFlow(flows.value[0].id)
    else if(selectedId.value){
      const item=flows.value.find(f=>f.id===selectedId.value)
      if(item) selected.value=item
    }
  }catch(e){error.value=e.message}finally{loading.value=false}
}
async function selectFlow(id){
  selectedId.value=id; error.value=''; success.value=''
  try{selected.value=await api.flow(id)}catch(e){error.value=e.message}
}
async function createFlow(){
  if(!canManage.value||saving.value)return
  saving.value=true;error.value='';success.value=''
  try{
    const created=await api.createFlow({...createForm,trigger_value:createForm.trigger_type==='keyword'?createForm.trigger_value:null})
    Object.assign(createForm,{name:'',description:'',trigger_type:'manual',trigger_value:'',stop_on_reply:false})
    await loadFlows(false); await selectFlow(created.id); success.value='Flow created.'
  }catch(e){error.value=e.message}finally{saving.value=false}
}
async function updateFlow(changes){
  if(!selected.value||!canManage.value)return
  saving.value=true;error.value='';success.value=''
  try{selected.value=await api.updateFlow(selected.value.id,changes);await loadFlows(false);success.value='Flow updated.'}
  catch(e){error.value=e.message}finally{saving.value=false}
}
async function deleteFlow(){
  if(!selected.value||!canManage.value||!confirm(`Delete flow “${selected.value.name}”?`))return
  try{await api.deleteFlow(selected.value.id);selectedId.value=null;selected.value=null;await loadFlows();success.value='Flow deleted.'}
  catch(e){error.value=e.message}
}
function buildConfig(){
  if(stepForm.step_type==='send_message') return {text:stepForm.text}
  if(stepForm.step_type==='add_tag'||stepForm.step_type==='remove_tag') return {tag_id:Number(stepForm.tag_id)}
  if(stepForm.step_type==='set_field') return {field_id:Number(stepForm.field_id),value:stepForm.value}
  if(stepForm.step_type==='assign_user') return {user_id:Number(stepForm.user_id)}
  if(stepForm.step_type==='set_status') return {status:stepForm.status}
  if(stepForm.step_type==='delay') return {seconds:Number(stepForm.seconds)}
  return {}
}
function stepValid(){
  if(stepForm.step_type==='send_message')return !!stepForm.text.trim()
  if(['add_tag','remove_tag'].includes(stepForm.step_type))return !!stepForm.tag_id
  if(stepForm.step_type==='set_field')return !!stepForm.field_id
  if(stepForm.step_type==='assign_user')return !!stepForm.user_id
  if(stepForm.step_type==='delay')return Number(stepForm.seconds)>0
  return true
}
async function addStep(){
  if(!selected.value||!stepValid()||saving.value)return
  saving.value=true;error.value='';success.value=''
  try{
    selected.value=await api.addFlowStep(selected.value.id,{step_type:stepForm.step_type,config:buildConfig()})
    stepForm.text='';stepForm.tag_id='';stepForm.field_id='';stepForm.value='';stepForm.user_id='';stepForm.status='open';stepForm.seconds=60
    await loadFlows(false);success.value='Step added.'
  }catch(e){error.value=e.message}finally{saving.value=false}
}
async function removeStep(step){
  if(!selected.value||!confirm('Remove this step?'))return
  try{selected.value=await api.deleteFlowStep(selected.value.id,step.id);await loadFlows(false)}catch(e){error.value=e.message}
}
async function moveStep(index,direction){
  if(!selected.value)return
  const steps=[...selected.value.steps],target=index+direction
  if(target<0||target>=steps.length)return
  ;[steps[index],steps[target]]=[steps[target],steps[index]]
  try{selected.value=await api.reorderFlowSteps(selected.value.id,steps.map(s=>s.id));await loadFlows(false)}catch(e){error.value=e.message}
}
function stepSummary(step){
  const c=step.config||{}
  if(step.step_type==='send_message')return c.text||'Empty message'
  if(step.step_type==='add_tag'||step.step_type==='remove_tag')return tags.value.find(t=>t.id===Number(c.tag_id))?.name||`Tag #${c.tag_id}`
  if(step.step_type==='set_field')return `${fields.value.find(f=>f.id===Number(c.field_id))?.label||`Field #${c.field_id}`} → ${c.value??''}`
  if(step.step_type==='assign_user')return agents.value.find(a=>a.id===Number(c.user_id))?.name||`User #${c.user_id}`
  if(step.step_type==='set_status')return c.status||'open'
  if(step.step_type==='delay')return `${c.seconds||0} seconds`
  return ''
}

onMounted(async()=>{
  try{[tags.value,fields.value,agents.value]=await Promise.all([api.contactTags(),api.contactFields(),api.agents()])}catch(_){}
  await loadFlows()
})
</script>

<template>
<section class="flows-page">
  <header class="flows-header"><div><p class="eyebrow">Automation</p><h1>Flows</h1><p>Build automated WhatsApp actions from triggers and ordered steps.</p></div><span class="contact-count">{{flows.length}} flows</span></header>
  <div class="flows-layout">
    <aside class="flow-list-card">
      <form v-if="canManage" class="flow-create" @submit.prevent="createFlow">
        <input v-model="createForm.name" required maxlength="150" placeholder="New flow name"/>
        <select v-model="createForm.trigger_type"><option value="manual">Manual</option><option value="keyword">Keyword</option><option value="first_message">First message</option></select>
        <input v-if="createForm.trigger_type==='keyword'" v-model="createForm.trigger_value" required maxlength="255" placeholder="Keyword, e.g. HELP"/>
        <button class="primary" :disabled="saving">Create flow</button>
      </form>
      <div v-if="loading" class="empty-list">Loading flows…</div>
      <div v-else-if="!flows.length" class="empty-list">No flows yet.</div>
      <button v-for="flow in flows" :key="flow.id" class="flow-list-row" :class="{selected:selectedId===flow.id}" @click="selectFlow(flow.id)">
        <span><strong>{{flow.name}}</strong><small>{{triggerLabels[flow.trigger_type]}} · {{flow.step_count}} step{{flow.step_count===1?'':'s'}}</small></span><b :class="['flow-status',flow.status]">{{flow.status}}</b>
      </button>
    </aside>

    <main class="flow-editor-card">
      <template v-if="selected">
        <div class="flow-editor-head"><div><p class="eyebrow">Flow builder</p><h2>{{selected.name}}</h2><p>{{selected.description||'No description yet.'}}</p></div><div class="flow-head-actions"><select :value="selected.status" :disabled="!canManage||saving" @change="updateFlow({status:$event.target.value})"><option value="draft">Draft</option><option value="active">Active</option><option value="paused">Paused</option></select><button v-if="canManage" class="secondary danger" @click="deleteFlow">Delete</button></div></div>

        <section class="flow-config-card"><div class="section-title"><div><p class="eyebrow">Trigger</p><h3>When should this flow start?</h3></div></div><div class="flow-config-grid"><label>Trigger<select :value="selected.trigger_type" :disabled="!canManage" @change="updateFlow({trigger_type:$event.target.value,trigger_value:$event.target.value==='keyword'?selected.trigger_value:null})"><option value="manual">Manual</option><option value="keyword">Keyword</option><option value="first_message">First message</option></select></label><label v-if="selected.trigger_type==='keyword'">Keyword<input :value="selected.trigger_value||''" :disabled="!canManage" placeholder="HELP" @change="updateFlow({trigger_value:$event.target.value})"/></label><label class="flow-check"><input type="checkbox" :checked="selected.stop_on_reply" :disabled="!canManage" @change="updateFlow({stop_on_reply:$event.target.checked})"/> Stop flow when contact replies</label></div></section>

        <section class="flow-canvas">
          <div class="flow-start"><span>START</span><strong>{{triggerLabels[selected.trigger_type]}}</strong><small v-if="selected.trigger_value">{{selected.trigger_value}}</small></div>
          <template v-for="(step,index) in selected.steps" :key="step.id"><div class="flow-connector"></div><article class="flow-step"><div class="flow-step-number">{{index+1}}</div><div class="flow-step-copy"><strong>{{stepLabels[step.step_type]}}</strong><p>{{stepSummary(step)}}</p></div><div v-if="canManage" class="flow-step-actions"><button :disabled="index===0" @click="moveStep(index,-1)">↑</button><button :disabled="index===selected.steps.length-1" @click="moveStep(index,1)">↓</button><button class="danger-link" @click="removeStep(step)">×</button></div></article></template>
          <div v-if="!selected.steps.length" class="flow-empty">Add the first action below.</div>
        </section>

        <section v-if="canManage" class="flow-add-card"><div class="section-title"><div><p class="eyebrow">Next action</p><h3>Add a step</h3></div></div><form @submit.prevent="addStep"><div class="flow-add-grid"><label>Action<select v-model="stepForm.step_type"><option v-for="(label,key) in stepLabels" :key="key" :value="key">{{label}}</option></select></label><label v-if="stepForm.step_type==='send_message'" class="wide">Message<textarea v-model="stepForm.text" rows="3" maxlength="4096" placeholder="Message to send…"/></label><label v-if="['add_tag','remove_tag'].includes(stepForm.step_type)">Tag<select v-model="stepForm.tag_id"><option value="">Select tag…</option><option v-for="tag in tags" :key="tag.id" :value="tag.id">{{tag.name}}</option></select></label><template v-if="stepForm.step_type==='set_field'"><label>Field<select v-model="stepForm.field_id"><option value="">Select field…</option><option v-for="field in fields" :key="field.id" :value="field.id">{{field.label}}</option></select></label><label>Value<input v-model="stepForm.value"/></label></template><label v-if="stepForm.step_type==='assign_user'">User<select v-model="stepForm.user_id"><option value="">Select user…</option><option v-for="agent in agents" :key="agent.id" :value="agent.id">{{agent.name}}</option></select></label><label v-if="stepForm.step_type==='set_status'">Status<select v-model="stepForm.status"><option value="open">Open</option><option value="pending">Pending</option><option value="resolved">Resolved</option></select></label><label v-if="stepForm.step_type==='delay'">Delay (seconds)<input v-model.number="stepForm.seconds" type="number" min="1"/></label></div><button class="primary" :disabled="saving||!stepValid()">Add step</button></form></section>
        <p v-if="success" class="success-message">{{success}}</p><p v-if="error" class="form-error">{{error}}</p>
      </template>
      <div v-else class="center-state">Create or select a flow to start building.</div>
    </main>
  </div>
</section>
</template>

<style scoped>
.flows-page{padding:38px;overflow:auto}.flows-header{max-width:1280px;margin:0 auto 24px;display:flex;align-items:end;justify-content:space-between}.flows-header>div>p:last-child{color:#75837b;margin-bottom:0}.flows-layout{max-width:1280px;margin:auto;display:grid;grid-template-columns:340px 1fr;gap:22px;align-items:start}.flow-list-card,.flow-editor-card{background:#fff;border:1px solid #e0e6e2;border-radius:16px;overflow:hidden;box-shadow:0 8px 30px rgba(20,40,30,.04)}.flow-create{padding:14px;border-bottom:1px solid #e9eeea;display:grid;gap:8px}.flow-create input,.flow-create select,.flow-config-grid input,.flow-config-grid select,.flow-add-grid input,.flow-add-grid select,.flow-add-grid textarea,.flow-head-actions select{border:1px solid #d7dfda;border-radius:9px;padding:9px 10px;background:#fff;outline:0}.flow-list-row{width:100%;border:0;border-bottom:1px solid #edf1ee;background:#fff;padding:14px;text-align:left;display:flex;gap:10px;justify-content:space-between;align-items:center}.flow-list-row:hover{background:#fafcfb}.flow-list-row.selected{background:#effaf3;box-shadow:inset 3px 0 #25d366}.flow-list-row strong,.flow-list-row small{display:block}.flow-list-row small{color:#7e8b84;margin-top:4px}.flow-status{font-size:9px;text-transform:uppercase;padding:5px 7px;border-radius:999px;background:#eff2f0;color:#68766f}.flow-status.active{background:#e4f7eb;color:#167346}.flow-status.paused{background:#fff5db;color:#896a16}.flow-editor-card{padding:26px}.flow-editor-head{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;padding-bottom:22px;border-bottom:1px solid #edf0ee}.flow-editor-head h2{margin:2px 0 5px}.flow-editor-head p:last-child{margin:0;color:#7d8982}.flow-head-actions{display:flex;gap:8px}.danger{color:#9d2c2c}.flow-config-card,.flow-add-card{border:1px solid #e3e9e5;border-radius:13px;padding:18px;background:#fbfcfb;margin-top:20px}.flow-config-grid,.flow-add-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.flow-config-grid label,.flow-add-grid label{display:grid;gap:6px;color:#59675f;font-size:12px;font-weight:700}.flow-add-grid label.wide{grid-column:1/-1}.flow-check{display:flex!important;grid-column:1/-1;align-items:center;grid-template-columns:auto 1fr!important}.flow-check input{width:auto}.flow-canvas{padding:28px 0;display:flex;flex-direction:column;align-items:center}.flow-start{min-width:220px;text-align:center;border:1px solid #cfe5d7;background:#f0faf4;border-radius:13px;padding:13px}.flow-start span{display:block;color:#17834d;font-size:9px;font-weight:900;letter-spacing:.12em}.flow-start strong,.flow-start small{display:block}.flow-start small{color:#718179;margin-top:3px}.flow-connector{height:26px;width:2px;background:#cfdad3}.flow-step{width:min(620px,100%);display:grid;grid-template-columns:36px 1fr auto;gap:12px;align-items:center;border:1px solid #dfe6e1;border-radius:13px;background:#fff;padding:13px 14px;box-shadow:0 4px 14px rgba(20,40,30,.04)}.flow-step-number{width:31px;height:31px;border-radius:9px;background:#18392c;color:#fff;display:grid;place-items:center;font-weight:900}.flow-step-copy strong{display:block}.flow-step-copy p{margin:4px 0 0;color:#77857d;white-space:pre-wrap}.flow-step-actions{display:flex;gap:5px}.flow-step-actions button{width:30px;height:30px;border:1px solid #d7dfda;background:#fff;border-radius:8px}.flow-step-actions .danger-link{color:#a33}.flow-empty{color:#89948e;padding:25px}.flow-add-card .primary{margin-top:14px}@media(max-width:1000px){.flows-layout{grid-template-columns:1fr}.flow-config-grid,.flow-add-grid{grid-template-columns:1fr}}
</style>
