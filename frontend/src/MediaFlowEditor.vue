<script setup>
import { ref } from 'vue'
import VariableInsert from './VariableInsert.vue'

const props=defineProps({draft:{type:Object,required:true},fields:{type:Array,default:()=>[]},mediaType:{type:String,required:true}})
const mediaInput=ref(null),captionInput=ref(null),filenameInput=ref(null)
function insert(prop,token,el){
  const input=el?.value,value=String(props.draft[prop]||''),start=input?.selectionStart??value.length,end=input?.selectionEnd??start
  props.draft[prop]=value.slice(0,start)+token+value.slice(end)
  requestAnimationFrame(()=>{if(input){const pos=start+token.length;input.focus();input.setSelectionRange(pos,pos)}})
}
</script>

<template>
  <div class="media-editor">
    <div class="media-help"><b>{{mediaType==='file'?'Document':mediaType}} source</b><span>Use a public HTTPS URL. WhatsApp also accepts an existing Meta media ID; Telegram accepts a Telegram file_id.</span></div>
    <label>Media URL / ID
      <input ref="mediaInput" v-model="draft.media" placeholder="https://example.com/media/file.jpg">
      <VariableInsert :fields="fields" @insert="token=>insert('media',token,mediaInput)"/>
    </label>
    <label v-if="mediaType!=='audio'">Caption
      <textarea ref="captionInput" v-model="draft.caption" rows="4" placeholder="Optional caption"></textarea>
      <VariableInsert :fields="fields" @insert="token=>insert('caption',token,captionInput)"/>
    </label>
    <label v-if="mediaType==='file'">Filename
      <input ref="filenameInput" v-model="draft.filename" placeholder="Optional document filename">
      <VariableInsert :fields="fields" @insert="token=>insert('filename',token,filenameInput)"/>
    </label>
  </div>
</template>

<style scoped>
.media-help{padding:12px 13px;margin-bottom:15px;border:1px solid #cfe4ef;border-radius:9px;background:#f3f9fc}.media-help b,.media-help span{display:block}.media-help b{text-transform:capitalize;font-size:12px;color:#16709a}.media-help span{margin-top:4px;font-size:11px;line-height:1.45;color:#71847b}
</style>
