<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { api } from './api'

const props = defineProps({ contact: { type: Object, default: null }, admin: { type: Boolean, default: false }, channel: { type: String, default: 'whatsapp' }, compact: { type: Boolean, default: false } })
const fields = ref([]), values = reactive({}), loading = ref(false), saving = ref({}), savingAll = ref(false), error = ref(''), success = ref('')
const form = reactive({ key:'', label:'', field_type:'text', options:'', required:false, active:true, sort_order:0 })
const systemKeys=new Set(['name','subscriber_id','source','location','latitude','longitude'])
const systemFields=computed(()=>fields.value.filter(f=>f.system||systemKeys.has(f.key)))
const customFields=computed(()=>fields.value.filter(f=>!(f.system||systemKeys.has(f.key))))
let refreshTimer=null

function normalizeValue(field, value){ return field.field_type==='checkbox' ? value==='true'||value===true : (value ?? '') }
async function loadDefinitions(){ if(!props.admin)return; fields.value=await api.contactFields() }
async function loadValues({silent=false}={}){ if(!props.contact){fields.value=[];return} if(!silent)loading.value=true;error.value='';try{const rows=props.channel==='telegram'?await api.telegramContactCustomFields(props.contact.id):await api.contactCustomFields(props.contact.id);fields.value=rows;for(const f of rows){if(!saving.value[f.id])values[f.id]=normalizeValue(f,f.value)}}catch(e){if(!silent)error.value=e.message}finally{if(!silent)loading.value=false} }
async function saveValue(field, showMessage=true){if(field.system||systemKeys.has(field.key))return true;saving.value={...saving.value,[field.id]:true};error.value='';if(showMessage)success.value='';try{const row=props.channel==='telegram'?await api.setTelegramContactCustomField(props.contact.id,field.id,values[field.id]):await api.setContactCustomField(props.contact.id,field.id,values[field.id]);values[field.id]=normalizeValue(row,row.value);if(showMessage)success.value=`${field.label} saved.`;return true}catch(e){error.value=e.message;return false}finally{saving.value={...saving.value,[field.id]:false}}}
async function saveAll(){if(!props.contact||!customFields.value.length)return;savingAll.value=true;error.value='';success.value='';let ok=true;for(const field of customFields.value){if(!await saveValue(field,false)){ok=false;break}}if(ok)success.value='Custom fields saved.';savingAll.value=false}
async function createField(){error.value='';success.value='';try{const payload={...form,options:form.field_type==='select'?form.options.split('\n').map(v=>v.trim()).filter(Boolean):[]};await api.createContactField(payload);Object.assign(form,{key:'',label:'',field_type:'text',options:'',required:false,active:true,sort_order:fields.value.length});await loadDefinitions();success.value='Contact field created.'}catch(e){error.value=e.message}}
async function toggleField(field){error.value='';try{await api.updateContactField(field.id,{active:!field.active});await loadDefinitions()}catch(e){error.value=e.message}}
async function removeField(field){if(!confirm(`Delete custom field “${field.label}” and its stored values?`))return;error.value='';try{await api.deleteContactField(field.id);await loadDefinitions()}catch(e){error.value=e.message}}
function startLiveRefresh(){if(refreshTimer)window.clearInterval(refreshTimer);refreshTimer=null;if(props.compact&&props.contact)refreshTimer=window.setInterval(()=>{if(!savingAll.value)loadValues({silent:true})},3000)}
watch(()=>props.contact?.id,async()=>{await loadValues();startLiveRefresh()},{immediate:true})
watch(()=>props.compact,startLiveRefresh)
onMounted(()=>{if(props.admin&&!props.contact)loadDefinitions();startLiveRefresh()})
onBeforeUnmount(()=>{if(refreshTimer)window.clearInterval(refreshTimer)})
</script>

