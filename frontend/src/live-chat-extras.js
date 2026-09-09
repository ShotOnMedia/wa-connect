import { api } from './api'
import './live-chat-extras.css'

let currentKey = ''
let renderToken = 0
let decoratedSignature = ''

function esc(value=''){return String(value).replace(/[&<>\"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[ch]))}
function selectedWaId(panel){
  const candidates=[...panel.querySelectorAll('p,span')].map(el=>el.textContent.trim()).filter(Boolean)
  return candidates.find(v=>/^\+?\d{7,}$/.test(v.replace(/[\s-]/g,'')))?.replace(/[\s+-]/g,'')||''
}
function fieldInput(field){
  const id=`lc-field-${field.id}`,value=field.value??''
  if(field.field_type==='textarea')return `<textarea id="${id}" rows="2">${esc(value)}</textarea>`
  if(field.field_type==='select')return `<select id="${id}"><option value="">— Select —</option>${(field.options||[]).map(o=>`<option value="${esc(o)}" ${String(o)===String(value)?'selected':''}>${esc(o)}</option>`).join('')}</select>`
  if(field.field_type==='checkbox')return `<label class="lc-check"><input id="${id}" type="checkbox" ${value===true||value==='true'?'checked':''}><span>Yes</span></label>`
  const type=field.field_type==='number'?'number':field.field_type==='date'?'date':field.field_type==='email'?'email':'text'
  return `<input id="${id}" type="${type}" value="${esc(value)}">`
}
function readField(root,field){const el=root.querySelector(`#lc-field-${field.id}`);return field.field_type==='checkbox'?el.checked:el.value}
function payloadOf(message){try{return JSON.parse(message?.payload_json||'{}')||{}}catch(_){return {}}}
function locationCoords(message){
  if(String(message?.message_type||'').toLowerCase()!=='location')return null
  let value=null
  try{value=payloadOf(message)?.location||JSON.parse(message.body||'{}')}catch(_){
    const match=String(message.body||'').match(/(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)/)
    if(match)value={latitude:match[1],longitude:match[2]}
  }
  const lat=Number(value?.latitude),lng=Number(value?.longitude)
  if(!Number.isFinite(lat)||!Number.isFinite(lng)||lat < -90||lat > 90||lng < -180||lng > 180)return null
  return {lat,lng}
}
function locationCard(coords){
  const {lat,lng}=coords,delta=.008,bbox=[lng-delta,lat-delta,lng+delta,lat+delta].join(',')
  const embed=`https://www.openstreetmap.org/export/embed.html?bbox=${encodeURIComponent(bbox)}&layer=mapnik&marker=${encodeURIComponent(`${lat},${lng}`)}`
  const open=`https://www.openstreetmap.org/?mlat=${lat}&mlon=${lng}#map=16/${lat}/${lng}`
  return `<div class="lc-location-card"><div class="lc-location-label">Location</div><iframe src="${esc(embed)}" loading="lazy" referrerpolicy="no-referrer-when-downgrade" title="Shared location on OpenStreetMap"></iframe><div class="lc-location-footer"><span>${esc(`${lat}, ${lng}`)}</span><a href="${esc(open)}" target="_blank" rel="noopener noreferrer">Open map ↗</a></div><small>© OpenStreetMap contributors</small></div>`
}
function imageInfo(message){
  if(String(message?.message_type||'').toLowerCase()!=='image')return null
  const payload=payloadOf(message),image=payload.image||payload.photo||payload.media||payload
  const url=image?.wa_connect_url||payload?.wa_connect_url||image?.stored_url||payload?.stored_url||image?.url||payload?.url||''
  if(!url)return null
  const caption=image?.caption??payload?.caption??message?.body??''
  return {url:String(url),caption:String(caption||'').trim()}
}
function imageCard(info){
  return `<div class="lc-image-card"><a href="${esc(info.url)}" target="_blank" rel="noopener noreferrer"><img src="${esc(info.url)}" loading="lazy" alt="Received WhatsApp image"></a>${info.caption?`<div class="lc-image-caption">${esc(info.caption)}</div>`:''}</div>`
}

async function decorateMessages(conversationId){
  const bubbles=[...document.querySelectorAll('.shell:not(.wide-view) .messages .bubble')]
  const items=await api.messages(conversationId).catch(()=>[])
  if(items.length!==bubbles.length)return
  const signature=`${conversationId}:${items.map(m=>`${m.id}:${m.status}:${m.message_type}:${m.payload_json||''}:${m.body||''}`).join('|')}`
  if(signature===decoratedSignature)return
  decoratedSignature=signature
  items.forEach((message,index)=>{
    const bubble=bubbles[index]
    bubble.querySelector('.lc-interactive-snapshot')?.remove()
    bubble.querySelector('.lc-location-card')?.remove()
    bubble.querySelector('.lc-image-card')?.remove()
    const coords=locationCoords(message)
    if(coords){
      const box=document.createElement('div');box.innerHTML=locationCard(coords);const card=box.firstElementChild
      const p=bubble.querySelector('p');if(p)p.hidden=true
      bubble.insertBefore(card,bubble.querySelector('footer'))
      return
    }
    const image=imageInfo(message)
    if(image){
      const box=document.createElement('div');box.innerHTML=imageCard(image);const card=box.firstElementChild
      const p=bubble.querySelector('p');if(p)p.hidden=true
      bubble.insertBefore(card,bubble.querySelector('footer'))
      return
    }
    if(message.direction!=='outbound'||message.message_type!=='interactive'||!message.payload_json)return
    const payload=payloadOf(message),snap=payload?._wa_connect
    if(!snap||snap.kind!=='interactive_snapshot'||!Array.isArray(snap.options)||!snap.options.length)return
    const box=document.createElement('div');box.className='lc-interactive-snapshot'
    box.innerHTML=`<div class="lc-interactive-label">Interactive</div><strong>${esc(snap.title||message.body||'Choose an option')}</strong><div class="lc-interactive-options">${snap.options.map(option=>`<div class="lc-interactive-option"><b>${esc(option.label||'Option')}</b>${option.description?`<span>${esc(option.description)}</span>`:''}</div>`).join('')}</div>`
    const p=bubble.querySelector('p');if(p)p.hidden=true
    bubble.insertBefore(box,bubble.querySelector('footer'))
  })
}

async function renderExtras(){
  const panel=document.querySelector('.shell:not(.wide-view) .contact-panel')
  if(!panel)return
  const waId=selectedWaId(panel)
  if(!waId){currentKey='';decoratedSignature='';panel.querySelector('.live-chat-extras')?.remove();return}
  const conversations=await api.conversations('all').catch(()=>[])
  const conversation=conversations.find(c=>String(c.contact?.wa_id||'').replace(/\D/g,'')===waId.replace(/\D/g,''))
  if(!conversation)return
  await decorateMessages(conversation.id)
  const key=`${conversation.id}:${conversation.contact.id}`
  if(currentKey===key&&panel.querySelector('.live-chat-extras'))return
  currentKey=key;const token=++renderToken
  const [fields,session,user]=await Promise.all([
    api.contactCustomFields(conversation.contact.id).catch(()=>[]),
    api.flowSession(conversation.id).catch(()=>conversation.flow_session||null),
    api.me().catch(()=>null),
  ])
  if(token!==renderToken)return
  panel.querySelector('.live-chat-extras')?.remove()
  const root=document.createElement('section');root.className='live-chat-extras'
  const canReset=session&&session.status!=='reset'
  root.innerHTML=`
    <div class="lc-section lc-flow-section">
      <div class="lc-title"><div><small>Automation</small><strong>Flow</strong></div>${session?`<span class="lc-status ${esc(session.status)}">${esc(session.status)}</span>`:''}</div>
      ${session?`<div class="lc-flow-card"><b>${esc(session.flow_name)}</b>${session.current_node_title?`<span>At: ${esc(session.current_node_title)}</span>`:''}${session.waiting_for?`<span>Waiting for ${esc(session.waiting_for)}</span>`:''}</div>`:'<p class="lc-empty">No flow session for this conversation.</p>'}
      ${canReset?'<button type="button" class="lc-reset">↻ Reset flow</button>':''}
    </div>
    <div class="lc-section">
      <div class="lc-title"><div><small>Profile data</small><strong>Custom fields</strong></div><span>${fields.length}</span></div>
      ${fields.length?`<form class="lc-fields">${fields.map(f=>`<label><span>${esc(f.label)}${f.required?' *':''}</span>${fieldInput(f)}</label>`).join('')}<button class="lc-save" type="submit">Save fields</button></form>`:'<p class="lc-empty">No custom fields configured.</p>'}
      ${user&&['admin','manager'].includes(user.role)?`<details class="lc-add-field"><summary>+ Add custom field</summary><form><input name="label" required placeholder="Field label"><input name="key" required pattern="[a-z][a-z0-9_]*" placeholder="field_key"><select name="field_type"><option value="text">Text</option><option value="textarea">Long text</option><option value="email">Email</option><option value="number">Number</option><option value="date">Date</option><option value="select">Select</option><option value="checkbox">Checkbox</option></select><button type="submit">Create field</button></form></details>`:''}
      <p class="lc-message" hidden></p>
    </div>`
  panel.appendChild(root)
  root.querySelector('.lc-reset')?.addEventListener('click',async e=>{
    if(!window.confirm(`Reset ${session.flow_name} for this conversation?\n\nConversation history, tags and custom fields will be kept.`))return
    const btn=e.currentTarget;btn.disabled=true;btn.textContent='Resetting…'
    try{
      const result=await api.resetFlowSession(conversation.id)
      if(result&&result.status!=='reset')throw new Error('The server did not place the flow session into reset state.')
      message(root,'Flow reset — subscriber is now in a neutral state.')
      currentKey='';decoratedSignature='';await renderExtras()
    }catch(err){message(root,err.message||'Could not reset flow.',true);btn.disabled=false;btn.textContent='↻ Reset flow'}
  })
  root.querySelector('.lc-fields')?.addEventListener('submit',async e=>{e.preventDefault();const btn=e.currentTarget.querySelector('.lc-save');btn.disabled=true;try{for(const field of fields)await api.setContactCustomField(conversation.contact.id,field.id,readField(root,field));message(root,'Custom fields saved.')}catch(err){message(root,err.message,true)}finally{btn.disabled=false}})
  root.querySelector('.lc-add-field form')?.addEventListener('submit',async e=>{e.preventDefault();const data=new FormData(e.currentTarget),label=String(data.get('label')||'').trim(),key=String(data.get('key')||'').trim(),field_type=String(data.get('field_type')||'text');try{await api.createContactField({label,key,field_type,options:[],required:false,active:true,sort_order:fields.length});currentKey='';await renderExtras()}catch(err){message(root,err.message,true)}})
}
function message(root,text,isError=false){const el=root.querySelector('.lc-message');if(!el)return;el.textContent=text;el.hidden=false;el.classList.toggle('error',isError);setTimeout(()=>{el.hidden=true},2500)}

export function installLiveChatExtras(){
  let timer=null
  const schedule=()=>{clearTimeout(timer);timer=setTimeout(()=>renderExtras().catch(()=>{}),80)}
  const observer=new MutationObserver(schedule)
  observer.observe(document.body,{subtree:true,childList:true,characterData:true})
  schedule()
  window.addEventListener('beforeunload',()=>observer.disconnect(),{once:true})
}
