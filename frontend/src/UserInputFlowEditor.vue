<script setup>
import {computed,onMounted,ref} from 'vue'
import {api} from './api'
const props=defineProps({draft:{type:Object,required:true}})
const campaigns=ref([]),loading=ref(false),error=ref('')
const selectedCampaign=computed(()=>{
  const id=Number(props.draft.campaign_id||0)
  if(id)return campaigns.value.find(c=>Number(c.id)===id)||null
  return campaigns.value.find(c=>c.name===props.draft.campaign_name)||null
})
async function load(){
  loading.value=true
  try{
    campaigns.value=(await api.campaigns()).filter(c=>c.status==='active')
    // Upgrade legacy name-only flow configs in the editor as soon as the
    // corresponding Campaign can be resolved. The builder's normal save then
    // persists the stable ID alongside the display/fallback name.
    if(!props.draft.campaign_id&&props.draft.campaign_name){
      const legacy=campaigns.value.find(c=>c.name===props.draft.campaign_name)
      if(legacy)props.draft.campaign_id=legacy.id
    }
  }catch(e){error.value=e.message}finally{loading.value=false}
}
function choose(value){
  const id=Number(value||0)
  const c=campaigns.value.find(x=>Number(x.id)===id)
  if(!c){
    props.draft.campaign_id=null
    props.draft.campaign_name=''
    return
  }
  props.draft.campaign_id=c.id
  props.draft.campaign_name=c.name
  props.draft.campaign_description=c.description||props.draft.campaign_description||''
}
onMounted(load)
</script>
<template><div class="editor"><div class="info"><b>User Input Flow</b><span>Select a reusable Campaign to run its questions automatically in sequence. Leave the selector on Manual questions to keep using individually connected Question blocks.</span></div><label>Question source<select :value="selectedCampaign?.id||''" @change="choose($event.target.value)"><option value="">Manual questions connected in the flow</option><option v-for="c in campaigns" :key="c.id" :value="c.id">{{c.name}} · {{c.question_count}} questions</option></select><small v-if="loading">Loading campaigns…</small><small v-else-if="error" class="error">{{error}}</small><small v-else-if="selectedCampaign">Runs <b>{{selectedCampaign.name}}</b> automatically. The Next output continues only after all {{selectedCampaign.question_count}} questions are answered.</small></label><template v-if="!selectedCampaign"><label>Campaign / submission name<input v-model="draft.campaign_name" placeholder="e.g. Customer Satisfaction"></label><label>Description<textarea v-model="draft.campaign_description" rows="3" placeholder="What is this input flow used for?"></textarea></label></template><template v-else><div class="campaign-card"><b>{{selectedCampaign.name}}</b><span>{{selectedCampaign.description||'Reusable questionnaire'}}</span><small>Campaign ID: {{selectedCampaign.id}} · saved as the stable questionnaire reference.</small><code>%campaign.answers%</code><small>Complete response JSON remains available after the Campaign finishes. Individual answers are still available as <code>%input.answer_key%</code>.</small></div></template><label>Completion webhook URL<input v-model="draft.webhook_url" placeholder="https://example.com/webhook"></label><label class="check"><input v-model="draft.webhook_enabled" type="checkbox"> POST the consolidated response when the input flow completes</label><label>Thank-you message<textarea v-model="draft.thank_you_text" rows="3" placeholder="Thank you for your response!"></textarea></label><small>Campaign submissions snapshot the exact question text with every answer, so later campaign edits do not rewrite historic responses.</small></div></template>
<style scoped>.editor{display:grid;gap:13px}.info{padding:12px;border:1px solid #cfe8dc;background:#f2faf6;border-radius:9px}.info b,.info span{display:block}.info span{font-size:11px;color:#71847b;margin-top:4px;line-height:1.45}.editor label{display:flex;flex-direction:column;gap:6px;font-size:12px;font-weight:700}.editor input,.editor textarea,.editor select{border:1px solid #d7e1dd;border-radius:8px;padding:10px;font:inherit;background:#fff}.editor .check{display:flex;flex-direction:row;align-items:center;font-weight:600}.editor .check input{width:auto}.editor>small,label small{color:#71847b;line-height:1.45}.error{color:#a23838}.campaign-card{border:1px solid #cfe3d9;border-radius:9px;background:#f7fcf9;padding:12px}.campaign-card b,.campaign-card span,.campaign-card code,.campaign-card small{display:block}.campaign-card span,.campaign-card small{color:#71847b;margin-top:4px}.campaign-card code{margin-top:9px;color:#168653;font-weight:800}</style>