<template>
<section v-if="contact" class="contact-section custom-fields-section" :class="{compact}">
  <div class="section-title"><div><p class="eyebrow">Customer snapshot</p><h3>Subscriber fields</h3></div><span>{{fields.length}}</span></div>
  <div v-if="loading" class="empty-notes">Loading subscriber fields…</div>
  <template v-else>
    <div v-if="systemFields.length" class="system-list">
      <div v-for="field in systemFields" :key="field.id" class="system-row"><span><b>{{field.label}}</b><small>{{field.variable||`%${field.key}%`}}</small></span><strong>{{field.value||'—'}}</strong><i>AUTO</i></div>
    </div>
    <div v-if="customFields.length" class="custom-title"><b>Custom fields</b><span>Editable</span></div>
    <form v-if="customFields.length" class="custom-fields-form" @submit.prevent="saveAll">
      <div class="custom-fields-grid">
        <label v-for="field in customFields" :key="field.id" :class="{wide:field.field_type==='textarea'}">
          <span class="custom-field-label">{{field.label}} <i v-if="field.required">Required</i></span>
          <textarea v-if="field.field_type==='textarea'" v-model="values[field.id]" rows="3"/>
          <select v-else-if="field.field_type==='select'" v-model="values[field.id]"><option value="">— Select —</option><option v-for="option in field.options" :key="option" :value="option">{{option}}</option></select>
          <span v-else-if="field.field_type==='checkbox'" class="checkbox-field"><input v-model="values[field.id]" type="checkbox"/> <span>Yes</span></span>
          <input v-else v-model="values[field.id]" :type="field.field_type==='number'?'number':field.field_type==='date'?'date':field.field_type==='email'?'email':'text'"/>
          <small v-if="saving[field.id]">Saving…</small>
        </label>
      </div>
      <div class="custom-fields-actions"><span>Shared across WA Connect automations.</span><button class="primary" :disabled="savingAll">{{savingAll?'Saving…':'Save fields'}}</button></div>
    </form>
    <div v-if="!fields.length" class="empty-notes">No subscriber fields configured yet.</div>
  </template>
  <p v-if="success" class="success-message compact-message">{{success}}</p><p v-if="error" class="form-error compact-message">{{error}}</p>
</section>

<section v-else-if="admin" class="settings-card wide-card contact-fields-admin">
  <div class="section-title"><div><p class="eyebrow">Contact data</p><h2>Custom contact fields</h2><p class="muted">Define reusable fields that agents can maintain on every contact profile.</p></div></div>
  <form class="custom-field-create" @submit.prevent="createField"><div class="form-grid"><label>Label<input v-model="form.label" required placeholder="Company"/></label><label>Key<input v-model="form.key" required pattern="[a-z0-9_-]+" placeholder="company"/></label><label>Type<select v-model="form.field_type"><option value="text">Text</option><option value="textarea">Long text</option><option value="email">Email</option><option value="number">Number</option><option value="date">Date</option><option value="select">Select</option><option value="checkbox">Checkbox</option></select></label><label>Sort order<input v-model.number="form.sort_order" type="number"/></label><label v-if="form.field_type==='select'" class="wide">Options (one per line)<textarea v-model="form.options" rows="4" required/></label></div><div class="field-create-actions"><label class="inline-check"><input v-model="form.required" type="checkbox"/> Required</label><button class="primary">Create field</button></div></form>
  <div class="field-definition-list"><article v-for="field in fields" :key="field.id" class="field-definition-row"><div class="field-definition-copy"><strong>{{field.label}}</strong><span><code>{{field.key}}</code><b>·</b>{{field.field_type}}<template v-if="field.required"><b>·</b>required</template></span></div><span class="status-pill" :class="{inactive:!field.active}">{{field.active?'active':'inactive'}}</span><div class="field-definition-actions"><button class="secondary" @click="toggleField(field)">{{field.active?'Disable':'Enable'}}</button><button class="secondary danger" @click="removeField(field)">Delete</button></div></article><div v-if="!fields.length" class="empty-notes">No custom fields defined yet.</div></div>
  <p v-if="success" class="success-message">{{success}}</p><p v-if="error" class="form-error">{{error}}</p>
