<script setup>
import { nextTick, ref } from 'vue'
import { api } from './api'
import FlowsLibrary from './FlowsLibrary.vue'
import VisualFlowBuilder from './VisualFlowBuilderV2.vue'

const props=defineProps({currentUser:{type:Object,required:true},channel:{type:String,default:'whatsapp'}})
const editing=ref(false), builderHost=ref(null), opening=ref(false), openError=ref('')

function setChannel(){api.setFlowChannel(props.channel)}

async function openBuilder(id=null){
  if(opening.value)return
  opening.value=true
  openError.value=''
  try{
    setChannel()
    let flowId=id
    if(!flowId){
      const isTelegram=props.channel==='telegram'
      const channelName=isTelegram?'Telegram':'WhatsApp'
      const created=await api.createFlow({
        name:`Untitled ${channelName} Flow`,
        description:isTelegram?'Telegram automation flow':'',
        trigger_type:isTelegram?'keyword':'manual',
        trigger_value:isTelegram?'hello':null,
        status:'draft'
      })
      flowId=created.id
    }
    editing.value=true
    await nextTick()
    let tries=0
    const choose=()=>{
      const select=builderHost.value?.querySelector('.flow-picker > select, .toolbar > select')
      if(select&&[...select.options].some(o=>Number(o.value)===Number(flowId))){
        select.value=String(flowId)
        select.dispatchEvent(new Event('change',{bubbles:true}))
        return
      }
      if(tries++<30)setTimeout(choose,75)
    }
    choose()
  }catch(e){
    openError.value=e.message||'Could not open flow builder'
    editing.value=false
  }finally{
    opening.value=false
  }
}
function backToLibrary(){editing.value=false;setChannel()}
</script>

<template>
  <div v-if="editing" ref="builderHost" class="flow-builder-host" :data-channel="channel">
    <button class="back-library" @click="backToLibrary">← All flows</button>
    <div v-if="channel==='telegram'" class="telegram-runtime-tip"><b>Telegram runtime:</b> New flows start with keyword <code>hello</code> so they can be tested immediately. Configure the Text block, return to All flows, activate the flow, then message the bot <code>hello</code>.</div>
    <VisualFlowBuilder :current-user="currentUser" :channel="channel"/>
  </div>
  <template v-else>
    <p v-if="openError" class="open-error">{{openError}}</p>
    <FlowsLibrary :channel="channel" @edit="openBuilder" @create="openBuilder()"/>
  </template>
</template>

<style scoped>
.flow-builder-host{position:relative;width:100%;height:100%}.back-library{position:absolute;z-index:30;top:12px;left:272px;border:1px solid #d7e1db;border-radius:9px;background:#fff;color:#294638;font-weight:700;padding:9px 12px;cursor:pointer;box-shadow:0 4px 14px rgba(20,55,40,.07)}.back-library:hover{background:#eff8f3}.telegram-runtime-tip{position:absolute;z-index:29;top:8px;left:455px;max-width:650px;padding:7px 11px;border:1px solid #cfe7f1;border-radius:8px;background:#f1f9fc;color:#52736a;font-size:10px;line-height:1.35}.telegram-runtime-tip b{color:#1585b6}.telegram-runtime-tip code{padding:1px 4px;border-radius:4px;background:#dff2fa;color:#126d94}.open-error{margin:12px 32px;padding:10px 12px;border-radius:8px;background:#fff0f0;color:#a52b2b}@media(max-width:1100px){.telegram-runtime-tip{display:none}}@media(max-width:900px){.back-library{left:12px;top:68px}}
</style>