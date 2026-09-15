import { api } from './api'

const BASE=(import.meta.env.VITE_API_BASE_URL||'/api/v1').replace(/\/$/,'')
let timer=null,busy=false,lastKey='',lastSignature=''

async function selected(){
  const tg=document.querySelector('.tg-chat')
  if(tg){const rows=[...tg.querySelectorAll('.tg-list > .row')],i=rows.findIndex(r=>r.classList.contains('active'));if(i>=0){const cs=await api.telegramConversations().catch(()=>[]);if(cs[i])return {channel:'telegram',conversation:cs[i],pane:tg.querySelector('.messages')}}}
  const pane=document.querySelector('.messages-panel,.conversation-messages,.chat-messages')
  const active=document.querySelector('.conversation-row.selected,.conversation-list .row.active')
  if(pane&&active){const cs=await api.conversations('all').catch(()=>[]),rows=[...document.querySelectorAll('.conversation-row,.conversation-list .row')],i=rows.indexOf(active);if(i>=0&&cs[i])return {channel:'whatsapp',conversation:cs[i],pane}}
  return null
}
async function events(channel,id){const r=await fetch(`${BASE}/conversation-control/${channel}/${id}/events?limit=200`,{credentials:'include'});if(!r.ok)return[];return r.json()}
function eventIcon(type){return ({human_takeover:'✋',automation_resumed:'↪',assignment_changed:'👤',status_changed:'●',flow_started:'▶',flow_completed:'✓',flow_reset:'↻'})[type]||'•'}
function when(v){try{return new Date(`${String(v).replace(' ','T')}Z`).toLocaleString(undefined,{year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})}catch(_){return String(v||'')}}
function eventTime(v){const s=String(v||'');const d=new Date(s.endsWith('Z')||/[+-]\d\d:\d\d$/.test(s)?s:`${s.replace(' ','T')}Z`);return Number.isNaN(d.getTime())?0:d.getTime()}
function messageTime(m){return eventTime(m.telegram_timestamp||m.created_at)}
async function render(){
  if(busy)return;busy=true
  try{
    const s=await selected();if(!s?.pane)return
    const key=`${s.channel}:${s.conversation.id}`,ev=await events(s.channel,s.conversation.id)
    const signature=ev.map(e=>`${e.id}:${e.created_at}`).join('|')
    if(key===lastKey&&signature===lastSignature&&s.pane.querySelectorAll('.lc-system-event').length===ev.length)return
    s.pane.querySelectorAll('.lc-system-event').forEach(x=>x.remove())
    if(!ev.length){lastKey=key;lastSignature=signature;return}
    const msgs=s.channel==='telegram'?await api.telegramMessages(s.conversation.id).catch(()=>[]):await api.messages(s.conversation.id).catch(()=>[])
    const articles=[...s.pane.querySelectorAll('article')]
    ev.forEach(e=>{
      const node=document.createElement('div');node.className=`lc-system-event lc-system-event-${e.event_type}`;node.dataset.eventId=e.id
      node.innerHTML=`<span>${eventIcon(e.event_type)} ${String(e.summary||'System event').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}</span><time>${when(e.created_at)}</time>`
      const t=eventTime(e.created_at);let before=null
      for(let i=0;i<Math.min(msgs.length,articles.length);i++){if(messageTime(msgs[i])>=t){before=articles[i];break}}
      if(before)s.pane.insertBefore(node,before);else s.pane.appendChild(node)
    })
    lastKey=key;lastSignature=signature
  }catch(e){console.warn('[event-timeline]',e)}finally{busy=false}
}
function schedule(delay=100){clearTimeout(timer);timer=setTimeout(render,delay)}
export function installLiveChatEventTimeline(){
  const observer=new MutationObserver(()=>schedule(120));observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['class']})
  document.addEventListener('click',e=>{if(e.target.closest('.tg-list .row,.conversation-row,.conversation-list .row,.lc-takeover-btn,[data-status],.tg-panel-reset')){lastKey='';lastSignature='';setTimeout(()=>schedule(0),250)}},true)
  schedule(0);window.addEventListener('beforeunload',()=>observer.disconnect(),{once:true})
}
