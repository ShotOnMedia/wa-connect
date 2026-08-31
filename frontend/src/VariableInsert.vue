<script setup>
import { computed, ref } from 'vue'

const props=defineProps({fields:{type:Array,default:()=>[]}})
const emit=defineEmits(['insert'])
const open=ref(false)
const search=ref('')
const filtered=computed(()=>{
  const q=search.value.trim().toLowerCase()
  return props.fields.filter(f=>{
    const label=String(f.label||f.name||f.key||'')
    const key=String(f.key||'')
    return !q||label.toLowerCase().includes(q)||key.toLowerCase().includes(q)
  })
})
function choose(field){
  if(!field?.key)return
  emit('insert',`%${field.key}%`)
  open.value=false
  search.value=''
}
</script>

<template>
  <div class="variable-insert">
    <button type="button" class="insert-button" @click="open=!open">＋ Insert Variable</button>
    <div v-if="open" class="variable-menu">
      <div class="menu-head"><b>Custom fields</b><button type="button" @click="open=false">×</button></div>
      <input v-model="search" placeholder="Search custom fields…" autofocus>
      <div class="variable-list">
        <button v-for="field in filtered" :key="field.id||field.key" type="button" @click="choose(field)">
          <span>{{field.label||field.name||field.key}}</span>
          <code>%{{field.key}}%</code>
        </button>
        <p v-if="!filtered.length">No matching custom fields.</p>
      </div>
      <small>Selecting a field inserts its variable into the message.</small>
    </div>
  </div>
</template>

<style scoped>
.variable-insert{position:relative;margin-top:7px}.insert-button{border:1px solid #cfe3d9!important;background:#f3faf6!important;color:#167348;padding:7px 10px!important;border-radius:7px!important;font-size:11px;font-weight:700;cursor:pointer}.variable-menu{position:absolute;z-index:90;left:0;top:38px;width:310px;background:#fff;border:1px solid #d8e4df;border-radius:10px;box-shadow:0 12px 30px rgba(20,45,35,.18);padding:10px}.menu-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}.menu-head button{border:0!important;background:none!important;font-size:18px;cursor:pointer}.variable-menu>input{width:100%;box-sizing:border-box;margin-bottom:8px}.variable-list{max-height:230px;overflow:auto}.variable-list button{display:flex!important;flex-direction:column!important;align-items:flex-start!important;gap:2px!important;width:100%;border:0!important;border-bottom:1px solid #edf2ef!important;background:#fff!important;padding:9px!important;text-align:left;cursor:pointer}.variable-list button:hover{background:#f2faf6!important}.variable-list span{font-size:12px;font-weight:700}.variable-list code{font-size:10px;color:#168653}.variable-list p{font-size:11px;color:#7c8b85;padding:8px}.variable-menu>small{display:block;margin-top:8px;color:#7c8b85;font-size:10px}
</style>