</section>
</template>

<style scoped>
.system-list{border:1px solid #e4ebe7;border-radius:10px;overflow:hidden;margin-bottom:14px}.system-row{display:grid;grid-template-columns:minmax(0,1fr) minmax(80px,1fr) auto;gap:10px;align-items:center;padding:10px 11px;border-bottom:1px solid #edf1ef}.system-row:last-child{border-bottom:0}.system-row span b,.system-row span small{display:block}.system-row span b{font-size:11px}.system-row span small{margin-top:2px;color:#8a9790;font:9px ui-monospace,monospace}.system-row strong{font-size:11px;word-break:break-word;text-align:right}.system-row i{font-style:normal;font-size:8px;font-weight:900;color:#16855a;background:#e6f7ef;border-radius:999px;padding:4px 6px}.custom-title{display:flex;justify-content:space-between;align-items:center;margin:13px 0 9px}.custom-title span{font-size:9px;color:#7d8d85}.custom-fields-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.compact .custom-fields-grid{grid-template-columns:1fr}.custom-fields-grid label{display:grid;gap:7px;min-width:0}.custom-fields-grid label.wide{grid-column:1/-1}.custom-field-label{color:#59675f;font-size:12px;font-weight:700}.custom-field-label i{font-style:normal;color:#258154;font-size:9px;text-transform:uppercase;letter-spacing:.05em;margin-left:5px}.custom-fields-grid input:not([type=checkbox]),.custom-fields-grid select,.custom-fields-grid textarea{box-sizing:border-box;width:100%;border:1px solid #d8e0da;border-radius:9px;padding:10px 11px;background:#fff;color:#17201c;outline:none}.custom-fields-grid textarea{resize:vertical}.custom-fields-grid input:focus,.custom-fields-grid select:focus,.custom-fields-grid textarea:focus{border-color:#70bc8e;box-shadow:0 0 0 3px rgba(37,211,102,.09)}.checkbox-field{min-height:40px;display:flex;align-items:center;gap:8px;border:1px solid #d8e0da;border-radius:9px;padding:8px 11px;background:#fff;color:#526158;font-size:12px}.checkbox-field input{width:16px;height:16px}.custom-fields-actions{display:flex;align-items:center;justify-content:space-between;gap:15px;margin-top:16px;padding-top:14px;border-top:1px solid #edf0ee}.custom-fields-actions span{color:#89948e;font-size:11px}.custom-fields-actions .primary{padding:9px 17px}.compact .custom-fields-actions{align-items:stretch;flex-direction:column}.compact .custom-fields-actions .primary{width:100%}.compact-message{margin:12px 0 0}.field-create-actions{display:flex;align-items:center;gap:14px;margin-top:-4px}.inline-check{display:flex;align-items:center;gap:7px;color:#59675f;font-size:12px}.field-definition-list{margin-top:22px;border-top:1px solid #edf0ee}.field-definition-row{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:14px;align-items:center;padding:15px 0;border-bottom:1px solid #edf0ee}.field-definition-copy strong,.field-definition-copy span{display:block}.field-definition-copy strong{font-size:14px}.field-definition-copy span{display:flex;align-items:center;gap:6px;color:#7c8982;font-size:11px;margin-top:4px;text-transform:capitalize}.field-definition-copy code{background:#f2f6f3;border-radius:5px;padding:2px 5px;color:#486057;text-transform:none}.field-definition-copy b{font-weight:400;color:#a0aaa4}.field-definition-actions{display:flex;gap:7px}.danger{color:#9d2c2c;border-color:#ead3d3}.danger:hover{background:#fff5f5}@media(max-width:900px){.custom-fields-grid{grid-template-columns:1fr}.custom-fields-grid label.wide{grid-column:auto}.field-definition-row{grid-template-columns:1fr auto}.field-definition-actions{grid-column:1/-1}}
</style>