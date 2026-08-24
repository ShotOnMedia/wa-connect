<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from './api'

const emit=defineEmits(['edit','create'])
const flows=ref([]),loading=ref(false),error=ref(''),search=ref(''),status=ref('all'),trigger=ref('all')
const filtered=computed(()=>flows.value.filter(f=>{
  const q=search.value.trim().toLowerCase()
  return (!q||f.name.toLowerCase().includes(q)||(f.description||'').toLowerCase().includes(q)||(f.trigger_value||'').toLowerCase().includes(q)) && (status.value==='all'||f.status===status.value) && (trigger.value==='all'||f.trigger_type===trigger.value)
}))
function triggerLabel(f){if(f.trigger_type==='keyword')return `Keyword${f.trigger_value?`: ${f.trigger_value}`:''}`;if(f.trigger_type==='first_message')return 'First message';return 'Manual'}
function fmt(v){if(!v)return '—';return new Intl.DateTimeFormat(undefined,{day:'numeric',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(v))}
async function load(){loading.value=true;error.value='';try{flows.value=await api.flows()}catch(e){error.value=e.message}finally{loading.value=false}}
async function remove(f){if(!confirm(`Delete “${f.name}”? This cannot be undone.`))return;try{await api.deleteFlow(f.id);await load()}catch(e){error.value=e.message}}
async function toggle(f){try{await api.updateFlow(f.id,{status:f.status==='active'?'paused':'active'});await load()}catch(e){error.value=e.message}}
onMounted(load)
</script>

<template>
<section class="flows-library">
  <header class="flows-library-head"><div><p class="eyebrow">Automation</p><h1>Flows</h1><p>Build, organise and manage your WhatsApp automations.</p></div><button class="primary" @click="emit('create')">＋ Create flow</button></header>
  <div class="flows-card">
    <div class="flows-tools"><input v-model="search" placeholder="Search flows…"/><select v-model="status"><option value="all">All statuses</option><option value="draft">Draft</option><option value="active">Active</option><option value="paused">Paused</option></select><select v-model="trigger"><option value="all">All triggers</option><option value="keyword">Keyword</option><option value="first_message">First message</option><option value="manual">Manual</option></select><button class="refresh" @click="load">↻</button></div>
    <div v-if="error" class="error-box">{{error}}</div>
    <div v-if="loading" class="flows-empty">Loading flows…</div>
    <div v-else-if="!filtered.length" class="flows-empty"><strong>No flows found</strong><span>Create your first automation or change the filters above.</span></div>
    <div v-else class="flows-table-wrap"><table class="flows-table"><thead><tr><th>Name</th><th>Trigger</th><th>Status</th><th>Steps</th><th>Updated</th><th class="actions-col">Actions</th></tr></thead><tbody><tr v-for="f in filtered" :key="f.id"><td><button class="flow-name" @click="emit('edit',f.id)"><strong>{{f.name}}</strong><small>{{f.description||'No description'}}</small></button></td><td><span class="trigger-pill">{{triggerLabel(f)}}</span></td><td><span :class="['library-status',f.status]">{{f.status}}</span></td><td>{{f.step_count||0}}</td><td>{{fmt(f.updated_at)}}</td><td><div class="flow-actions"><button title="Edit" @click="emit('edit',f.id)">✎</button><button :title="f.status==='active'?'Pause':'Activate'" @click="toggle(f)">{{f.status==='active'?'Ⅱ':'▶'}}</button><button class="danger" title="Delete" @click="remove(f)">×</button></div></td></tr></tbody></table></div>
    <footer class="flows-footer"><span>{{filtered.length}} of {{flows.length}} flows</span></footer>
  </div>
</section>
</template>

<style scoped>
.flows-library{width:min(1220px,calc(100% - 64px));margin:0 auto;padding:34px 0 60px}.flows-library-head{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:24px}.flows-library-head h1{margin:2px 0 8px;font-size:30px}.flows-library-head p:last-child{margin:0;color:#7b8b83}.primary{border:0;border-radius:10px;background:#18ad61;color:#fff;font-weight:800;padding:13px 18px;cursor:pointer}.flows-card{background:#fff;border:1px solid #dce5df;border-radius:16px;box-shadow:0 12px 30px rgba(20,55,40,.05);overflow:hidden}.flows-tools{display:flex;gap:10px;padding:18px;border-bottom:1px solid #e8eeea}.flows-tools input{flex:1;min-width:220px}.flows-tools input,.flows-tools select{border:1px solid #d6e0da;border-radius:9px;padding:10px 12px;background:#fff}.flows-tools select{min-width:150px}.refresh{width:42px;border:1px solid #d6e0da;border-radius:9px;background:#fff;cursor:pointer}.flows-table-wrap{overflow:auto}.flows-table{width:100%;border-collapse:collapse;min-width:850px}.flows-table th{padding:12px 18px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#829188;background:#f7faf8;border-bottom:1px solid #e5ece8}.flows-table td{padding:15px 18px;border-bottom:1px solid #edf1ef;vertical-align:middle}.flows-table tbody tr:hover{background:#f9fcfa}.flow-name{display:flex;flex-direction:column;gap:3px;text-align:left;border:0;background:none;padding:0;cursor:pointer;color:#17231d}.flow-name strong{font-size:14px}.flow-name small{color:#89968f}.trigger-pill{display:inline-block;padding:5px 9px;border-radius:999px;background:#eef6f1;color:#365746;font-size:12px}.library-status{display:inline-block;padding:5px 9px;border-radius:999px;font-size:11px;font-weight:800;text-transform:uppercase}.library-status.active{background:#e4f7eb;color:#08763e}.library-status.draft{background:#f0f2f1;color:#68746e}.library-status.paused{background:#fff2d8;color:#91630b}.actions-col{text-align:right!important}.flow-actions{display:flex;justify-content:flex-end;gap:7px}.flow-actions button{width:34px;height:34px;border:1px solid #d9e3dd;border-radius:8px;background:#fff;cursor:pointer}.flow-actions button:hover{background:#eef8f2}.flow-actions .danger{color:#b52d2d}.flows-footer{padding:13px 18px;color:#89968f;font-size:12px;background:#fafcfb}.flows-empty{padding:70px 20px;text-align:center;color:#819087;display:flex;flex-direction:column;gap:6px}.error-box{margin:14px 18px;padding:10px 12px;border-radius:8px;background:#fff0f0;color:#b22}.eyebrow{text-transform:uppercase;letter-spacing:.12em;font-size:11px!important;font-weight:800;color:#07934d!important;margin:0}@media(max-width:850px){.flows-library{width:calc(100% - 28px)}.flows-library-head{align-items:flex-start;flex-direction:column}.flows-tools{flex-wrap:wrap}.flows-tools input{flex-basis:100%}}
</style>