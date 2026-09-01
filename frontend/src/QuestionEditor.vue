<script setup>
import { computed, nextTick, ref } from 'vue'
import CustomFieldSelector from './CustomFieldSelector.vue'
import VariableInsert from './VariableInsert.vue'
const props=defineProps({draft:{type:Object,required:true},fields:{type:Array,default:()=>[]}})
const emit=defineEmits(['field-created'])
const validationTextarea=ref(null)
const textTypes=new Set(['text','email','phone','date','number','integer','decimal']),lengthTypes=new Set(['text','email','phone']),numberTypes=new Set(['number','integer','decimal'])
const isText=computed(()=>textTypes.has(props.draft.reply_type)),hasLength=computed(()=>lengthTypes.has(props.draft.reply_type)),isNumber=computed(()=>numberTypes.has(props.draft.reply_type)),isDate=computed(()=>props.draft.reply_type==='date'),isMedia=computed(()=>['image','audio','video','document','sticker','media'].includes(props.draft.reply_type)),isTelegramPhone=computed(()=>props.draft.reply_type==='telegram_phone')
async function insertValidationVariable(token){
  const el=validationTextarea.value
  const value=props.draft.validation_error||''
  const start=el?.selectionStart??value.length,end=el?.selectionEnd??start
  props.draft.validation_error=value.slice(0,start)+token+value.slice(end)
  await nextTick()
  if(el){const pos=start+token.length;el.focus();el.setSelectionRange(pos,pos)}
}
</script>
<template><section class="question-editor">
<div class="section-title"><b>Reply & validation</b><small>Control what the contact may send before the flow continues.</small></div>
<label>Expected reply type<select v-model="draft.reply_type"><optgroup label="Text & data"><option value="text">Text</option><option value="email">Email address</option><option value="phone">Phone number (typed)</option><option value="telegram_phone">Telegram — Share phone number</option><option value="date">Date</option><option value="number">Number</option><option value="integer">Whole number</option></optgroup><optgroup label="Media"><option value="image">Photo / image</option><option value="audio">Audio / voice note</option><option value="video">Video</option><option value="document">Document / file</option><option value="sticker">Sticker</option><option value="media">Any media</option></optgroup></select><small class="help" v-if="isMedia">The flow remains waiting until the contact sends this media type.</small><small class="help telegram-help" v-if="isTelegramPhone">Telegram shows a native <b>Share phone number</b> button. When tapped, the supplied number is automatically stored in the system Subscriber ID field. This option is Telegram-only.</small></label>
<label class="check"><input v-model="draft.required" type="checkbox"><span><b>Reply required</b><small>Do not continue until a valid reply is received.</small></span></label>
<label v-if="!isTelegramPhone">Save valid reply to<CustomFieldSelector v-model="draft.capture_field_id" :fields="fields" value-mode="id" empty-label="Do not save reply" @field-created="emit('field-created',$event)"/><small class="help">Media fields store stable WhatsApp media metadata, including the Meta media ID.</small></label>
<label v-else>Telegram button text<input v-model="draft.telegram_phone_button_text" maxlength="64" placeholder="Share phone number"><small class="help">The system Subscriber ID field is populated automatically; no custom field is required.</small></label>
<div v-if="hasLength" class="two"><label>Minimum length<input v-model="draft.min_length" type="number" min="0" placeholder="None"></label><label>Maximum length<input v-model="draft.max_length" type="number" min="1" placeholder="None"></label></div>
<div v-if="isNumber" class="two"><label>Minimum value<input v-model="draft.min_value" type="number" placeholder="None"></label><label>Maximum value<input v-model="draft.max_value" type="number" placeholder="None"></label></div>
<label v-if="isDate">Date format<input v-model="draft.date_format" placeholder="%Y-%m-%d"><small class="help">Default is YYYY-MM-DD.</small></label>
<label v-if="isText">Validation pattern <span class="optional">optional</span><input v-model="draft.pattern" placeholder="Regular expression"><small class="help">Advanced: require the entire text reply to match a regular expression.</small></label>
<label>Invalid reply message<textarea ref="validationTextarea" v-model="draft.validation_error" rows="3" placeholder="Leave blank to use the automatic message"></textarea><VariableInsert :fields="fields" @insert="insertValidationVariable"/><small class="help">Sent when the reply has the wrong type or fails validation. The flow stays on this Question block.</small></label>
</section></template>
<style scoped>.question-editor{margin-top:20px;padding-top:18px;border-top:1px solid #e5ece9}.section-title{margin-bottom:15px}.section-title b,.section-title small{display:block}.section-title small,.help{margin-top:4px;color:#7c8b85;font-weight:400;line-height:1.4}.telegram-help{padding:9px 10px;background:#eef8fd;border:1px solid #d2edf9;border-radius:7px;color:#39758e}.two{display:grid;grid-template-columns:1fr 1fr;gap:12px}.check{flex-direction:row!important;align-items:flex-start;gap:10px!important;padding:11px 12px;border:1px solid #e0e8e4;border-radius:8px}.check input{width:auto!important;margin-top:2px}.check span,.check b,.check small{display:block}.check small{margin-top:3px;color:#7c8b85;font-weight:400}.optional{font-weight:400;color:#8b9a94}.question-editor label{display:flex;flex-direction:column;gap:6px;font-size:12px;font-weight:700;margin-bottom:14px}.question-editor input,.question-editor textarea,.question-editor select{border:1px solid #d7e1dd;border-radius:8px;padding:10px;font:inherit;background:#fff}</style>