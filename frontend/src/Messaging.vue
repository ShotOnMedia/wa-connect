<script setup>
import {ref,watch,onBeforeUnmount} from 'vue'
import {api} from './api'
import Broadcasts from './Broadcasts.vue'
import Campaigns from './Campaigns.vue'
import FlowBuilder from './FlowBuilder.vue'

const props=defineProps({view:{type:String,default:'broadcasts'},currentUser:{type:Object,required:true}})
const channel=ref('telegram')
function selectChannel(value){channel.value=value}
watch([()=>props.view,channel],()=>{if(props.view==='flows')api.setFlowChannel(channel.value)},{immediate:true})
onBeforeUnmount(()=>api.setFlowChannel('whatsapp'))
</script>

<template>
<section class="messaging-page">
  <header class="messaging-head">
    <div><p class="eyebrow">Messaging</p><h1>{{view==='questionnaires'?'Questionnaires':view.charAt(0).toUpperCase()+view.slice(1)}}</h1>
      <p v-if="view==='broadcasts'">Create and track one-off messages to your audience.</p>
      <p v-else-if="view==='campaigns'">Plan multi-message campaigns across your messaging channels.</p>
      <p v-else-if="view==='flows'">Build and manage channel automations from one workspace.</p>
      <p v-else>Build reusable question sets for WhatsApp and Telegram flows.</p>
    </div>
    <div class="channel-tabs" role="tablist" aria-label="Messaging channel">
      <button :class="{active:channel==='whatsapp'}" @click="selectChannel('whatsapp')"><span class="dot wa">W</span> WhatsApp</button>
      <button :class="{active:channel==='telegram'}" @click="selectChannel('telegram')"><span class="dot tg">T</span> Telegram</button>
    </div>
  </header>

  <div v-if="view==='broadcasts'" class="embedded" :key="'broadcasts-'+channel"><Broadcasts :channel="channel"/></div>

  <div v-else-if="view==='campaigns'" class="coming"><span :class="['dot',channel==='telegram'?'tg':'wa']">{{channel==='telegram'?'T':'W'}}</span><div><strong>{{channel==='telegram'?'Telegram':'WhatsApp'}} Campaigns</strong><p>The campaign workspace is reserved for the new multi-message campaign engine.</p></div></div>

  <div v-else-if="view==='flows'" class="flow-host shared-flows" :key="channel"><FlowBuilder :current-user="currentUser" :channel="channel"/></div>
  <div v-else-if="view==='questionnaires'" class="embedded questionnaires"><Campaigns :channel="channel"/></div>
</section>
</template>

<style scoped>
.messaging-page{margin-left:220px;min-height:100vh;background:#f4f7f6;padding:30px 38px 60px}.messaging-head{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:20px}.messaging-head h1{font-size:30px;margin:2px 0 5px}.messaging-head p:last-child{margin:0;color:#74867e}.eyebrow{margin:0;text-transform:uppercase;color:#119052;font-size:11px;font-weight:800;letter-spacing:.08em}.channel-tabs{display:flex;background:#e8efeb;border-radius:11px;padding:4px;gap:3px}.channel-tabs button{display:flex;align-items:center;gap:7px;border:0;background:transparent;border-radius:8px;padding:9px 13px;color:#61736a;font-weight:700;cursor:pointer}.channel-tabs button.active{background:#fff;color:#182820;box-shadow:0 1px 3px rgba(20,50,35,.12)}.dot{width:23px;height:23px;border-radius:7px;display:grid;place-items:center;font-size:10px;font-weight:900;flex:0 0 auto}.dot.wa{background:#25d366;color:#07331f}.dot.tg{background:#229ed9;color:#fff}.embedded{margin:0 -38px -60px}.embedded :deep(.broadcast-page){padding-top:8px}.embedded :deep(.broadcast-head){justify-content:flex-end;margin-bottom:14px}.embedded :deep(.broadcast-head>div:first-child){display:none}.questionnaires :deep(.campaign-page){margin-left:0;padding-top:8px}.questionnaires :deep(.campaign-page>header){justify-content:flex-end;margin-top:0;margin-bottom:14px}.questionnaires :deep(.campaign-page>header>div:first-child){display:none}.shared-flows :deep(.flows-library-head){justify-content:flex-end;margin-bottom:14px}.shared-flows :deep(.flows-library-head>div:first-child){display:none}.flow-host{margin:0 -38px}.coming{display:flex;align-items:flex-start;gap:14px;background:#fff;border:1px dashed #cbd8d2;border-radius:14px;padding:26px}.coming .dot{width:38px;height:38px;border-radius:10px;font-size:13px}.coming strong{font-size:16px}.coming p{margin:5px 0 0;color:#74867e}@media(max-width:800px){.messaging-page{padding:24px 18px}.messaging-head{align-items:stretch;flex-direction:column}.channel-tabs{align-self:flex-start}.embedded,.flow-host{margin-left:-18px;margin-right:-18px}}
</style>