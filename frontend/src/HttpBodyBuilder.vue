<script setup>
import { computed, ref, watch } from 'vue'
const props=defineProps({modelValue:{default:()=>({})},fields:{type:Array,default:()=>[]},bodyType:{type:String,default:'json'}})
const emit=defineEmits(['update:modelValue'])
const systemKeys=new Set(['first_name','last_name','phone','subscriber_id','latitude','longitude','source'])
const rows=ref([])
let syncing=false
function rowsFromBody(body){
  if(!body||Array.isArray(body)||typeof body!=='object')return []
  return Object.entries(body).map(([key,value])=>{
    const text=value===null?'':String(value)
    const m=text.match(/^%([^%]+)%$/)
    return {key,type:m?'dynamic':'static',value:m?m[1]:text}
  })
}
watch(()=>props.modelValue,(body)=>{
  if(syncing){syncing=false;return}
  rows.value=rowsFromBody(body)
},{immediate:true,deep:true})
const systemFields=computed(()=>props.fields.filter(f=>systemKeys.has(String(f.key||''))))
const customFields=computed(()=>props.fields.filter(f=>!systemKeys.has(String(f.key||''))))
function commit(){
  const obj={}
  rows.value.forEach(r=>{
    const key=String(r.key||'').trim()
    if(!key)return
    obj[key]=r.type==='dynamic'?(r.value?`%${r.value}%`:''):r.value
  })
  syncing=true
  emit('update:modelValue',obj)
}
function update(i,prop,value){
  rows.value[i][prop]=value
  if(prop==='type')rows.value[i].value=''
  commit()
}
function add(){
  // Keep the new blank row locally until the user gives it a key. A blank key
  // cannot be represented in the object emitted through v-model.
  rows.value.push({key:'',type:'static',value:''})
}
function remove(i){rows.value.splice(i,1);commit()}
const preview=computed(()=>{
  const obj={}
  rows.value.forEach(r=>{const key=String(r.key||'').trim();if(key)obj[key]=r.type==='dynamic'?(r.value?`%${r.value}%`:''):r.value})
  return JSON.stringify(obj,null,2)
})
</script>
<template>
  <div class="body-builder">
    <div class="builder-head"><div><strong>Body Data</strong><small>Build {{bodyType==='form'?'form fields':'JSON'}} without writing it manually.</small></div><button type="button" @click="add">＋ Add field</button></div>
    <div v-if="rows.length" class="labels"><span>Key</span><span>Type</span><span>Value</span><span></span></div>
    <div v-for="(row,i) in rows" :key="i" class="body-row">
      <input :value="row.key" placeholder="e.g. subscriber_id" @input="update(i,'key',$event.target.value)">
      <select :value="row.type" @change="update(i,'type',$event.target.value)"><option value="static">Static Value</option><option value="dynamic">Dynamic Value</option></select>
      <template v-if="row.type==='dynamic'">
        <select :value="row.value" @change="update(i,'value',$event.target.value)">
          <option value="">Select subscriber field…</option>
          <optgroup v-if="systemFields.length" label="Subscriber / System Fields"><option v-for="f in systemFields" :key="f.id||f.key" :value="f.key">{{f.label||f.name||f.key}}</option></optgroup>
          <optgroup v-if="customFields.length" label="Custom Fields"><option v-for="f in customFields" :key="f.id||f.key" :value="f.key">{{f.label||f.name||f.key}}</option></optgroup>
        </select>
      </template>
      <input v-else :value="row.value" placeholder="Static value" @input="update(i,'value',$event.target.value)">
      <button type="button" class="delete" @click="remove(i)">×</button>
    </div>
    <div v-if="!rows.length" class="empty-builder">No body fields yet. Click <b>+ Add field</b> to start.</div>
    <details class="preview"><summary>Generated Body Preview</summary><pre>{{preview}}</pre></details>
  </div>
</template>
<style scoped>
.body-builder{margin-top:12px;border:1px solid #dce5df;border-radius:11px;padding:14px;background:#fbfdfc}.builder-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:13px}.builder-head strong,.builder-head small{display:block}.builder-head small{font-size:11px;color:#7b8b83;margin-top:3px}.builder-head button{border:1px solid #b9d9ca;background:#fff;color:#176f4b;border-radius:8px;padding:7px 10px;font-weight:700;cursor:pointer}.labels,.body-row{display:grid;grid-template-columns:minmax(150px,1fr) 155px minmax(190px,1.35fr) 36px;gap:9px;align-items:center}.labels{font-size:10px;text-transform:uppercase;font-weight:800;color:#72847b;padding:0 3px 6px}.body-row{margin-bottom:9px}.body-row input,.body-row select{width:100%;box-sizing:border-box;border:1px solid #d6e1db;background:#fff;border-radius:8px;padding:10px}.delete{height:39px;border:0;border-radius:8px;background:#fff0f0;color:#c33;font-size:17px;cursor:pointer}.empty-builder{padding:18px;text-align:center;border:1px dashed #d5e2dc;border-radius:8px;color:#7b8a83;background:#fff}.preview{margin-top:12px}.preview summary{cursor:pointer;color:#53675d;font-size:12px;font-weight:700}.preview pre{margin:9px 0 0;padding:12px;border-radius:8px;background:#f1f5f3;white-space:pre-wrap;font-size:11px;overflow:auto}@media(max-width:800px){.labels{display:none}.body-row{grid-template-columns:1fr}.delete{width:40px}}
</style>