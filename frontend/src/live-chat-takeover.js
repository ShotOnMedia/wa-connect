import { api } from './api'
import './live-chat-takeover.css'

let timer=null,busy=false,lastKey='',rerender=false,selectionVersion=0
const BASE=import.meta.env.VITE_API_BASE_URL||'/api/v1'

async function controlRequest(path,options={}){
  const response=await fetch(`${BASE}/conversation-control${path}`,{credentials:'include',headers:{'Content-Type':'application/json'},...options})
  const payload=await response.json().catch(()=>({}))
  if(!response.ok)throw new Error(payload.detail||`Request failed (${response.status})`)
  return payload
}
function esc(v=''){return String(v).replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]))}
function selectedWaId(panel){return [...panel.querySelectorAll('p,span')].map(x=>x.textContent.trim()).find(v=>/^\+?\d{7,}$/.test(v.replace(/[\s-]/g,'')))?.replace(/[\s+-]/g,'')||''}
async function selectedWhatsApp(){const panel=document.querySelector('.shell:not(.wide-view) .contact-panel');if(!panel)return null;const waId=selectedWaId(panel);if(!waId)return null;const rows=await api.conversations('all').catch(()=>[]);const c=rows.find(x=>String(x.contact?.wa_id||'').replace(/\D/g,'')===waId.replace(/\D/g,''));return c?{channel:'whatsapp',conversation:c,panel}:null}
async function selectedTelegram(){const root=document.querySelector('.tg-chat'),panel=root?.querySelector('.customer-panel'),list=root?.querySelector('.tg-list');if(!root||!panel||!list)return null;const rows=[...list.querySelectorAll(':scope > .row')],index=rows.findIndex(r=>r.classList.contains('active'));if(index<0)return null;const conversations=await api.telegramConversations().catch(()=>[]),c=conversations[index];return c?{channel:'telegram',conversation:c,panel}:null}
function formatTime(v){if(!v)return'';try{return new Date(`${String(v).replace(' ','T')}Z`).toLocaleString()}catch(_){return String(v)}}
async function render(){
  if(busy){rerender=true;return}
  busy=true
  const version=selectionVersion
  try{
    const selected=await selectedTelegram()||await selectedWhatsApp()
    if(version!==selectionVersion){rerender=true;return}
    if(!selected){lastKey='';return}
    const {channel,conversation,panel}=selected,key=`${channel}:${conversation.id}`
    let root=panel.querySelector('.lc-takeover')
    if(key===lastKey&&root)return
    const [control,events]=await Promise.all([controlRequest(`/${channel}/${conversation.id}`),controlRequest(`/${channel}/${conversation.id}/events?limit=20`).catch(()=>[])])
    if(version!==selectionVersion){rerender=true;return}
    const current=await selectedTelegram()||await selectedWhatsApp()
    if(!current||`${current.channel}:${current.conversation.id}`!==key){rerender=true;return}
    current.panel.querySelector('.lc-takeover')?.remove();root=document.createElement('section');root.className='lc-takeover'
    const human=!!control.human_control
    root.innerHTML=`<div class="lc-takeover-head"><div><small>CONTROL</small><strong>${human?'Human Agent':'Automation'}</strong></div><span class="${human?'human':'auto'}">${human?'HUMAN':'AUTO'}</span></div><p>${human?'Automation is paused. Incoming replies remain in Live Chat until the conversation is returned to automation.':'Automation is active for this conversation.'}</p><button type="button" class="lc-takeover-btn ${human?'resume':'take'}">${human?'↪ Return to automation':'✋ Take control'}</button><details class="lc-event-log"><summary>Conversation events <span>${events.length}</span></summary><div>${events.length?events.slice().reverse().map(e=>`<div class="lc-event"><i></i><div><b>${esc(e.summary)}</b><small>${esc(formatTime(e.created_at))}</small></div></div>`).join(''):'<p>No control events yet.</p>'}</div></details><p class="lc-takeover-message" hidden></p>`
    const anchor=current.panel.querySelector('.live-chat-extras,.tg-profile-actions,.tg-whatsapp-summary,.snapshot');if(anchor)anchor.insertAdjacentElement('afterend',root);else current.panel.appendChild(root)
    root.querySelector('.lc-takeover-btn').onclick=async e=>{const btn=e.currentTarget,action=human?'resume':'takeover';btn.disabled=true;btn.textContent=human?'Returning…':'Taking control…';try{await controlRequest(`/${channel}/${conversation.id}/${action}`,{method:'POST'});lastKey='';selectionVersion++;schedule(20)}catch(err){const msg=root.querySelector('.lc-takeover-message');msg.textContent=err.message;msg.hidden=false;btn.disabled=false;btn.textContent=human?'↪ Return to automation':'✋ Take control'}}
    lastKey=key
  }catch(_){
  }finally{
    busy=false
    if(rerender){rerender=false;schedule(0)}
  }
}
function schedule(delay=80){clearTimeout(timer);timer=setTimeout(render,delay)}
function conversationChanged(){
  selectionVersion++
  lastKey=''
  document.querySelectorAll('.lc-takeover').forEach(el=>el.remove())
  schedule(0)
}
export function installLiveChatTakeover(){
  const observer=new MutationObserver(()=>schedule())
  observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['class']})
  document.addEventListener('click',event=>{
    if(event.target.closest('.tg-list .row,.conversation-list .conversation-item,.conversation-list .row')){
      requestAnimationFrame(()=>requestAnimationFrame(conversationChanged))
    }
  },true)
  schedule(0)
  window.addEventListener('beforeunload',()=>observer.disconnect(),{once:true})
}
