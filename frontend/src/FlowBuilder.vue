<script setup>
import { nextTick, ref } from 'vue'
import FlowsLibrary from './FlowsLibrary.vue'
import VisualFlowBuilder from './VisualFlowBuilderV2.vue'

const props=defineProps({currentUser:{type:Object,required:true}})
const editing=ref(false), builderHost=ref(null)
async function openBuilder(id=null){editing.value=true;await nextTick();if(id){let tries=0;const choose=()=>{const select=builderHost.value?.querySelector('.flow-picker > select');if(select&&[...select.options].some(o=>Number(o.value)===Number(id))){select.value=String(id);select.dispatchEvent(new Event('change',{bubbles:true}));return}if(tries++<20)setTimeout(choose,75)};choose()}else{setTimeout(()=>builderHost.value?.querySelector('.flow-picker form input')?.focus(),100)}}
function backToLibrary(){editing.value=false}
</script>

<template>
  <div v-if="editing" ref="builderHost" class="flow-builder-host">
    <button class="back-library" @click="backToLibrary">← All flows</button>
    <VisualFlowBuilder :current-user="currentUser"/>
  </div>
  <FlowsLibrary v-else @edit="openBuilder" @create="openBuilder()"/>
</template>

<style scoped>
.flow-builder-host{position:relative;width:100%;height:100%}.back-library{position:absolute;z-index:30;top:12px;left:272px;border:1px solid #d7e1db;border-radius:9px;background:#fff;color:#294638;font-weight:700;padding:9px 12px;cursor:pointer;box-shadow:0 4px 14px rgba(20,55,40,.07)}.back-library:hover{background:#eff8f3}@media(max-width:900px){.back-library{left:12px;top:68px}}
</style>
