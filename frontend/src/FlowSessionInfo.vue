<script setup>
import { onBeforeUnmount,ref,watch } from 'vue'
import { api } from './api'
const props=defineProps({conversationId:{type:Number,default:null},channel:{type:String,default:'telegram'}})
const session=ref(null),loading=ref(false)
let timer=null
function pretty(value){return String(value||'').replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase())}
function time(value){if(!value)return '—';return new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short'}).format(new Date(value))}
async function load(){if(!props.conversationId)return;loading.value=true;try{session.value=props.channel==='telegram'?await api.telegramFlowSession(props.conversationId):await api.flowSession(props.conversationId)}catch(_){session.value=null}finally{loading.value=false}}
watch(()=>props.conversationId,async()=>{await load()},{immediate:true})
timer=setInterval(load,3000)
onBeforeUnmount(()=>timer&&clearInterval(timer))
defineExpose({refresh:load})
</script>

<template>
<section class="flow-info">
  <div class="flow-head"><div><p>AUTOMATION</p><h4>Current Flow</h4></div><span v-if="session" class="status" :class="session.status">{{pretty(session.status)}}</span></div>
  <div v-if="loading&&!session" class="flow-empty">Checking flow…</div>
  <div v-else-if="!session||['reset','completed','failed'].includes(session.status)" class="flow-empty"><b>No active flow</b><span>This subscriber is currently in a neutral automation state.</span></div>
  <template v-else>
    <div class="flow-name">{{session.flow_name}}</div>
    <dl>
      <div><dt>Current block</dt><dd>{{session.current_node_title||pretty(session.current_node_type)||'Processing'}}</dd></div>
      <div v-if="session.waiting_for"><dt>Waiting for</dt><dd>{{pretty(session.waiting_for)}}</dd></div>
      <div><dt>Started</dt><dd>{{time(session.started_at)}}</dd></div>
      <div><dt>Last activity</dt><dd>{{time(session.updated_at)}}</dd></div>
    </dl>
  </template>
</section>
</template>

<style scoped>
.flow-info{margin:0 0 14px;background:#fff;border:1px solid #dce8e3;border-radius:10px;padding:12px}.flow-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px}.flow-head p{margin:0;color:#229ed9;font-size:8px;font-weight:900;letter-spacing:.08em}.flow-head h4{margin:2px 0 0;font-size:13px;color:#173026}.status{padding:3px 7px;border-radius:999px;background:#eaf8f2;color:#17704f;font-size:8px;font-weight:900;text-transform:uppercase}.status.waiting{background:#fff5dc;color:#8a6500}.flow-name{padding:10px;border-radius:8px;background:#edf8fd;color:#147da9;font-size:12px;font-weight:800;margin-bottom:7px}.flow-info dl{margin:0}.flow-info dl div{display:flex;justify-content:space-between;gap:12px;padding:7px 0;border-bottom:1px solid #edf1ef}.flow-info dl div:last-child{border-bottom:0}.flow-info dt{font-size:9px;color:#7a8b83}.flow-info dd{margin:0;font-size:9px;font-weight:700;text-align:right;color:#263b32}.flow-empty{padding:10px;border-radius:8px;background:#f5f8f7;color:#74867e;font-size:10px}.flow-empty b,.flow-empty span{display:block}.flow-empty b{color:#40554b;margin-bottom:3px}.flow-empty span{line-height:1.4}
</style>
