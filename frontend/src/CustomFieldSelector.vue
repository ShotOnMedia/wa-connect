<script setup>
import { computed, ref, watch } from 'vue'
import { api } from './api'

const props=defineProps({modelValue:{default:''},fields:{type:Array,default:()=>[]},valueMode:{type:String,default:'id'},emptyLabel:{type:String,default:'Select a field…'},allowEmpty:{type:Boolean,default:true}})
const emit=defineEmits(['update:modelValue','field-created'])
const CREATE='__create_new__'
const selected=ref(props.modelValue??''),creating=ref(false),label=ref(''),key=ref(''),fieldType=ref('text'),error=ref(''),saving=ref(false),keyTouched=ref(false),createdFields=ref([])
const availableFields=computed(()=>{const map=new Map();for(const f of [...props.fields,...createdFields.value])map.set(String(f.id??f.key),f);return [...map.values()]})
watch(()=>props.modelValue,v=>selected.value=v??'')
watch(label,v=>{if(!keyTouched.value)key.value=slug(v)})
function slug(v){return String(v||'').trim().toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_+|_+$/g,'')}
function optionValue(f){return props.valueMode==='key'?f.key:f.id}
function changed(){if(selected.value===CREATE){creating.value=true;selected.value='';emit('update:modelValue','');return}emit('update:modelValue',selected.value)}
function cancel(){creating.value=false;label.value='';key.value='';fieldType.value='text';error.value='';keyTouched.value=false}
async function create(){error.value='';const l=label.value.trim(),k=slug(key.value||label.value);if(!l){error.value='Field label is required.';return}if(!k){error.value='Field key is required.';return}saving.value=true;try{const created=await api.createContactField({label:l,key:k,field_type:fieldType.value,active:true});createdFields.value.push(created);const newValue=optionValue(created);selected.value=newValue;emit('field-created',created);emit('update:modelValue',newValue);cancel()}catch(e){error.value=e.message||'Could not create custom field.'}finally{saving.value=false}}
</script>

<template>
  <div class="custom-field-selector">
    <select v-model="selected" @change="changed">
      <option v-if="allowEmpty" value="">{{emptyLabel}}</option>
      <option v-for="field in availableFields" :key="field.id||field.key" :value="optionValue(field)">{{field.label||field.name||field.key}}</option>
      <option disabled>────────────</option>
      <option :value="CREATE">＋ Create new custom field…</option>
    </select>
    <div v-if="creating" class="creator">
      <div class="creator-head"><b>New custom field</b><button type="button" @click="cancel">×</button></div>
      <label>Label<input v-model="label" placeholder="e.g. Store Code"></label>
      <label>Key<input v-model="key" @input="keyTouched=true" placeholder="store_code"><small>Generated automatically from the label.</small></label>
      <label>Field type<select v-model="fieldType"><option value="text">Text</option><option value="textarea">Long text</option><option value="email">Email</option><option value="number">Number</option><option value="date">Date</option><option value="checkbox">Checkbox</option></select></label>
      <div v-if="error" class="error">{{error}}</div>
      <div class="actions"><button type="button" class="secondary" @click="cancel">Cancel</button><button type="button" class="primary" :disabled="saving" @click="create">{{saving?'Creating…':'Create & select'}}</button></div>
    </div>
  </div>
</template>

<style scoped>
.custom-field-selector>select{width:100%}.creator{margin-top:9px;padding:14px;border:1px solid #cfe1da;border-radius:10px;background:#f8fbfa}.creator-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}.creator-head button{border:0;background:transparent;font-size:21px;cursor:pointer}.creator label{display:flex;flex-direction:column;gap:6px;margin-bottom:11px;font-size:12px;font-weight:700}.creator input,.creator select{border:1px solid #d7e1dd;border-radius:8px;padding:10px;background:#fff}.creator small{color:#7c8b85;font-weight:400}.actions{display:flex;justify-content:flex-end;gap:8px}.actions button{padding:8px 12px;border-radius:8px;font-weight:700;cursor:pointer}.secondary{border:1px solid #d7e1dd;background:#fff}.primary{border:1px solid #17785d;background:#17785d;color:#fff}.error{margin-bottom:10px;padding:8px;border-radius:7px;background:#fff0f0;color:#a52b2b;font-size:12px}
</style>
