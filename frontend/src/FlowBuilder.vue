<script setup>
import { ref } from 'vue'
import FlowsLibrary from './FlowsLibrary.vue'
import VisualFlowBuilder from './VisualFlowBuilder.vue'

const props=defineProps({currentUser:{type:Object,required:true}})
const editingFlowId=ref(null)
const createNew=ref(false)
function editFlow(id){editingFlowId.value=Number(id);createNew.value=false}
function createFlow(){editingFlowId.value=null;createNew.value=true}
function backToLibrary(){editingFlowId.value=null;createNew.value=false}
</script>

<template>
  <VisualFlowBuilder v-if="editingFlowId||createNew" :current-user="currentUser" :initial-flow-id="editingFlowId" :create-new="createNew" @back="backToLibrary"/>
  <FlowsLibrary v-else @edit="editFlow" @create="createFlow"/>
</template>
