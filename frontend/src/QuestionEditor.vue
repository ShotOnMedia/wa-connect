<script setup>
import { computed, ref, watch } from 'vue'
import { api } from './api'

const props=defineProps({draft:{type:Object,required:true},fields:{type:Array,default:()=>[]}})
const emit=defineEmits(['field-created'])
const textTypes=new Set(['text','email','phone','date','number','integer','decimal'])
const lengthTypes=new Set(['text','email','phone'])
const numberTypes=new Set(['number','integer','decimal'])
const isText=computed(()=>textTypes.has(props.draft.reply_type))
const hasLength=computed(()=>lengthTypes.has(props.draft.reply_type))
const isNumber=computed(()=>numberTypes.has(props.draft.reply_type))
const isDate=computed(()=>props.draft.reply_type==='date')
const isMedia=computed(()=>['image','audio','video','document','sticker','media'].includes(props.draft.reply_type))
const CREATE_FIELD='__create_new__'
const creating=ref(false),fieldLabel=ref(''),fieldKey=ref(''),fieldType=ref('text'),fieldError=ref(''),keyTouched=ref(false)
function slugify(value){return String(value||'').trim().toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_+|_+$/g,'')}
watch(fieldLabel,v=>{if(!keyTouched.value)fieldKey.value=slugify(v)})
watch(()=>props.draft.capture_field_id,v=>{if(v===CREATE_FIELD){creating.value=true;props.draft.capture_field_id=''}})
function cancelCreate(){creating.value=false;fieldLabel.value='';fieldKey.value='';fieldType.value='text';fieldError.value='';keyTouched.value=false}
async function createField(){fieldError.value='';const label=fieldLabel.value.trim(),key=slugify(fieldKey.value||fieldLabel.value);if(!label){fieldError.value='Field label is required.';return}if(!key){fieldError.value='Field key is required.';return}creating.value=true;try{const created=await api.createContactField({label,key,field_type:fieldType.value,active:true});emit('field-created',created);props.draft.capture_field_id=created.id;fieldLabel.value='';fieldKey.value='';fieldType.value='text';keyTouched.value=false;creating.value=false}catch(e){fieldError.value=e.message||'Could not create custom field.'}}
</script>

<template>
  <section class="question-editor">
    <div class="section-title"><b>Reply & validation</b><small>Control what the contact may send before the flow continues.</small></div>

    <label>Expected reply type
      <select v-model="draft.reply_type">
        <optgroup label="Text & data">
          <option value="text">Text</option><option value="email">Email address</option><option value="phone">Phone number</option><option value="date">Date</option><option value="number">Number</option><option value="integer">Whole number</option>
        </optgroup>
        <optgroup label="Media">
          <option value="image">Photo / image</option><option value="audio">Audio / voice note</option><option value="video">Video</option><option value="document">Document / file</option><option value="sticker">Sticker</option><option value="media">Any media</option>
        </optgroup>
      </select>
      <small class="help" v-if="isMedia">The flow remains waiting until the contact sends this media type.</small>
    </label>

    <label class="check"><input v-model="draft.required" type="checkbox"><span><b>Reply required</b><small>Do not continue until a valid reply is received.</small></span></label>

    <label>Save valid reply to
      <select v-model="draft.capture_field_id">
        <option value="">Do not save reply</option>
        <option v-for="field in fields" :key="field.id" :value="field.id">{{field.label||field.name||field.key}}</option>
        <option disabled>────────────</option>
        <option :value="CREATE_FIELD">＋ Create new custom field…</option>
      </select>
      <small class="help">Media fields store stable WhatsApp media metadata, including the Meta media ID.</small>
    </label>

    <div v-if="creating" class="new-field">
      <div class="new-field-title"><b>New custom field</b><button type="button" class="close" @click="cancelCreate">×</button></div>
      <label>Label<input v-model="fieldLabel" placeholder="e.g. Store Code"></label>
      <label>Key<input v-model="fieldKey" @input="keyTouched=true" placeholder="store_code"><small class="help">Used internally. Generated automatically from the label.</small></label>
      <label>Field type
        <select v-model="fieldType"><option value="text">Text</option><option value="textarea">Long text</option><option value="email">Email</option><option value="number">Number</option><option value="date">Date</option><option value="checkbox">Checkbox</option></select>
      </label>
      <div v-if="fieldError" class="field-error">{{fieldError}}</div>
      <div class="new-field-actions"><button type="button" class="secondary" @click="cancelCreate">Cancel</button><button type="button" class="primary" @click="createField">Create & select</button></div>
    </div>

    <div v-if="hasLength" class="two"><label>Minimum length<input v-model="draft.min_length" type="number" min="0" placeholder="None"></label><label>Maximum length<input v-model="draft.max_length" type="number" min="1" placeholder="None"></label></div>
    <div v-if="isNumber" class="two"><label>Minimum value<input v-model="draft.min_value" type="number" placeholder="None"></label><label>Maximum value<input v-model="draft.max_value" type="number" placeholder="None"></label></div>
    <label v-if="isDate">Date format<input v-model="draft.date_format" placeholder="%Y-%m-%d"><small class="help">Default is YYYY-MM-DD.</small></label>
    <label v-if="isText">Validation pattern <span class="optional">optional</span><input v-model="draft.pattern" placeholder="Regular expression"><small class="help">Advanced: require the entire text reply to match a regular expression.</small></label>

    <label>Invalid reply message<textarea v-model="draft.validation_error" rows="3" placeholder="Leave blank to use the automatic message"></textarea><small class="help">Sent when the reply has the wrong type or fails validation. The flow stays on this Question block.</small></label>
  </section>
</template>

<style scoped>
.question-editor{margin-top:20px;padding-top:18px;border-top:1px solid #e5ece9}.section-title{margin-bottom:15px}.section-title b,.section-title small{display:block}.section-title small,.help{margin-top:4px;color:#7c8b85;font-weight:400;line-height:1.4}.two{display:grid;grid-template-columns:1fr 1fr;gap:12px}.check{flex-direction:row!important;align-items:flex-start;gap:10px!important;padding:11px 12px;border:1px solid #e0e8e4;border-radius:8px}.check input{width:auto!important;margin-top:2px}.check span,.check b,.check small{display:block}.check small{margin-top:3px;color:#7c8b85;font-weight:400}.optional{font-weight:400;color:#8b9a94}.question-editor label{display:flex;flex-direction:column;gap:6px;font-size:12px;font-weight:700;margin-bottom:14px}.question-editor input,.question-editor textarea,.question-editor select{border:1px solid #d7e1dd;border-radius:8px;padding:10px;font:inherit;background:#fff}.new-field{margin:-2px 0 16px;padding:14px;border:1px solid #cfe1da;border-radius:10px;background:#f8fbfa}.new-field-title{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}.close{border:0;background:transparent;font-size:22px;line-height:1;cursor:pointer;color:#718079}.new-field-actions{display:flex;justify-content:flex-end;gap:8px}.new-field-actions button{border-radius:8px;padding:8px 12px;font-weight:700;cursor:pointer}.secondary{border:1px solid #d7e1dd;background:#fff}.primary{border:1px solid #17785d;background:#17785d;color:#fff}.field-error{margin:-4px 0 12px;padding:8px 10px;border-radius:7px;background:#fff0f0;color:#a52b2b;font-size:12px}
</style>
